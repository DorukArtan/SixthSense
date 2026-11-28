#!/usr/bin/env bash
# One-time setup: Python deps, UCI data, SQLite snapshot, local model.
# Usage: ./scripts/setup.sh && streamlit run app.py
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m pip install -r requirements.txt

RAW_DIR="data/raw"
XLSX="$RAW_DIR/Online Retail.xlsx"
# Verify this URL on https://archive.ics.uci.edu/dataset/352/online+retail before the demo.
UCI_ZIP_URL="${UCI_ZIP_URL:-https://archive.ics.uci.edu/static/public/352/online%2Bretail.zip}"

mkdir -p "$RAW_DIR"
if [ ! -f "$XLSX" ]; then
  echo "Downloading UCI Online Retail ..."
  curl -fL "$UCI_ZIP_URL" -o "$RAW_DIR/online_retail.zip" \
    || { echo "Download failed. Get 'Online Retail.xlsx' from the UCI page and put it in $RAW_DIR/"; exit 1; }
  unzip -o "$RAW_DIR/online_retail.zip" -d "$RAW_DIR"
fi

python3 scripts/import_uci.py "$XLSX"

if [ -f .env ]; then set -a; . ./.env; set +a; fi
MODEL="${OLLAMA_MODEL:-qwen2.5-coder:7b-instruct-q4_K_M}"
if command -v ollama >/dev/null 2>&1; then
  ollama pull "$MODEL"
else
  echo "Ollama not found. Install it from https://ollama.com, then run: ollama pull $MODEL"
fi
