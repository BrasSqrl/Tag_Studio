from __future__ import annotations

import io
import json
import os
import shutil
from pathlib import Path
from typing import Any

os.environ["TAG_STUDIO_STORAGE_BACKEND"] = "s3"
os.environ["TAG_STUDIO_LOCAL_WORKSPACE"] = "tag_studio_s3_mock_workspace"
os.environ["TAG_STUDIO_S3_BUCKET"] = "tag-studio-test-bucket"
os.environ["TAG_STUDIO_S3_PREFIX"] = "tag-studio/mock"
os.environ["AWS_REGION"] = "us-east-1"

from tag_studio import storage  # noqa: E402


class FakeS3Paginator:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects

    def paginate(self, Bucket: str, Prefix: str) -> list[dict[str, Any]]:  # noqa: N803 - boto3-compatible name.
        return [{"Contents": [{"Key": key} for key in sorted(self.objects) if key.startswith(Prefix)]}]


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def head_bucket(self, Bucket: str) -> None:  # noqa: N803 - boto3-compatible name.
        if Bucket != "tag-studio-test-bucket":
            raise KeyError(Bucket)

    def put_object(self, Bucket: str, Key: str, Body: bytes, **_kwargs: Any) -> None:  # noqa: N803
        self.objects[Key] = Body if isinstance(Body, bytes) else str(Body).encode("utf-8")

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": io.BytesIO(self.objects[Key])}

    def head_object(self, Bucket: str, Key: str) -> None:  # noqa: N803
        if Key not in self.objects:
            raise KeyError(Key)

    def upload_file(self, Filename: str, Bucket: str, Key: str, ExtraArgs: dict[str, str] | None = None) -> None:  # noqa: N803
        self.objects[Key] = Path(Filename).read_bytes()

    def download_file(self, Bucket: str, Key: str, Filename: str) -> None:  # noqa: N803
        if Key not in self.objects:
            raise KeyError(Key)
        path = Path(Filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.objects[Key])

    def get_paginator(self, name: str) -> FakeS3Paginator:
        if name != "list_objects_v2":
            raise ValueError(name)
        return FakeS3Paginator(self.objects)


def main() -> None:
    fake = FakeS3Client()
    storage._s3_client = lambda: fake  # type: ignore[method-assign]
    storage.storage_readiness.cache_clear()

    workspace = storage.DEFAULT_WORKSPACE
    if workspace.exists():
        shutil.rmtree(workspace)

    ready, message = storage.storage_readiness()
    if not ready:
        raise AssertionError(message)

    storage.ensure_workspace(workspace)
    memo = storage.create_memo_workspace(
        workspace=workspace,
        pdf_bytes=b"%PDF-1.4\n% synthetic test bytes\n",
        file_name="sample.pdf",
        memo_id="memo_s3_mock_001",
        memo_type="Renewal",
        facility_type="Revolver",
        customer_id="1001",
        reviewer="tester",
    )
    storage.save_tags(
        workspace,
        memo.memo_id,
        [{"tag_record_id": "tag_001", "memo_id": memo.memo_id, "section_id": "section_001", "tag_id": "test", "tag_label": "Test", "value": "ok"}],
    )
    storage.save_evidence(
        workspace,
        memo.memo_id,
        [{"evidence_id": "ev_001", "memo_id": memo.memo_id, "section_id": "section_001", "selected_text": "sample", "source_document_hash": memo.source_hash}],
    )
    storage.save_review(workspace, memo.memo_id, {"memo_id": memo.memo_id, "status": "Approved Gold", "reviewer": "tester"})

    required_keys = [
        "tag-studio/mock/config/section_schema.json",
        "tag-studio/mock/config/tag_schema.json",
        "tag-studio/mock/memos/index.json",
        "tag-studio/mock/memos/memo_s3_mock_001/source/source.pdf",
        "tag-studio/mock/memos/memo_s3_mock_001/memo_record.json",
        "tag-studio/mock/memos/memo_s3_mock_001/tags/tag_records.json",
        "tag-studio/mock/memos/memo_s3_mock_001/evidence/evidence_records.json",
        "tag-studio/mock/memos/memo_s3_mock_001/review/review_status.json",
    ]
    missing = [key for key in required_keys if key not in fake.objects]
    if missing:
        raise AssertionError(f"Missing S3 objects: {missing}")
    if not any(key.startswith("tag-studio/mock/memos/memo_s3_mock_001/audit/events/") for key in fake.objects):
        raise AssertionError("Missing S3 audit event objects.")

    shutil.rmtree(workspace)
    storage.ensure_workspace(workspace)
    memo_ids = storage.list_memo_ids(workspace)
    if memo.memo_id not in memo_ids:
        raise AssertionError("S3 memo index did not hydrate.")

    storage.hydrate_memo_from_remote(workspace, memo.memo_id, force=True)
    if not (storage.memo_dir(workspace, memo.memo_id) / "source" / "source.pdf").exists():
        raise AssertionError("Memo source PDF did not hydrate from S3.")
    if not storage.load_tags(workspace, memo.memo_id):
        raise AssertionError("Tag records did not hydrate from S3.")

    print(
        json.dumps(
            {
                "status": "ok",
                "backend": storage.storage_backend_name(),
                "object_count": len(fake.objects),
                "memo_ids": memo_ids,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
