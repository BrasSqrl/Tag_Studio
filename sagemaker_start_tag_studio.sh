#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

APP_PORT="${TAG_STUDIO_PORT:-8501}"
APP_ADDRESS="${TAG_STUDIO_ADDRESS:-0.0.0.0}"
VENV_DIR="${TAG_STUDIO_VENV_DIR:-.venv}"

echo "Tag Studio SageMaker startup"
echo "Repository: ${SCRIPT_DIR}"

if [[ ! -f "tag_studio_launcher.py" ]]; then
  echo "ERROR: tag_studio_launcher.py was not found."
  echo "Run this script from the Tag_Studio repo folder, or call it by path from that folder."
  exit 1
fi

if [[ -n "${PYTHON_BIN:-}" ]]; then
  PYTHON_CMD="${PYTHON_BIN}"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_CMD="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_CMD="python"
else
  echo "ERROR: Python was not found. Start a SageMaker image that includes Python 3.11 or newer."
  exit 1
fi

"${PYTHON_CMD}" - <<'PY'
import sys

if sys.version_info < (3, 11):
    raise SystemExit(
        f"ERROR: Python 3.11 or newer is required. Found {sys.version.split()[0]}."
    )
print(f"Using Python {sys.version.split()[0]}")
PY

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "Creating virtual environment: ${VENV_DIR}"
  "${PYTHON_CMD}" -m venv "${VENV_DIR}"
else
  echo "Using existing virtual environment: ${VENV_DIR}"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

echo "Upgrading pip tooling"
python -m pip install --upgrade pip setuptools wheel

echo "Installing Tag Studio requirements"
python -m pip install -r requirements.txt

if [[ "${TAG_STUDIO_INSTALL_OCR_TOOLS:-0}" == "1" ]]; then
  if command -v conda >/dev/null 2>&1; then
    echo "Installing optional scanned-PDF OCR tools with conda"
    conda install -y -c conda-forge tesseract ghostscript qpdf
  else
    echo "WARNING: TAG_STUDIO_INSTALL_OCR_TOOLS=1 was set, but conda was not found."
    echo "Ask your SageMaker administrator to add Tesseract, Ghostscript, and qpdf to the image."
  fi
fi

echo "Checking optional OCR tools"
command -v tesseract >/dev/null 2>&1 || echo "WARNING: Tesseract not found. Digital PDFs can still be used, but scanned PDFs may need OCR support."
command -v gs >/dev/null 2>&1 || echo "WARNING: Ghostscript not found. Some OCR workflows may be unavailable."
command -v qpdf >/dev/null 2>&1 || echo "WARNING: qpdf not found. Some OCR workflows may be unavailable."

export TAG_STUDIO_STORAGE_BACKEND="${TAG_STUDIO_STORAGE_BACKEND:-local}"

if [[ "${TAG_STUDIO_STORAGE_BACKEND}" == "local" ]]; then
  export TAG_STUDIO_LOCAL_WORKSPACE="${TAG_STUDIO_LOCAL_WORKSPACE:-${SCRIPT_DIR}/tag_studio_workspace}"
  echo "Storage mode: local"
  echo "Workspace: ${TAG_STUDIO_LOCAL_WORKSPACE}"
elif [[ "${TAG_STUDIO_STORAGE_BACKEND}" == "s3" ]]; then
  : "${TAG_STUDIO_S3_BUCKET:?ERROR: TAG_STUDIO_S3_BUCKET is required when TAG_STUDIO_STORAGE_BACKEND=s3.}"
  export TAG_STUDIO_S3_PREFIX="${TAG_STUDIO_S3_PREFIX:-tag-studio/sagemaker}"
  export AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
  echo "Storage mode: s3"
  echo "Bucket: ${TAG_STUDIO_S3_BUCKET}"
  echo "Prefix: ${TAG_STUDIO_S3_PREFIX}"
  echo "Region: ${AWS_REGION}"
else
  echo "ERROR: TAG_STUDIO_STORAGE_BACKEND must be local or s3."
  exit 1
fi

if [[ "${TAG_STUDIO_SETUP_ONLY:-0}" == "1" ]]; then
  echo "Setup complete. TAG_STUDIO_SETUP_ONLY=1 was set, so Streamlit was not started."
  exit 0
fi

echo ""
echo "Starting Tag Studio on port ${APP_PORT}"
echo "In SageMaker Studio, open the matching proxy URL, usually one of:"
echo "  /proxy/${APP_PORT}/"
echo "  /jupyter/default/proxy/${APP_PORT}/"
echo ""
echo "Keep this terminal running. Press Ctrl+C here to stop Tag Studio."

exec python -m streamlit run tag_studio_launcher.py \
  --server.port "${APP_PORT}" \
  --server.address "${APP_ADDRESS}" \
  --server.headless true \
  --server.enableCORS false \
  --server.enableXsrfProtection false
