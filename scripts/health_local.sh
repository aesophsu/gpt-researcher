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

QDRANT_URL="${QDRANT_URL:-$(read_env_var QDRANT_URL || true)}"; QDRANT_URL="${QDRANT_URL:-http://127.0.0.1:6333}"
QDRANT_COLLECTION_PREFIX="${QDRANT_COLLECTION_PREFIX:-$(read_env_var QDRANT_COLLECTION_PREFIX || true)}"; QDRANT_COLLECTION_PREFIX="${QDRANT_COLLECTION_PREFIX:-medical_}"
ZOTERO_QDRANT_COLLECTION="${ZOTERO_QDRANT_COLLECTION:-$(read_env_var ZOTERO_QDRANT_COLLECTION || true)}"; ZOTERO_QDRANT_COLLECTION="${ZOTERO_QDRANT_COLLECTION:-zotero_med_bge_m3_20260301}"
ZOTERO_PDF_DIR="${ZOTERO_PDF_DIR:-$(read_env_var ZOTERO_PDF_DIR || true)}"; ZOTERO_PDF_DIR="${ZOTERO_PDF_DIR:-/Users/sue/Zotero/storage}"
OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-$(read_env_var OLLAMA_BASE_URL || true)}"; OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"

FAILURES=0

pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1"; FAILURES=$((FAILURES + 1)); }

command -v uv >/dev/null || fail "uv not found"
command -v curl >/dev/null || fail "curl not found"
command -v ollama >/dev/null || fail "ollama not found"

if curl -fsS -m 5 "$QDRANT_URL/" >/dev/null; then
  pass "Qdrant reachable at $QDRANT_URL"
else
  fail "Qdrant unreachable at $QDRANT_URL"
fi

if curl -fsS -m 5 "$QDRANT_URL/collections" >/dev/null; then
  pass "Qdrant collections endpoint OK"
else
  fail "Qdrant collections endpoint failed"
fi

if ollama list >/tmp/ollama-list.txt 2>/dev/null; then
  pass "Ollama service reachable"
  if rg -q '^bge-m3:|[[:space:]]bge-m3:latest' /tmp/ollama-list.txt; then
    pass "Ollama embedding model bge-m3 exists"
  else
    fail "Model bge-m3 missing (run: ollama pull bge-m3)"
  fi
else
  fail "Ollama service not reachable"
fi

if [[ -d "$ZOTERO_PDF_DIR" ]]; then
  PDF_COUNT="$(find "$ZOTERO_PDF_DIR" -type f -name '*.pdf' | wc -l | tr -d ' ')"
  if [[ "${PDF_COUNT:-0}" -gt 0 ]]; then
    pass "Zotero PDF dir exists with $PDF_COUNT PDFs"
  else
    fail "Zotero PDF dir exists but has zero PDFs: $ZOTERO_PDF_DIR"
  fi
else
  fail "Zotero PDF dir missing: $ZOTERO_PDF_DIR"
fi

TARGET_COLLECTION="${QDRANT_COLLECTION_PREFIX}${ZOTERO_QDRANT_COLLECTION}"
COUNT_JSON="$(curl -fsS -m 5 -X POST \
  "$QDRANT_URL/collections/$TARGET_COLLECTION/points/count" \
  -H 'Content-Type: application/json' \
  -d '{"exact":true}' 2>/dev/null || true)"

if [[ -n "$COUNT_JSON" ]]; then
  POINTS="$(COUNT_JSON="$COUNT_JSON" uv run python - <<'PY'
import json
import os
raw = os.environ.get("COUNT_JSON", "")
try:
    print(int((json.loads(raw) or {}).get("result", {}).get("count", 0)))
except Exception:
    print(0)
PY
)"
  if [[ "${POINTS:-0}" -gt 0 ]]; then
    pass "Target collection $TARGET_COLLECTION has $POINTS points"
  else
    fail "Target collection $TARGET_COLLECTION has zero points"
  fi
else
  fail "Unable to read count for collection $TARGET_COLLECTION"
fi

if TARGET_COLLECTION="$TARGET_COLLECTION" OLLAMA_BASE_URL="$OLLAMA_BASE_URL" QDRANT_URL="$QDRANT_URL" \
  uv run python - <<'PY' >/tmp/qdrant-smoke.txt 2>/dev/null
import os
from langchain_ollama import OllamaEmbeddings
from qdrant_client import QdrantClient

qdrant_url = os.environ.get("QDRANT_URL", "http://127.0.0.1:6333")
collection = os.environ.get("TARGET_COLLECTION")
ollama_base_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

emb = OllamaEmbeddings(model="bge-m3", base_url=ollama_base_url)
vec = emb.embed_query("health check acute pancreatitis")

client = QdrantClient(url=qdrant_url, check_compatibility=False)
res = client.query_points(collection_name=collection, query=vec, limit=1, with_payload=True)
points = res.points or []
print(f"HITS={len(points)}")
if points:
    print(f"TOP_SCORE={points[0].score}")
PY
then
  HITS="$(rg -n '^HITS=' /tmp/qdrant-smoke.txt | cut -d= -f2 | tail -n1 || echo 0)"
  if [[ "${HITS:-0}" -gt 0 ]]; then
    pass "Vector query smoke test passed (hits=$HITS)"
  else
    fail "Vector query smoke test returned zero hits"
  fi
else
  fail "Vector query smoke test failed"
fi

rm -f /tmp/ollama-list.txt /tmp/qdrant-smoke.txt

if [[ "$FAILURES" -gt 0 ]]; then
  echo "Health check finished with $FAILURES failure(s)."
  exit 1
fi

echo "Health check passed."
