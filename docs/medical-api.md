# Medical Extension API (Phase 1 + Phase 2 partial)

This project now exposes backend-first medical research endpoints under `/api/v1/medical`.

## Endpoints

### `POST /api/v1/medical/ingest`
Index local documents (including Zotero-exported PDF folders) into Qdrant first, with automatic JSON fallback.

Request:
```json
{
  "doc_path": "/absolute/or/relative/path",
  "collection_name": "default",
  "recursive": true
}
```

Response fields:
- `indexed_docs`: number of documents indexed
- `chunks`: number of text chunks stored
- `skipped_files`: number of duplicate files skipped in the same collection
- `failed_files`: list of failed files with reason
- `index_backend`: `qdrant` / `json_fallback` / `dual_write_partial`
- `index_warnings[]`: backend warnings (for example, Qdrant temporary errors)

### `POST /api/v1/medical/zotero-ingest`
Linked ingest for Zotero export metadata and local full-text files.

Request:
```json
{
  "collection_name": "zotero-med",
  "pdf_dir": "/path/to/zotero/storage-or-export-dir",
  "zotero_json_path": "/path/to/zotero_export.json",
  "bibtex_path": "/path/to/library.bib",
  "recursive": true
}
```

Response fields:
- all fields from `/ingest`
- `collection_name`
- `match_stats`: `pdf_files/matched_metadata/unmatched_pdf_files/json_entries/bib_entries`

### `POST /api/v1/medical/ingest/async`
Submit local ingest as a background task.

Response:
```json
{
  "job_id": "uuid",
  "status": "pending"
}
```

### `POST /api/v1/medical/zotero-ingest/async`
Submit Zotero linked ingest as a background task.

### `GET /api/v1/medical/jobs/{job_id}`
Query task progress and final result.

Response fields:
- `status`: `pending/running/completed/failed`
- `progress`: `stage/message/total_files/processed_files/skipped_files/indexed_docs/chunks/failed_files`
- `result`: completed response payload from ingest API
- `error`: failure reason when status is `failed`

### `POST /api/v1/medical/search`
Run medical-oriented search over local index, web sources, or hybrid mode.

Request:
```json
{
  "query": "hypertension treatment in adults",
  "top_k": 8,
  "sources": "hybrid",
  "collection_name": "default"
}
```

Response fields:
- `expanded_query`: query after basic MeSH-style expansion
- `results[]`: local/web results with snippet, score, source, page, DOI, year, journal, URL

Local reranking (when `sources=local|hybrid`) now adds metadata-aware boosts:
- DOI exact match with query
- year match / recent-year freshness
- journal token overlap with query
- metadata confidence boost (matched from Zotero JSON/BibTeX)

### `POST /api/v1/medical/polish`
Polish manuscript text with optional evidence mapping and strict fact guardrails.

Request:
```json
{
  "text": "Original paragraph...",
  "mode": "academic",
  "journal_style": "NEJM",
  "require_evidence": true,
  "strict_fact_mode": true,
  "collection_name": "default"
}
```

Response fields:
- `revisions[]`: `original/revised/reason` triples by sentence
- `evidence_map[]`: sentence-to-source mapping with confidence/page/snippet
- `risk_flags[]`: e.g. `llm_not_configured`, `missing_evidence:s1,s3`

Evidence selection strategy in `/polish` uses a combined score:
- sentence-snippet semantic overlap
- retrieval/rerank score from `medical/search`
- evidence quality boosts (DOI, journal presence, recency, trusted source)

### `POST /api/v1/medical/citation-audit`
Audit manuscript citation coverage and style consistency.

Request:
```json
{
  "manuscript_text": "...",
  "format": "auto",
  "references": ["optional reference lines..."]
}
```

Response fields:
- `missing_citations[]`
- `weak_claims[]`
- `unmatched_citations[]`: citations appearing in text but not found in provided references
- `unused_references[]`: references provided but never cited in manuscript
- `format_issues[]`
- `consistency_score`: citation consistency score in `[0,1]`

## Environment

- `MEDICAL_INDEX_PATH`: optional path for local medical index file (default: `data/medical_index.json`)
- `MEDICAL_JOB_PATH`: optional path for ingest job status store (default: `data/medical_jobs.json`)
- `MEDICAL_VECTOR_BACKEND`: vector backend selector (default: `qdrant`)
- `QDRANT_URL`: Qdrant endpoint (default: `http://127.0.0.1:6333`)
- `QDRANT_API_KEY`: optional API key (default empty)
- `QDRANT_COLLECTION_PREFIX`: collection name prefix (default: `medical_`)
- `QDRANT_PREFER_GRPC`: use gRPC transport (`true/false`, default: `false`)
- `QDRANT_TIMEOUT_SECONDS`: client timeout (default: `10`)
- `QDRANT_FORCE_DISABLED`: force disable Qdrant and use JSON fallback only (`true/false`, default: `false`)
- LLM keys for polish rewrite (optional but recommended):
  - `OPENAI_API_KEY`
  - `ANTHROPIC_API_KEY`
  - `GOOGLE_API_KEY`
  - `AZURE_OPENAI_API_KEY`
  - `OPENROUTER_API_KEY`

If no LLM key is configured, `/polish` returns structured output with `llm_not_configured` risk flag and preserves original text.

## Notes

- Local search path is Qdrant-first and automatically falls back to JSON index on connectivity/runtime errors.
- Ingest now avoids duplicate imports by source path per `collection_name` and returns `skipped_files`.
- Zotero ingest is local-file based and does not require Zotero online API.
- Citation consistency checks are currently rule-based for deterministic behavior and speed.

## Local Qdrant Quick Start

1. Start Qdrant:
```bash
docker run -d --name qdrant -p 6333:6333 -v qdrant_storage:/qdrant/storage qdrant/qdrant
```

2. Verify health:
```bash
curl http://127.0.0.1:6333/healthz
```

3. Start backend as usual:
```bash
make backend-dev
```
