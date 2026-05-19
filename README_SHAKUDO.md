# Tag Studio on Shakudo

This guide is for Shakudo administrators deploying Tag Studio as a shared Streamlit app.

## Deployment Model

- Runtime: Shakudo Microservice.
- App port: `8787`.
- Storage mode: S3 primary.
- Local disk: pod-level working cache only.
- Replica count: keep min replicas and max replicas at `1` for this version.

Tag Studio follows Shakudo's Streamlit microservice pattern:

- Streamlit app reference: https://docs.shakudo.io/tutorials/streamlitapp/
- Microservice reference: https://docs.shakudo.io/shakudo-platform-core/service/

## Required Environment

Set these in Shakudo environment or secret configuration:

```bash
TAG_STUDIO_STORAGE_BACKEND=s3
TAG_STUDIO_S3_BUCKET=your-s3-bucket
TAG_STUDIO_S3_PREFIX=tag-studio/prod
TAG_STUDIO_LOCAL_WORKSPACE=/tmp/tag_studio_workspace
AWS_REGION=us-east-1
```

Optional encryption settings:

```bash
TAG_STUDIO_S3_SSE=aws:kms
TAG_STUDIO_S3_KMS_KEY_ID=your-kms-key-id
```

## Required AWS Permissions

The Shakudo runtime role must be able to read and write within the configured bucket and prefix:

- `s3:ListBucket`
- `s3:GetObject`
- `s3:PutObject`
- `s3:DeleteObject` is optional for future cleanup features.
- `kms:Encrypt`, `kms:Decrypt`, and `kms:GenerateDataKey` are required if `TAG_STUDIO_S3_SSE=aws:kms`.

## OCR Runtime Requirements

For digital PDFs, Python dependencies are enough. For scanned PDFs, the Shakudo environment also needs these system binaries:

- Tesseract
- Ghostscript
- qpdf

If the base Shakudo environment does not include these, create an environment config or custom image before production use.

Technical note: this requirement is for Tag Studio's current local OCR path. Amazon Textract is AWS's managed document-analysis service, but Tag Studio does not call Textract in the current Shakudo deployment plan.

## How Storage Works

S3 object keys mirror the local workspace layout:

```text
config/tag_schema.json
config/section_schema.json
memos/index.json
memos/{memo_id}/source/source.pdf
memos/{memo_id}/extraction/page_text.json
memos/{memo_id}/pages/page_001.png
memos/{memo_id}/sections/sections.json
memos/{memo_id}/tags/tag_records.json
memos/{memo_id}/evidence/evidence_records.json
memos/{memo_id}/review/review_status.json
memos/{memo_id}/audit/audit_log.jsonl
exports/
```

The app writes locally first, then syncs changed artifacts to S3. On restart, it rebuilds the shared memo queue and hydrates memo files from S3.

## Deployment Steps

1. Create or select the S3 bucket.
2. Grant the Shakudo runtime role the required S3 permissions.
3. Configure the environment variables above.
4. Register `shakudo/service.yaml` as the Shakudo Microservice definition.
5. Confirm the service is configured as a single replica.
6. Start the service and open the Shakudo app URL.
7. Check Admin Tools > Technical Diagnostics to confirm storage backend `s3` and a successful last sync.

## Validation

Before deployment:

```bash
python -m compileall tag_studio verify_tag_studio.py verify_s3_storage.py
python verify_tag_studio.py
python verify_s3_storage.py
```

Optional real-bucket smoke test:

```bash
TAG_STUDIO_RUN_LIVE_S3_TEST=1 python verify_s3_live_storage.py
```

Only run the live smoke test against a non-production prefix.

After deployment:

1. Upload a synthetic memo PDF.
2. Confirm it appears in the shared memo queue.
3. Complete one section review and save tags.
4. Confirm S3 objects appear under the configured prefix.
5. Restart the Shakudo service and confirm the memo queue reappears.
6. Download the Review Workbook, Training File, and Audit Package.
