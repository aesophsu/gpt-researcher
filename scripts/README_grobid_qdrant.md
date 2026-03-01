# GROBID + Qdrant + GPT Researcher

This script consumes a Qdrant collection already populated by the sibling stack:

- `/Users/sue/Code/grobid-qdrant-stack`

## Run

```bash
cd /Users/sue/Code/gpt-researcher
python scripts/grobid_qdrant_research_example.py \
  --query "Summarize key methods and results" \
  --collection papers_grobid
```

Section-focused retrieval:

```bash
python scripts/grobid_qdrant_research_example.py \
  --query "Compare experimental methods" \
  --collection papers_grobid \
  --section method
```

## Required env

- `OPENAI_API_KEY`
- Optional:
  - `QDRANT_URL` (default `http://localhost:6333`)
  - `QDRANT_COLLECTION` (default `papers_grobid`)
  - `EMBEDDING_MODEL` (default `text-embedding-3-small`)
