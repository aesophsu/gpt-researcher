"""Run GPT Researcher against a Qdrant collection populated by GROBID ingestion.

Example:
python scripts/grobid_qdrant_research_example.py \
  --query "Summarize the methods and limitations" \
  --collection papers_grobid \
  --section method
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GPT Researcher + Qdrant example")
    parser.add_argument("--query", required=True, help="Research question")
    parser.add_argument("--collection", default=os.getenv("QDRANT_COLLECTION", "papers_grobid"))
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://localhost:6333"))
    parser.add_argument("--qdrant-api-key", default=os.getenv("QDRANT_API_KEY", ""))
    parser.add_argument("--embedding-model", default=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"))
    parser.add_argument("--section", default="", help="Optional section filter, e.g. method/result/reference")
    parser.add_argument("--report-type", default="research_report")
    return parser.parse_args()


async def run() -> None:
    args = parse_args()
    from gpt_researcher import GPTResearcher
    from langchain_openai import OpenAIEmbeddings
    from langchain_qdrant import QdrantVectorStore
    from qdrant_client import QdrantClient

    embeddings = OpenAIEmbeddings(model=args.embedding_model)
    qdrant_client = QdrantClient(url=args.qdrant_url, api_key=args.qdrant_api_key or None)

    vector_store = QdrantVectorStore(
        client=qdrant_client,
        collection_name=args.collection,
        embedding=embeddings,
    )

    vector_store_filter = {"section": args.section} if args.section else None

    researcher = GPTResearcher(
        query=args.query,
        report_type=args.report_type,
        report_source="langchain_vectorstore",
        vector_store=vector_store,
        vector_store_filter=vector_store_filter,
    )

    await researcher.conduct_research()
    report = await researcher.write_report()
    print("\n=== REPORT ===\n")
    print(report)


if __name__ == "__main__":
    asyncio.run(run())
