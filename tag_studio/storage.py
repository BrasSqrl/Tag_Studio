from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from filelock import FileLock

from .defaults import DEFAULT_SECTIONS, DEFAULT_TAGS, SCHEMA_VERSION
from .models import MemoRecord, ReviewRecord, utc_now


DEFAULT_WORKSPACE = Path("tag_studio_workspace")


def slugify(value: str) -> str:
    safe = "".join(ch.lower() if ch.isalnum() else "_" for ch in value.strip())
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe.strip("_") or "item"


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(path) + ".lock")
    with lock:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def append_jsonl(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(path) + ".lock")
    with lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(data, ensure_ascii=False) + "\n")


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

    section_path = config_dir / "section_schema.json"
    tag_path = config_dir / "tag_schema.json"
    meta_path = config_dir / "schema_meta.json"

    if not section_path.exists():
        write_json(section_path, [section.model_dump() for section in DEFAULT_SECTIONS])
    if not tag_path.exists():
        write_json(tag_path, [tag.model_dump() for tag in DEFAULT_TAGS])
    if not meta_path.exists():
        write_json(meta_path, {"schema_version": SCHEMA_VERSION, "created_at": utc_now()})
    return workspace


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
    borrower_name_or_hash: str,
    reviewer: str,
) -> MemoRecord:
    base = memo_dir(workspace, memo_id)
    for subdir in ["source", "pages", "extraction", "sections", "tags", "evidence", "review", "exports", "audit"]:
        (base / subdir).mkdir(parents=True, exist_ok=True)

    source_pdf = base / "source" / "source.pdf"
    source_pdf.write_bytes(pdf_bytes)
    source_hash = file_sha256(source_pdf)
    (base / "source" / "source_hash.txt").write_text(source_hash, encoding="utf-8")
    (base / "source" / "original_file_name.txt").write_text(file_name, encoding="utf-8")

    record = MemoRecord(
        memo_id=memo_id,
        source_file_name=file_name,
        source_hash=source_hash,
        memo_type=memo_type,
        facility_type=facility_type,
        borrower_name_or_hash=borrower_name_or_hash,
        reviewer=reviewer,
    )
    write_json(base / "memo_record.json", record.model_dump())
    write_json(base / "review" / "review_status.json", ReviewRecord(memo_id=memo_id, reviewer=reviewer).model_dump())
    append_audit(workspace, memo_id, "memo_created", {"source_file_name": file_name})
    return record


def list_memo_ids(workspace: Path) -> list[str]:
    memos = workspace / "memos"
    if not memos.exists():
        return []
    return sorted(path.name for path in memos.iterdir() if path.is_dir())


def load_memo_record(workspace: Path, memo_id: str) -> dict[str, Any]:
    return read_json(memo_dir(workspace, memo_id) / "memo_record.json", {})


def save_memo_record(workspace: Path, memo_id: str, data: dict[str, Any]) -> None:
    data["updated_at"] = utc_now()
    write_json(memo_dir(workspace, memo_id) / "memo_record.json", data)


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


def append_audit(workspace: Path, memo_id: str, event_type: str, payload: dict[str, Any]) -> None:
    append_jsonl(
        memo_dir(workspace, memo_id) / "audit" / "audit_log.jsonl",
        {"memo_id": memo_id, "event_type": event_type, "payload": payload, "created_at": utc_now()},
    )


def reset_demo_workspace(workspace: Path) -> None:
    if workspace.exists():
        shutil.rmtree(workspace)
    ensure_workspace(workspace)
