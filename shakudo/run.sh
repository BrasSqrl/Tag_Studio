#!/bin/bash
set -e

PROJECT_DIR="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

export TAG_STUDIO_STORAGE_BACKEND="${TAG_STUDIO_STORAGE_BACKEND:-s3}"
export TAG_STUDIO_LOCAL_WORKSPACE="${TAG_STUDIO_LOCAL_WORKSPACE:-/tmp/tag_studio_workspace}"
export TAG_STUDIO_S3_PREFIX="${TAG_STUDIO_S3_PREFIX:-tag-studio/prod}"

python -m streamlit run tag_studio_launcher.py \
  --server.port 8787 \
  --server.address 0.0.0.0 \
  --server.headless true
