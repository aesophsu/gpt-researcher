#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

read_env_var() {
  local key="$1"
  local file="${2:-.env}"
  [[ -f "$file" ]] || return 1
  local line
  line="$(grep -E "^${key}=" "$file" | tail -n1 || true)"
  [[ -n "$line" ]] || return 1
  line="${line#*=}"
  line="${line%$'\r'}"
  if [[ "$line" =~ ^\".*\"$ ]] || [[ "$line" =~ ^\'.*\'$ ]]; then
    line="${line:1:${#line}-2}"
  fi
  printf '%s' "$line"
}

unset ALL_PROXY all_proxy HTTP_PROXY http_proxy HTTPS_PROXY https_proxy

COLLECTION="${ZOTERO_QDRANT_COLLECTION:-$(read_env_var ZOTERO_QDRANT_COLLECTION || true)}"
COLLECTION="${COLLECTION:-zotero_med_bge_m3_20260301}"
BATCH_SIZE="${BATCH_SIZE:-64}"
RECREATE="true"

usage() {
  cat <<'EOF'
Usage: scripts/import_zotero_local.sh [options]

Options:
  --collection <name>    Override target collection name
  --batch-size <n>       Batch size for embedding/upsert (default: 64)
  --no-recreate          Keep existing collection; perform idempotent upsert
  --recreate             Recreate collection before import (default)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --collection)
      COLLECTION="${2:-}"
      shift 2
      ;;
    --batch-size)
      BATCH_SIZE="${2:-}"
      shift 2
      ;;
    --no-recreate)
      RECREATE="false"
      shift
      ;;
    --recreate)
      RECREATE="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$COLLECTION" ]]; then
  echo "ERROR: collection name is empty"
  exit 1
fi

if ! [[ "$BATCH_SIZE" =~ ^[0-9]+$ ]] || [[ "$BATCH_SIZE" -lt 1 ]]; then
  echo "ERROR: --batch-size must be a positive integer"
  exit 1
fi

EMBEDDING="${EMBEDDING:-$(read_env_var EMBEDDING || true)}"; EMBEDDING="${EMBEDDING:-ollama:bge-m3}"
OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-$(read_env_var OLLAMA_BASE_URL || true)}"; OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
MEDICAL_VECTOR_BACKEND="${MEDICAL_VECTOR_BACKEND:-$(read_env_var MEDICAL_VECTOR_BACKEND || true)}"; MEDICAL_VECTOR_BACKEND="${MEDICAL_VECTOR_BACKEND:-qdrant}"
QDRANT_URL="${QDRANT_URL:-$(read_env_var QDRANT_URL || true)}"; QDRANT_URL="${QDRANT_URL:-http://127.0.0.1:6333}"
QDRANT_COLLECTION_PREFIX="${QDRANT_COLLECTION_PREFIX:-$(read_env_var QDRANT_COLLECTION_PREFIX || true)}"; QDRANT_COLLECTION_PREFIX="${QDRANT_COLLECTION_PREFIX:-medical_}"
QDRANT_TIMEOUT_SECONDS="${QDRANT_TIMEOUT_SECONDS:-$(read_env_var QDRANT_TIMEOUT_SECONDS || true)}"; QDRANT_TIMEOUT_SECONDS="${QDRANT_TIMEOUT_SECONDS:-600}"
QDRANT_FORCE_DISABLED="${QDRANT_FORCE_DISABLED:-$(read_env_var QDRANT_FORCE_DISABLED || true)}"; QDRANT_FORCE_DISABLED="${QDRANT_FORCE_DISABLED:-false}"
MEDICAL_INDEX_PATH="${MEDICAL_INDEX_PATH:-$(read_env_var MEDICAL_INDEX_PATH || true)}"; MEDICAL_INDEX_PATH="${MEDICAL_INDEX_PATH:-./data/medical_index.json}"
ZOTERO_PDF_DIR="${ZOTERO_PDF_DIR:-$(read_env_var ZOTERO_PDF_DIR || true)}"; ZOTERO_PDF_DIR="${ZOTERO_PDF_DIR:-/Users/sue/Zotero/storage}"
ZOTERO_JSON_PATH="${ZOTERO_JSON_PATH:-$(read_env_var ZOTERO_JSON_PATH || true)}"; ZOTERO_JSON_PATH="${ZOTERO_JSON_PATH:-/Users/sue/Zotero/My Library.json}"
ZOTERO_BIB_PATH="${ZOTERO_BIB_PATH:-$(read_env_var ZOTERO_BIB_PATH || true)}"; ZOTERO_BIB_PATH="${ZOTERO_BIB_PATH:-/Users/sue/Zotero/My Library.bib}"

echo "== Local Zotero Import =="
echo "COLLECTION=$COLLECTION"
echo "BATCH_SIZE=$BATCH_SIZE"
echo "RECREATE=$RECREATE"
echo "EMBEDDING=$EMBEDDING"
echo "QDRANT_URL=$QDRANT_URL"

command -v uv >/dev/null || { echo "ERROR: uv not found"; exit 1; }
command -v curl >/dev/null || { echo "ERROR: curl not found"; exit 1; }
command -v ollama >/dev/null || { echo "ERROR: ollama not found"; exit 1; }

curl -fsS -m 5 "$QDRANT_URL/" >/dev/null || {
  echo "ERROR: Qdrant unreachable at $QDRANT_URL"
  exit 1
}

ollama list | rg -q '^bge-m3:|[[:space:]]bge-m3:latest' || {
  echo "ERROR: bge-m3 model is not installed. Run: ollama pull bge-m3"
  exit 1
}

[[ -d "$ZOTERO_PDF_DIR" ]] || { echo "ERROR: ZOTERO_PDF_DIR not found: $ZOTERO_PDF_DIR"; exit 1; }
[[ -f "$ZOTERO_JSON_PATH" ]] || { echo "ERROR: ZOTERO_JSON_PATH not found: $ZOTERO_JSON_PATH"; exit 1; }
[[ -f "$ZOTERO_BIB_PATH" ]] || { echo "ERROR: ZOTERO_BIB_PATH not found: $ZOTERO_BIB_PATH"; exit 1; }

PDF_COUNT="$(find "$ZOTERO_PDF_DIR" -type f -name '*.pdf' | wc -l | tr -d ' ')"
if [[ "${PDF_COUNT:-0}" -lt 1 ]]; then
  echo "ERROR: no PDF found under $ZOTERO_PDF_DIR"
  exit 1
fi
echo "ZOTERO_PDF_COUNT=$PDF_COUNT"

if [[ ! -f "$MEDICAL_INDEX_PATH" ]]; then
  mkdir -p "$(dirname "$MEDICAL_INDEX_PATH")"
  printf '{"collections":{}}\n' > "$MEDICAL_INDEX_PATH"
fi

echo "== Step 1/2: Ensure cache chunks exist in $MEDICAL_INDEX_PATH =="
env \
  COLLECTION="$COLLECTION" \
  MEDICAL_VECTOR_BACKEND="$MEDICAL_VECTOR_BACKEND" \
  QDRANT_FORCE_DISABLED="$QDRANT_FORCE_DISABLED" \
  QDRANT_URL="$QDRANT_URL" \
  QDRANT_COLLECTION_PREFIX="$QDRANT_COLLECTION_PREFIX" \
  QDRANT_TIMEOUT_SECONDS="$QDRANT_TIMEOUT_SECONDS" \
  EMBEDDING="$EMBEDDING" \
  OLLAMA_BASE_URL="$OLLAMA_BASE_URL" \
  MEDICAL_INDEX_PATH="$MEDICAL_INDEX_PATH" \
  ZOTERO_PDF_DIR="$ZOTERO_PDF_DIR" \
  ZOTERO_JSON_PATH="$ZOTERO_JSON_PATH" \
  ZOTERO_BIB_PATH="$ZOTERO_BIB_PATH" \
  uv run python - <<'PY'
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient
from backend.server.app import app

collection = os.environ["COLLECTION"]
index_path = Path(os.environ["MEDICAL_INDEX_PATH"])
state = {"collections": {}}
if index_path.exists():
    try:
        state = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        pass

if collection not in state.get("collections", {}):
    client = TestClient(app)
    resp = client.post(
        "/api/v1/medical/zotero-ingest",
        json={
            "collection_name": collection,
            "pdf_dir": os.environ["ZOTERO_PDF_DIR"],
            "zotero_json_path": os.environ["ZOTERO_JSON_PATH"],
            "bibtex_path": os.environ["ZOTERO_BIB_PATH"],
            "recursive": True,
        },
    )
    data = resp.json()
    print(f"CACHE_STATUS={resp.status_code}")
    print(f"CACHE_INDEXED_DOCS={data.get('indexed_docs', 0)}")
    print(f"CACHE_CHUNKS={data.get('chunks', 0)}")
    print(f"CACHE_BACKEND={data.get('index_backend')}")
else:
    docs = len(state["collections"][collection].get("docs", []))
    chunks = len(state["collections"][collection].get("chunks", []))
    print("CACHE_HIT=true")
    print(f"CACHE_INDEXED_DOCS={docs}")
    print(f"CACHE_CHUNKS={chunks}")
PY

echo "== Step 2/2: Batch embed and upsert to Qdrant =="
env \
  COLLECTION="$COLLECTION" \
  BATCH_SIZE="$BATCH_SIZE" \
  RECREATE="$RECREATE" \
  QDRANT_URL="$QDRANT_URL" \
  QDRANT_COLLECTION_PREFIX="$QDRANT_COLLECTION_PREFIX" \
  MEDICAL_INDEX_PATH="$MEDICAL_INDEX_PATH" \
  OLLAMA_BASE_URL="$OLLAMA_BASE_URL" \
  uv run python - <<'PY'
import json
import os
import time
from hashlib import sha1
from pathlib import Path

from langchain_ollama import OllamaEmbeddings
from qdrant_client import QdrantClient
from qdrant_client.http import models

collection = os.environ["COLLECTION"]
batch_size = int(os.environ["BATCH_SIZE"])
recreate = os.environ["RECREATE"].lower() == "true"
qdrant_url = os.environ["QDRANT_URL"]
prefix = os.environ["QDRANT_COLLECTION_PREFIX"]
index_path = Path(os.environ["MEDICAL_INDEX_PATH"])
ollama_base = os.environ["OLLAMA_BASE_URL"]

state = json.loads(index_path.read_text(encoding="utf-8"))
if collection not in state.get("collections", {}):
    raise SystemExit(f"Collection cache not found in {index_path}: {collection}")

docs = state["collections"][collection].get("docs", [])
chunks = state["collections"][collection].get("chunks", [])
if not chunks:
    raise SystemExit("No chunks available in cache. Abort.")

qdrant_collection = f"{prefix}{collection}"
emb = OllamaEmbeddings(model="bge-m3", base_url=ollama_base)
qc = QdrantClient(url=qdrant_url, check_compatibility=False, timeout=600)

if recreate and qc.collection_exists(qdrant_collection):
    qc.delete_collection(qdrant_collection)

vector_size = None
written = 0
start = time.time()

for i in range(0, len(chunks), batch_size):
    batch = chunks[i:i + batch_size]
    vectors = emb.embed_documents([c.get("text", "") for c in batch])

    if vector_size is None:
        vector_size = len(vectors[0])
        if not qc.collection_exists(qdrant_collection):
            qc.create_collection(
                collection_name=qdrant_collection,
                vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
            )

    points = []
    for c, v in zip(batch, vectors):
        chunk_id = str(c.get("chunk_id"))
        stable_id = int(sha1(f"{qdrant_collection}:{chunk_id}".encode("utf-8")).hexdigest()[:16], 16)
        points.append(
            models.PointStruct(
                id=stable_id,
                vector=v,
                payload={
                    "chunk_id": chunk_id,
                    "collection_name": c.get("collection_name", collection),
                    "source": c.get("source", ""),
                    "page": c.get("page"),
                    "title": c.get("title"),
                    "doi": c.get("doi"),
                    "year": c.get("year"),
                    "journal": c.get("journal"),
                    "external_metadata_matched": c.get("external_metadata_matched", False),
                    "text": c.get("text", ""),
                },
            )
        )

    qc.upsert(collection_name=qdrant_collection, points=points, wait=True)
    written += len(points)
    if written % max(batch_size * 5, 320) == 0 or written == len(chunks):
        print(f"PROGRESS={written}/{len(chunks)}")

qcount = qc.count(collection_name=qdrant_collection, exact=True).count
elapsed = round(time.time() - start, 2)
print(f"INDEXED_DOCS={len(docs)}")
print(f"CHUNKS_TOTAL={len(chunks)}")
print(f"UPSERTED_POINTS={written}")
print(f"QDRANT_COLLECTION={qdrant_collection}")
print(f"QDRANT_POINTS={qcount}")
print(f"ELAPSED_SEC={elapsed}")
if qcount < 1:
    raise SystemExit("QDRANT_POINTS is zero after import.")
PY

echo "Import completed successfully."
