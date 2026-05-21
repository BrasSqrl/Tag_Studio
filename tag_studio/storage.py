from __future__ import annotations

import hashlib
import json
import os
import shutil
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from filelock import FileLock

from .defaults import DEFAULT_OUTCOME_TAXONOMY, DEFAULT_SCORING_RUBRIC, DEFAULT_SECTIONS, DEFAULT_TAGS, SCHEMA_VERSION
from .models import MemoRecord, ReviewRecord, utc_now

DEFAULT_WORKSPACE = Path(os.getenv("TAG_STUDIO_LOCAL_WORKSPACE", "tag_studio_workspace"))
S3_INDEX_RELATIVE_PATH = "memos/index.json"

_LAST_SYNC_STATUS: dict[str, Any] = {
    "ok": True,
    "message": "Local storage active.",
    "last_key": "",
    "updated_at": "",
}


def slugify(value: str) -> str:
    safe = "".join(ch.lower() if ch.isalnum() else "_" for ch in value.strip())
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe.strip("_") or "item"


def storage_backend_name() -> str:
    backend = os.getenv("TAG_STUDIO_STORAGE_BACKEND", "local").strip().lower()
    return backend if backend in {"local", "s3"} else "local"


def using_s3_storage() -> bool:
    return storage_backend_name() == "s3"


def _s3_bucket() -> str:
    return os.getenv("TAG_STUDIO_S3_BUCKET", "").strip()


def _s3_prefix() -> str:
    return os.getenv("TAG_STUDIO_S3_PREFIX", "tag-studio/prod").strip().strip("/")


def _aws_region() -> str:
    return os.getenv("AWS_REGION", "").strip() or os.getenv("AWS_DEFAULT_REGION", "").strip()


def _s3_extra_args() -> dict[str, str]:
    extra_args: dict[str, str] = {}
    sse = os.getenv("TAG_STUDIO_S3_SSE", "").strip()
    kms_key_id = os.getenv("TAG_STUDIO_S3_KMS_KEY_ID", "").strip()
    if sse:
        extra_args["ServerSideEncryption"] = sse
    if sse == "aws:kms" and kms_key_id:
        extra_args["SSEKMSKeyId"] = kms_key_id
    return extra_args


@lru_cache(maxsize=1)
def _s3_client():
    import boto3  # type: ignore

    region = _aws_region()
    return boto3.client("s3", region_name=region or None)


def _mark_sync(ok: bool, message: str, key: str = "") -> None:
    _LAST_SYNC_STATUS.update({"ok": ok, "message": message, "last_key": key, "updated_at": utc_now()})


def _workspace_for_path(path: Path) -> Path | None:
    try:
        path.resolve().relative_to(DEFAULT_WORKSPACE.resolve())
    except ValueError:
        return None
    return DEFAULT_WORKSPACE


def _object_key(workspace: Path, path: Path) -> str:
    relative = path.resolve().relative_to(workspace.resolve()).as_posix()
    prefix = _s3_prefix()
    return f"{prefix}/{relative}" if prefix else relative


def _relative_key(relative_path: str) -> str:
    clean = PurePosixPath(relative_path).as_posix().lstrip("/")
    prefix = _s3_prefix()
    return f"{prefix}/{clean}" if prefix else clean


def _path_from_key(workspace: Path, key: str) -> Path:
    prefix = _s3_prefix()
    relative = key
    if prefix and key.startswith(f"{prefix}/"):
        relative = key[len(prefix) + 1 :]
    return workspace.joinpath(*PurePosixPath(relative).parts)


def storage_status(workspace: Path = DEFAULT_WORKSPACE) -> dict[str, Any]:
    return {
        "backend": storage_backend_name(),
        "local_workspace": str(workspace),
        "s3_bucket": _s3_bucket() if using_s3_storage() else "",
        "s3_prefix": _s3_prefix() if using_s3_storage() else "",
        "aws_region": _aws_region() if using_s3_storage() else "",
        "last_sync": dict(_LAST_SYNC_STATUS),
    }


@lru_cache(maxsize=1)
def storage_readiness() -> tuple[bool, str]:
    if not using_s3_storage():
        return True, "Local storage is ready."

    bucket = _s3_bucket()
    region = _aws_region()
    if not bucket:
        return False, "S3 storage is selected, but TAG_STUDIO_S3_BUCKET is not set."
    if not region:
        return False, "S3 storage is selected, but AWS_REGION is not set."

    try:
        client = _s3_client()
        client.head_bucket(Bucket=bucket)
        health_key = _relative_key(".healthcheck.json")
        body = json.dumps({"app": "tag-studio", "checked_at": utc_now()}).encode("utf-8")
        client.put_object(Bucket=bucket, Key=health_key, Body=body, **_s3_extra_args())
        client.get_object(Bucket=bucket, Key=health_key)
    except Exception as exc:  # noqa: BLE001 - converted to a friendly app readiness message.
        _mark_sync(False, "S3 storage is not reachable.")
        return False, f"Tag Studio cannot read and write to the configured S3 bucket: {exc}"

    _mark_sync(True, "S3 storage is ready.", health_key)
    return True, "S3 storage is ready."


def _remote_key_exists(key: str) -> bool:
    if not using_s3_storage():
        return False
    try:
        _s3_client().head_object(Bucket=_s3_bucket(), Key=key)
        return True
    except Exception:
        return False


def _iter_remote_keys(relative_prefix: str) -> list[str]:
    if not using_s3_storage():
        return []
    prefix = _relative_key(relative_prefix).rstrip("/")
    if prefix:
        prefix += "/"
    client = _s3_client()
    paginator = client.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=_s3_bucket(), Prefix=prefix):
        keys.extend(item["Key"] for item in page.get("Contents", []) if item.get("Key"))
    return keys


def _upload_file(workspace: Path, path: Path) -> None:
    if not using_s3_storage() or not path.is_file() or path.name.endswith(".lock"):
        return
    key = _object_key(workspace, path)
    try:
        extra_args = _s3_extra_args()
        if extra_args:
            _s3_client().upload_file(str(path), _s3_bucket(), key, ExtraArgs=extra_args)
        else:
            _s3_client().upload_file(str(path), _s3_bucket(), key)
        _mark_sync(True, "Uploaded to S3.", key)
    except Exception as exc:  # noqa: BLE001 - keep write path explicit for diagnostics.
        _mark_sync(False, f"S3 upload failed: {exc}", key)
        raise


def sync_path_to_remote(workspace: Path, path: Path) -> None:
    if not using_s3_storage():
        return
    if path.is_dir():
        for child in path.rglob("*"):
            _upload_file(workspace, child)
    else:
        _upload_file(workspace, path)


def _download_key(workspace: Path, key: str) -> None:
    if not using_s3_storage():
        return
    target = _path_from_key(workspace, key)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        _s3_client().download_file(_s3_bucket(), key, str(target))
        _mark_sync(True, "Downloaded from S3.", key)
    except Exception as exc:  # noqa: BLE001 - keep hydration errors visible to Admin Tools.
        _mark_sync(False, f"S3 download failed: {exc}", key)
        raise


def hydrate_path_from_remote(workspace: Path, path: Path) -> None:
    if not using_s3_storage() or path.exists():
        return
    key = _object_key(workspace, path)
    if _remote_key_exists(key):
        _download_key(workspace, key)


def hydrate_prefix_from_remote(workspace: Path, relative_prefix: str) -> None:
    if not using_s3_storage():
        return
    for key in _iter_remote_keys(relative_prefix):
        if key.endswith(".lock"):
            continue
        _download_key(workspace, key)


def hydrate_workspace_metadata(workspace: Path) -> None:
    if not using_s3_storage():
        return
    hydrate_prefix_from_remote(workspace, "config")
    hydrate_path_from_remote(workspace, workspace / S3_INDEX_RELATIVE_PATH)


def hydrate_memo_from_remote(workspace: Path, memo_id: str, force: bool = False) -> None:
    if not using_s3_storage():
        return
    base = memo_dir(workspace, memo_id)
    if not force and (base / "memo_record.json").exists() and (base / "source" / "source.pdf").exists():
        return
    hydrate_prefix_from_remote(workspace, f"memos/{memo_id}")


def _remote_memo_ids() -> list[str]:
    keys = _iter_remote_keys("memos")
    ids = set()
    prefix = _relative_key("memos").rstrip("/") + "/"
    for key in keys:
        if not key.startswith(prefix):
            continue
        relative = key[len(prefix) :]
        parts = PurePosixPath(relative).parts
        if parts and parts[0] != "index.json":
            ids.add(parts[0])
    return sorted(ids)


def _read_memo_index(workspace: Path) -> list[str]:
    raw = read_json(workspace / S3_INDEX_RELATIVE_PATH, {"memo_ids": []})
    if isinstance(raw, list):
        return sorted(str(item) for item in raw)
    if isinstance(raw, dict):
        return sorted(str(item) for item in raw.get("memo_ids", []))
    return []


def _update_memo_index(workspace: Path, memo_id: str | None = None) -> None:
    if not using_s3_storage():
        return
    local_ids = []
    memos = workspace / "memos"
    if memos.exists():
        local_ids = [path.name for path in memos.iterdir() if path.is_dir()]
    ids = set(_read_memo_index(workspace)) | set(local_ids)
    if memo_id:
        ids.add(memo_id)
    index = {"memo_ids": sorted(ids), "updated_at": utc_now()}
    write_json(workspace / S3_INDEX_RELATIVE_PATH, index)


def read_json(path: Path, default: Any) -> Any:
    if using_s3_storage() and not path.exists():
        workspace = _workspace_for_path(path)
        if workspace:
            hydrate_path_from_remote(workspace, path)
    if not path.exists():
        return default
    lock = FileLock(str(path) + ".lock")
    with lock:
        return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(path) + ".lock")
    with lock:
        temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(path)
    workspace = _workspace_for_path(path)
    if workspace:
        sync_path_to_remote(workspace, path)


def append_jsonl(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(path) + ".lock")
    with lock, path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False) + "\n")
    workspace = _workspace_for_path(path)
    if workspace:
        sync_path_to_remote(workspace, path)


def stable_hash(data: Any) -> str:
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_workspace(workspace: Path = DEFAULT_WORKSPACE) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)
    config_dir = workspace / "config"
    config_dir.mkdir(exist_ok=True)
    if using_s3_storage():
        hydrate_workspace_metadata(workspace)

    section_path = config_dir / "section_schema.json"
    tag_path = config_dir / "tag_schema.json"
    meta_path = config_dir / "schema_meta.json"

    if not section_path.exists():
        write_json(section_path, [section.model_dump() for section in DEFAULT_SECTIONS])
    if not tag_path.exists():
        write_json(tag_path, [tag.model_dump() for tag in DEFAULT_TAGS])
    outcome_path = config_dir / "outcome_taxonomy.json"
    scoring_path = config_dir / "scoring_rubric.json"
    if not outcome_path.exists():
        write_json(outcome_path, DEFAULT_OUTCOME_TAXONOMY)
    if not scoring_path.exists():
        write_json(scoring_path, [record.model_dump() for record in DEFAULT_SCORING_RUBRIC])
    if not meta_path.exists():
        write_json(
            meta_path,
            {
                "schema_version": SCHEMA_VERSION,
                "schema_hash": active_schema_hash(workspace),
                "created_at": utc_now(),
            },
        )
    if using_s3_storage():
        (workspace / "memos").mkdir(parents=True, exist_ok=True)
        if not (workspace / S3_INDEX_RELATIVE_PATH).exists():
            write_json(workspace / S3_INDEX_RELATIVE_PATH, {"memo_ids": _remote_memo_ids(), "updated_at": utc_now()})
    return workspace


def active_schema_payload(workspace: Path) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "sections": read_json(config_path(workspace, "section_schema.json"), []),
        "tags": read_json(config_path(workspace, "tag_schema.json"), []),
        "outcome_taxonomy": read_json(config_path(workspace, "outcome_taxonomy.json"), []),
        "scoring_rubric": read_json(config_path(workspace, "scoring_rubric.json"), []),
    }


def active_schema_hash(workspace: Path) -> str:
    return stable_hash(active_schema_payload(workspace))


def config_path(workspace: Path, name: str) -> Path:
    return workspace / "config" / name


def memo_dir(workspace: Path, memo_id: str) -> Path:
    return workspace / "memos" / memo_id


def create_memo_workspace(
    workspace: Path,
    pdf_bytes: bytes,
    file_name: str,
    memo_id: str,
    memo_type: str,
    facility_type: str,
    customer_id: str,
    reviewer: str,
) -> MemoRecord:
    base = memo_dir(workspace, memo_id)
    for subdir in [
        "source",
        "pages",
        "extraction",
        "sections",
        "facilities",
        "tags",
        "evidence",
        "outcomes",
        "tables",
        "review",
        "exports",
        "audit",
        "audit/events",
        "schema",
    ]:
        (base / subdir).mkdir(parents=True, exist_ok=True)

    source_pdf = base / "source" / "source.pdf"
    source_pdf.write_bytes(pdf_bytes)
    source_hash = file_sha256(source_pdf)
    (base / "source" / "source_hash.txt").write_text(source_hash, encoding="utf-8")
    (base / "source" / "original_file_name.txt").write_text(file_name, encoding="utf-8")
    sync_path_to_remote(workspace, base / "source")

    record = MemoRecord(
        memo_id=memo_id,
        source_file_name=file_name,
        source_hash=source_hash,
        memo_type=memo_type,
        facility_type=facility_type,
        customer_id=customer_id,
        reviewer=reviewer,
        schema_version=SCHEMA_VERSION,
        schema_hash=active_schema_hash(workspace),
    )
    write_json(base / "memo_record.json", record.model_dump())
    write_json(
        base / "schema" / "schema_snapshot.json",
        {
            **active_schema_payload(workspace),
            "schema_hash": record.schema_hash,
            "created_at": utc_now(),
        },
    )
    write_json(
        base / "review" / "review_status.json",
        ReviewRecord(
            memo_id=memo_id,
            reviewer=reviewer,
            assigned_to=reviewer,
            assignment_status="Assigned to reviewer" if reviewer else "Unassigned",
            schema_version=SCHEMA_VERSION,
            schema_hash=record.schema_hash,
        ).model_dump(),
    )
    write_json(base / "facilities" / "facility_records.json", [])
    write_json(base / "outcomes" / "facility_outcome_summaries.json", [])
    write_json(base / "outcomes" / "outcome_events.json", [])
    write_json(base / "outcomes" / "foreseeability_assessments.json", [])
    write_json(base / "tables" / "table_metric_records.json", [])
    append_audit(workspace, memo_id, "memo_created", {"source_file_name": file_name})
    _update_memo_index(workspace, memo_id)
    return record


def list_memo_ids(workspace: Path) -> list[str]:
    if using_s3_storage():
        hydrate_path_from_remote(workspace, workspace / S3_INDEX_RELATIVE_PATH)
        ids = _read_memo_index(workspace)
        if not ids:
            ids = _remote_memo_ids()
            write_json(workspace / S3_INDEX_RELATIVE_PATH, {"memo_ids": ids, "updated_at": utc_now()})
        return ids

    memos = workspace / "memos"
    if not memos.exists():
        return []
    return sorted(path.name for path in memos.iterdir() if path.is_dir())


def load_memo_record(workspace: Path, memo_id: str) -> dict[str, Any]:
    hydrate_path_from_remote(workspace, memo_dir(workspace, memo_id) / "memo_record.json")
    return read_json(memo_dir(workspace, memo_id) / "memo_record.json", {})


def save_memo_record(workspace: Path, memo_id: str, data: dict[str, Any]) -> None:
    data["updated_at"] = utc_now()
    write_json(memo_dir(workspace, memo_id) / "memo_record.json", data)
    _update_memo_index(workspace, memo_id)


def load_review(workspace: Path, memo_id: str) -> dict[str, Any]:
    return read_json(memo_dir(workspace, memo_id) / "review" / "review_status.json", {"memo_id": memo_id, "status": "Draft"})


def save_review(workspace: Path, memo_id: str, data: dict[str, Any]) -> None:
    data["updated_at"] = utc_now()
    write_json(memo_dir(workspace, memo_id) / "review" / "review_status.json", data)
    append_audit(workspace, memo_id, "review_status_saved", data)


def load_sections(workspace: Path, memo_id: str) -> list[dict[str, Any]]:
    return read_json(memo_dir(workspace, memo_id) / "sections" / "sections.json", [])


def save_sections(workspace: Path, memo_id: str, sections: list[dict[str, Any]]) -> None:
    write_json(memo_dir(workspace, memo_id) / "sections" / "sections.json", sections)
    append_audit(workspace, memo_id, "sections_saved", {"section_count": len(sections)})


def load_tags(workspace: Path, memo_id: str) -> list[dict[str, Any]]:
    return read_json(memo_dir(workspace, memo_id) / "tags" / "tag_records.json", [])


def save_tags(workspace: Path, memo_id: str, tags: list[dict[str, Any]]) -> None:
    write_json(memo_dir(workspace, memo_id) / "tags" / "tag_records.json", tags)
    append_audit(workspace, memo_id, "tags_saved", {"tag_count": len(tags)})


def load_evidence(workspace: Path, memo_id: str) -> list[dict[str, Any]]:
    return read_json(memo_dir(workspace, memo_id) / "evidence" / "evidence_records.json", [])


def save_evidence(workspace: Path, memo_id: str, evidence: list[dict[str, Any]]) -> None:
    write_json(memo_dir(workspace, memo_id) / "evidence" / "evidence_records.json", evidence)
    append_audit(workspace, memo_id, "evidence_saved", {"evidence_count": len(evidence)})


def load_facilities(workspace: Path, memo_id: str) -> list[dict[str, Any]]:
    return read_json(memo_dir(workspace, memo_id) / "facilities" / "facility_records.json", [])


def save_facilities(workspace: Path, memo_id: str, facilities: list[dict[str, Any]]) -> None:
    write_json(memo_dir(workspace, memo_id) / "facilities" / "facility_records.json", facilities)
    append_audit(workspace, memo_id, "facilities_saved", {"facility_count": len(facilities)})


def load_outcome_summaries(workspace: Path, memo_id: str) -> list[dict[str, Any]]:
    return read_json(memo_dir(workspace, memo_id) / "outcomes" / "facility_outcome_summaries.json", [])


def save_outcome_summaries(workspace: Path, memo_id: str, summaries: list[dict[str, Any]]) -> None:
    write_json(memo_dir(workspace, memo_id) / "outcomes" / "facility_outcome_summaries.json", summaries)
    append_audit(workspace, memo_id, "outcome_summaries_saved", {"summary_count": len(summaries)})


def load_outcome_events(workspace: Path, memo_id: str) -> list[dict[str, Any]]:
    return read_json(memo_dir(workspace, memo_id) / "outcomes" / "outcome_events.json", [])


def save_outcome_events(workspace: Path, memo_id: str, events: list[dict[str, Any]]) -> None:
    write_json(memo_dir(workspace, memo_id) / "outcomes" / "outcome_events.json", events)
    append_audit(workspace, memo_id, "outcome_events_saved", {"event_count": len(events)})


def load_foreseeability_assessments(workspace: Path, memo_id: str) -> list[dict[str, Any]]:
    return read_json(memo_dir(workspace, memo_id) / "outcomes" / "foreseeability_assessments.json", [])


def save_foreseeability_assessments(workspace: Path, memo_id: str, assessments: list[dict[str, Any]]) -> None:
    write_json(memo_dir(workspace, memo_id) / "outcomes" / "foreseeability_assessments.json", assessments)
    append_audit(workspace, memo_id, "foreseeability_assessments_saved", {"assessment_count": len(assessments)})


def load_table_metrics(workspace: Path, memo_id: str) -> list[dict[str, Any]]:
    return read_json(memo_dir(workspace, memo_id) / "tables" / "table_metric_records.json", [])


def save_table_metrics(workspace: Path, memo_id: str, metrics: list[dict[str, Any]]) -> None:
    write_json(memo_dir(workspace, memo_id) / "tables" / "table_metric_records.json", metrics)
    append_audit(workspace, memo_id, "table_metrics_saved", {"metric_count": len(metrics)})


def load_scoring_rubric(workspace: Path) -> list[dict[str, Any]]:
    return read_json(config_path(workspace, "scoring_rubric.json"), [])


def save_scoring_rubric(workspace: Path, records: list[dict[str, Any]]) -> None:
    write_json(config_path(workspace, "scoring_rubric.json"), records)


def append_audit(workspace: Path, memo_id: str, event_type: str, payload: dict[str, Any]) -> None:
    event_id = uuid4().hex
    event = {"event_id": event_id, "memo_id": memo_id, "event_type": event_type, "payload": payload, "created_at": utc_now()}
    write_json(memo_dir(workspace, memo_id) / "audit" / "events" / f"{event['created_at'].replace(':', '').replace('.', '')}_{event_id}.json", event)


def load_audit_events(workspace: Path, memo_id: str) -> list[dict[str, Any]]:
    events_dir = memo_dir(workspace, memo_id) / "audit" / "events"
    hydrate_prefix_from_remote(workspace, f"memos/{memo_id}/audit/events")
    if not events_dir.exists():
        return []
    events = [read_json(path, {}) for path in sorted(events_dir.glob("*.json"))]
    return [event for event in events if event]


def reset_demo_workspace(workspace: Path) -> None:
    if workspace.exists():
        shutil.rmtree(workspace)
    ensure_workspace(workspace)
