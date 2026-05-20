from __future__ import annotations

import json
import os
import shutil
from uuid import uuid4


def main() -> None:
    if os.getenv("TAG_STUDIO_RUN_LIVE_S3_TEST") != "1":
        print(json.dumps({"status": "skipped", "reason": "Set TAG_STUDIO_RUN_LIVE_S3_TEST=1 to run against real S3."}))
        return

    if not os.getenv("TAG_STUDIO_S3_BUCKET"):
        raise SystemExit("TAG_STUDIO_S3_BUCKET is required for the live S3 smoke test.")
    if not os.getenv("AWS_REGION") and not os.getenv("AWS_DEFAULT_REGION"):
        raise SystemExit("AWS_REGION is required for the live S3 smoke test.")

    os.environ["TAG_STUDIO_STORAGE_BACKEND"] = "s3"
    os.environ.setdefault("TAG_STUDIO_LOCAL_WORKSPACE", "tag_studio_s3_live_workspace")
    os.environ.setdefault("TAG_STUDIO_S3_PREFIX", f"tag-studio/live-smoke/{uuid4().hex[:10]}")

    from tag_studio import storage

    workspace = storage.DEFAULT_WORKSPACE
    if workspace.exists():
        shutil.rmtree(workspace)

    ready, message = storage.storage_readiness()
    if not ready:
        raise AssertionError(message)

    storage.ensure_workspace(workspace)
    memo = storage.create_memo_workspace(
        workspace=workspace,
        pdf_bytes=b"%PDF-1.4\n% live smoke test bytes\n",
        file_name="live_smoke.pdf",
        memo_id=f"memo_live_{uuid4().hex[:8]}",
        memo_type="Renewal",
        facility_type="Revolver",
        borrower_name_or_hash="LIVE_SMOKE_TEST",
        reviewer="smoke-test",
    )
    storage.save_review(workspace, memo.memo_id, {"memo_id": memo.memo_id, "status": "Approved Gold", "reviewer": "smoke-test"})
    if memo.memo_id not in storage.list_memo_ids(workspace):
        raise AssertionError("Live S3 memo index did not include the created memo.")

    print(
        json.dumps(
            {
                "status": "ok",
                "bucket": os.getenv("TAG_STUDIO_S3_BUCKET"),
                "prefix": os.getenv("TAG_STUDIO_S3_PREFIX"),
                "memo_id": memo.memo_id,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
