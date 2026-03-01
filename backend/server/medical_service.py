from __future__ import annotations

import asyncio
import inspect
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha1
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Sequence
from uuid import uuid4

from gpt_researcher.core.documents import (
    DefaultMetadataExtractor,
    RawDocument,
    list_files as core_list_files,
    loader_for_file as core_loader_for_file,
)
from gpt_researcher.core.rag import DefaultRetrievalPipeline
from gpt_researcher.core.storage.adapters import (
    JsonIndexStoreAdapter,
    QdrantVectorStoreAdapter,
)
from gpt_researcher.config.config import Config
from gpt_researcher.retrievers.pubmed_central.pubmed_central import PubMedCentralSearch
from gpt_researcher.retrievers.semantic_scholar.semantic_scholar import SemanticScholarSearch
from gpt_researcher.utils.llm import create_chat_completion

from .medical_models import (
    CitationAuditRequest,
    CitationAuditResponse,
    CitationIssue,
    EvidenceRef,
    FailedFile,
    MedicalJobCreateResponse,
    MedicalJobProgress,
    MedicalJobStatusResponse,
    MedicalIngestRequest,
    MedicalIngestResponse,
    MedicalPolishRequest,
    MedicalPolishResponse,
    MedicalSearchRequest,
    MedicalSearchResponse,
    MedicalSearchResult,
    RevisionItem,
    ZoteroIngestRequest,
    ZoteroIngestResponse,
    ZoteroMatchStats,
)
from .medical_job_store import MedicalJobStore
from .medical_vector_store import MedicalVectorStore

_MESH_EXPANSION = {
    "heart attack": ["myocardial infarction", "acute coronary syndrome"],
    "stroke": ["cerebrovascular accident", "ischemic stroke"],
    "high blood pressure": ["hypertension"],
    "diabetes": ["diabetes mellitus", "hyperglycemia"],
    "kidney disease": ["renal disease", "chronic kidney disease"],
    "lung cancer": ["pulmonary neoplasm", "nsclc"],
}

_CLAIM_MARKERS = (
    "significantly",
    "improves",
    "reduces",
    "increases",
    "effective",
    "associated",
    "causes",
    "prevents",
    "risk",
    "mortality",
)

logger = logging.getLogger(__name__)
_VECTOR_STORE: MedicalVectorStore | None = None
_JOB_STORE: MedicalJobStore | None = None
_RETRIEVAL_PIPELINE: DefaultRetrievalPipeline | None = None
_RUNNING_JOBS: dict[str, asyncio.Task[Any]] = {}
ProgressCallback = Callable[..., Awaitable[None] | None]
_METADATA_EXTRACTOR = DefaultMetadataExtractor()


@dataclass
class IndexedChunk:
    chunk_id: str
    collection_name: str
    source: str
    page: int | None
    text: str
    title: str | None
    doi: str | None
    year: int | None
    journal: str | None
    external_metadata_matched: bool

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "collection_name": self.collection_name,
            "source": self.source,
            "page": self.page,
            "text": self.text,
            "title": self.title,
            "doi": self.doi,
            "year": self.year,
            "journal": self.journal,
            "external_metadata_matched": self.external_metadata_matched,
        }


class MedicalIndexStore(JsonIndexStoreAdapter):
    def __init__(self, path: Path):
        super().__init__(path)


def _get_store() -> MedicalIndexStore:
    index_path = Path(os.getenv("MEDICAL_INDEX_PATH", os.path.join("data", "medical_index.json")))
    return MedicalIndexStore(index_path)


def _get_job_store() -> MedicalJobStore:
    global _JOB_STORE
    if _JOB_STORE is None:
        jobs_path = Path(os.getenv("MEDICAL_JOB_PATH", os.path.join("data", "medical_jobs.json")))
        _JOB_STORE = MedicalJobStore(jobs_path)
    return _JOB_STORE


def _get_vector_store() -> MedicalVectorStore:
    global _VECTOR_STORE
    if _VECTOR_STORE is None:
        _VECTOR_STORE = QdrantVectorStoreAdapter()
    return _VECTOR_STORE


def _get_retrieval_pipeline() -> DefaultRetrievalPipeline:
    global _RETRIEVAL_PIPELINE
    if _RETRIEVAL_PIPELINE is None:
        _RETRIEVAL_PIPELINE = DefaultRetrievalPipeline(
            index_store=_get_store(),
            vector_store=_get_vector_store(),
        )
    return _RETRIEVAL_PIPELINE


def _try_upsert_qdrant(collection_name: str, chunks: list[IndexedChunk]) -> tuple[str, list[str], FailedFile | None]:
    vector_store = _get_vector_store()
    if not vector_store.enabled:
        return "json_fallback", ["qdrant_disabled"], None

    try:
        started = datetime.now()
        upserted, warnings = vector_store.upsert_chunks(collection_name, chunks)
        elapsed_ms = int((datetime.now() - started).total_seconds() * 1000)
        logger.info(
            "medical.ingest qdrant upsert collection=%s chunks=%s elapsed_ms=%s warnings=%s",
            collection_name,
            upserted,
            elapsed_ms,
            warnings,
        )
        backend = "qdrant" if not warnings else "dual_write_partial"
        return backend, warnings, None
    except Exception as exc:
        logger.warning("medical.ingest qdrant fallback collection=%s error=%s", collection_name, exc)
        return (
            "json_fallback",
            [f"qdrant_upsert_failed:{type(exc).__name__}"],
            FailedFile(file="__qdrant__", reason=str(exc)),
        )


def _split_text(text: str, chunk_size: int = 1200, overlap: int = 150) -> List[str]:
    value = (text or "").strip()
    if not value:
        return []
    if len(value) <= chunk_size:
        return [value]

    chunks: List[str] = []
    start = 0
    while start < len(value):
        end = min(len(value), start + chunk_size)
        chunks.append(value[start:end].strip())
        if end >= len(value):
            break
        start = max(0, end - overlap)
    return [chunk for chunk in chunks if chunk]


def _tokenize(value: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z0-9]{2,}", value.lower()))


def _similarity(query: str, text: str) -> float:
    q = _tokenize(query)
    t = _tokenize(text)
    if not q or not t:
        return 0.0
    intersect = len(q.intersection(t))
    union = len(q.union(t))
    return intersect / max(1, union)


def _extract_metadata(text: str) -> Dict[str, int | str | None]:
    meta = _METADATA_EXTRACTOR.extract(RawDocument(source="inline://metadata", raw_content=text))
    return {"title": meta.title, "year": meta.year, "doi": meta.doi, "journal": meta.journal}


def _list_files(path: Path, recursive: bool) -> List[Path]:
    return core_list_files(path, recursive)


def _loader_for_file(file_path: Path):
    return core_loader_for_file(file_path)


async def _emit_progress(callback: ProgressCallback | None, **payload: Any) -> None:
    if callback is None:
        return
    result = callback(**payload)
    if inspect.isawaitable(result):
        await result


def _collection_seen_sources(collection: dict[str, Any]) -> set[str]:
    docs = collection.get("docs", []) if isinstance(collection, dict) else []
    chunks = collection.get("chunks", []) if isinstance(collection, dict) else []
    seen = {str(doc.get("source")) for doc in docs if isinstance(doc, dict) and doc.get("source")}
    seen.update(str(chunk.get("source")) for chunk in chunks if isinstance(chunk, dict) and chunk.get("source"))
    return seen


def _merge_collection_data(
    existing_collection: dict[str, Any],
    new_docs: list[dict[str, Any]],
    new_chunks: list[IndexedChunk],
) -> tuple[list[dict[str, Any]], list[Any]]:
    existing_docs = existing_collection.get("docs", []) if isinstance(existing_collection, dict) else []
    existing_chunks = existing_collection.get("chunks", []) if isinstance(existing_collection, dict) else []

    merged_docs: list[dict[str, Any]] = []
    seen_doc_ids: set[str] = set()
    for doc in existing_docs:
        if not isinstance(doc, dict):
            continue
        key = str(doc.get("doc_id") or doc.get("source") or "")
        if key and key not in seen_doc_ids:
            merged_docs.append(doc)
            seen_doc_ids.add(key)
    for doc in new_docs:
        key = str(doc.get("doc_id") or doc.get("source") or "")
        if key and key not in seen_doc_ids:
            merged_docs.append(doc)
            seen_doc_ids.add(key)

    merged_chunks: list[Any] = []
    seen_chunk_ids: set[str] = set()
    for chunk in existing_chunks:
        if not isinstance(chunk, dict):
            continue
        key = str(chunk.get("chunk_id") or "")
        if key and key not in seen_chunk_ids:
            merged_chunks.append(chunk)
            seen_chunk_ids.add(key)
    for chunk in new_chunks:
        key = chunk.chunk_id
        if key not in seen_chunk_ids:
            merged_chunks.append(chunk)
            seen_chunk_ids.add(key)

    return merged_docs, merged_chunks


async def ingest_documents(request: MedicalIngestRequest, progress_callback: ProgressCallback | None = None) -> MedicalIngestResponse:
    base_path = Path(request.doc_path).expanduser().resolve()
    candidates = _list_files(base_path, request.recursive)
    if not candidates:
        return MedicalIngestResponse(indexed_docs=0, chunks=0, failed_files=[FailedFile(file=str(base_path), reason="No supported files found")])

    store = _get_store()
    existing_collection = store.get_collection(request.collection_name)
    existing_sources = _collection_seen_sources(existing_collection)

    await _emit_progress(
        progress_callback,
        stage="ingesting",
        message="start ingest",
        total_files=len(candidates),
        processed_files=0,
        skipped_files=0,
        indexed_docs=0,
        chunks=0,
        failed_files=0,
    )

    docs_summary, chunks, failed, skipped_files = await _ingest_files(
        files=candidates,
        collection_name=request.collection_name,
        metadata_map={},
        existing_sources=existing_sources,
        progress_callback=progress_callback,
    )

    index_backend, index_warnings, qdrant_failed = _try_upsert_qdrant(request.collection_name, chunks)
    if qdrant_failed is not None:
        failed.append(qdrant_failed)

    merged_docs, merged_chunks = _merge_collection_data(existing_collection, docs_summary, chunks)
    store.upsert_collection(request.collection_name, merged_docs, merged_chunks)

    await _emit_progress(
        progress_callback,
        stage="persisted",
        message="ingest persisted",
        total_files=len(candidates),
        processed_files=len(candidates),
        skipped_files=skipped_files,
        indexed_docs=len(docs_summary),
        chunks=len(chunks),
        failed_files=len(failed),
    )

    return MedicalIngestResponse(
        indexed_docs=len(docs_summary),
        chunks=len(chunks),
        skipped_files=skipped_files,
        failed_files=failed,
        index_backend=index_backend,
        index_warnings=index_warnings,
    )


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _derive_lookup_keys(file_path: Path) -> set[str]:
    stem = file_path.stem
    return {
        _normalize_name(stem),
        _normalize_name(file_path.name),
    }


def _parse_bibtex_entries(content: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for raw in re.split(r"\n@", "\n" + content):
        block = raw.strip()
        if not block:
            continue
        if not block.startswith("@"):
            block = "@" + block
        body = block.split("{", 1)
        if len(body) != 2:
            continue
        entry: dict[str, Any] = {}
        for field, value in re.findall(r"(\w+)\s*=\s*[{\"]([^{}\"]+)[}\"]", body[1], flags=re.IGNORECASE):
            entry[field.lower()] = value.strip()
        if entry:
            entries.append(entry)
    return entries


def _build_zotero_metadata_map(
    zotero_json_path: str | None,
    bibtex_path: str | None,
) -> tuple[dict[str, dict[str, Any]], int, int]:
    metadata_map: dict[str, dict[str, Any]] = {}
    json_entries = 0
    bib_entries = 0

    if zotero_json_path:
        json_path = Path(zotero_json_path).expanduser().resolve()
        if json_path.exists():
            try:
                raw = json.loads(json_path.read_text(encoding="utf-8"))
                items = raw if isinstance(raw, list) else []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    title = item.get("title") or item.get("data", {}).get("title")
                    doi = item.get("DOI") or item.get("data", {}).get("DOI")
                    date = item.get("date") or item.get("data", {}).get("date")
                    journal = (
                        item.get("publicationTitle")
                        or item.get("journalAbbreviation")
                        or item.get("data", {}).get("publicationTitle")
                        or item.get("data", {}).get("journalAbbreviation")
                    )
                    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", str(date or ""))
                    year = int(year_match.group(1)) if year_match else None
                    key_candidates = []

                    attachments = item.get("attachments") or item.get("data", {}).get("attachments") or []
                    for attachment in attachments:
                        if isinstance(attachment, dict):
                            local_path = attachment.get("path") or attachment.get("localPath")
                            if local_path:
                                key_candidates.append(_normalize_name(Path(str(local_path)).name))
                                key_candidates.append(_normalize_name(Path(str(local_path)).stem))

                    if title:
                        key_candidates.append(_normalize_name(str(title)))
                    if doi:
                        key_candidates.append(_normalize_name(str(doi)))

                    entry_meta = {"title": title, "doi": doi, "year": year, "journal": journal}
                    for key in key_candidates:
                        if key:
                            metadata_map[key] = entry_meta
                    json_entries += 1
            except Exception:
                pass

    if bibtex_path:
        bib_path = Path(bibtex_path).expanduser().resolve()
        if bib_path.exists():
            try:
                entries = _parse_bibtex_entries(bib_path.read_text(encoding="utf-8"))
                for entry in entries:
                    title = entry.get("title")
                    doi = entry.get("doi")
                    year = int(entry["year"]) if entry.get("year", "").isdigit() else None
                    journal = entry.get("journal") or entry.get("journaltitle")
                    key_candidates = [
                        _normalize_name(entry.get("file", "")),
                        _normalize_name(entry.get("title", "")),
                        _normalize_name(entry.get("doi", "")),
                        _normalize_name(entry.get("citekey", "")),
                    ]
                    entry_meta = {"title": title, "doi": doi, "year": year, "journal": journal}
                    for key in key_candidates:
                        if key:
                            metadata_map[key] = entry_meta
                    bib_entries += 1
            except Exception:
                pass

    return metadata_map, json_entries, bib_entries


def _match_external_metadata(file_path: Path, metadata_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    keys = _derive_lookup_keys(file_path)
    for key in keys:
        if key in metadata_map:
            return metadata_map[key]

    # Fallback: fuzzy partial includes
    normalized_stem = _normalize_name(file_path.stem)
    for key, meta in metadata_map.items():
        if normalized_stem and (normalized_stem in key or key in normalized_stem):
            return meta
    return {}


async def _ingest_files(
    files: list[Path],
    collection_name: str,
    metadata_map: dict[str, dict[str, Any]],
    existing_sources: set[str] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[list[dict], list[IndexedChunk], list[FailedFile], int]:
    docs_summary = []
    chunks: list[IndexedChunk] = []
    failed: list[FailedFile] = []
    skipped_files = 0
    seen_sources = set(existing_sources or set())
    processed_files = 0
    total_files = len(files)

    for file_path in files:
        normalized_source = str(file_path.expanduser().resolve())
        if normalized_source in seen_sources:
            skipped_files += 1
            processed_files += 1
            await _emit_progress(
                progress_callback,
                stage="ingesting",
                message=f"skip duplicate: {file_path.name}",
                total_files=total_files,
                processed_files=processed_files,
                skipped_files=skipped_files,
                indexed_docs=len(docs_summary),
                chunks=len(chunks),
                failed_files=len(failed),
            )
            continue
        seen_sources.add(normalized_source)

        loader = _loader_for_file(file_path)
        if loader is None:
            failed.append(FailedFile(file=str(file_path), reason="Unsupported extension"))
            processed_files += 1
            await _emit_progress(
                progress_callback,
                stage="ingesting",
                message=f"unsupported file: {file_path.name}",
                total_files=total_files,
                processed_files=processed_files,
                skipped_files=skipped_files,
                indexed_docs=len(docs_summary),
                chunks=len(chunks),
                failed_files=len(failed),
            )
            continue

        try:
            pages = await asyncio.to_thread(loader.load)
        except Exception as exc:
            failed.append(FailedFile(file=str(file_path), reason=str(exc)))
            processed_files += 1
            await _emit_progress(
                progress_callback,
                stage="ingesting",
                message=f"failed load: {file_path.name}",
                total_files=total_files,
                processed_files=processed_files,
                skipped_files=skipped_files,
                indexed_docs=len(docs_summary),
                chunks=len(chunks),
                failed_files=len(failed),
            )
            continue

        if not pages:
            failed.append(FailedFile(file=str(file_path), reason="Empty document"))
            processed_files += 1
            await _emit_progress(
                progress_callback,
                stage="ingesting",
                message=f"empty doc: {file_path.name}",
                total_files=total_files,
                processed_files=processed_files,
                skipped_files=skipped_files,
                indexed_docs=len(docs_summary),
                chunks=len(chunks),
                failed_files=len(failed),
            )
            continue

        merged_text = "\n".join([p.page_content for p in pages if p.page_content]).strip()
        extracted = _extract_metadata(merged_text)
        external = _match_external_metadata(file_path, metadata_map)
        matched_external = bool(external)
        metadata = {
            "title": external.get("title") or extracted.get("title"),
            "year": external.get("year") or extracted.get("year"),
            "doi": external.get("doi") or extracted.get("doi"),
            "journal": external.get("journal") or extracted.get("journal"),
        }

        doc_id = sha1(normalized_source.encode("utf-8")).hexdigest()[:16]
        docs_summary.append(
            {
                "doc_id": doc_id,
                "source": normalized_source,
                "title": metadata.get("title"),
                "year": metadata.get("year"),
                "doi": metadata.get("doi"),
                "pages": len(pages),
                "external_metadata_matched": matched_external,
                "journal": metadata.get("journal"),
            }
        )

        for page in pages:
            page_text = (page.page_content or "").strip()
            if not page_text:
                continue

            page_no = page.metadata.get("page")
            if isinstance(page_no, int):
                page_no = page_no + 1
            else:
                page_no = None

            for idx, chunk in enumerate(_split_text(page_text)):
                chunk_id = sha1(f"{doc_id}:{page_no}:{idx}:{chunk[:64]}".encode("utf-8")).hexdigest()[:20]
                chunks.append(
                    IndexedChunk(
                        chunk_id=chunk_id,
                        collection_name=collection_name,
                        source=normalized_source,
                        page=page_no,
                        text=chunk,
                        title=metadata.get("title"),
                        doi=metadata.get("doi"),
                        year=metadata.get("year"),
                        journal=metadata.get("journal"),
                        external_metadata_matched=matched_external,
                    )
                )

        processed_files += 1
        await _emit_progress(
            progress_callback,
            stage="ingesting",
            message=f"indexed: {file_path.name}",
            total_files=total_files,
            processed_files=processed_files,
            skipped_files=skipped_files,
            indexed_docs=len(docs_summary),
            chunks=len(chunks),
            failed_files=len(failed),
        )

    return docs_summary, chunks, failed, skipped_files


async def ingest_zotero_documents(
    request: ZoteroIngestRequest,
    progress_callback: ProgressCallback | None = None,
) -> ZoteroIngestResponse:
    pdf_root = Path(request.pdf_dir).expanduser().resolve()
    pdf_candidates = _list_files(pdf_root, request.recursive)
    if not pdf_candidates:
        return ZoteroIngestResponse(
            collection_name=request.collection_name,
            indexed_docs=0,
            chunks=0,
            skipped_files=0,
            failed_files=[FailedFile(file=str(pdf_root), reason="No supported files found")],
            match_stats=ZoteroMatchStats(),
        )

    store = _get_store()
    existing_collection = store.get_collection(request.collection_name)
    existing_sources = _collection_seen_sources(existing_collection)

    await _emit_progress(
        progress_callback,
        stage="ingesting",
        message="start zotero ingest",
        total_files=len(pdf_candidates),
        processed_files=0,
        skipped_files=0,
        indexed_docs=0,
        chunks=0,
        failed_files=0,
    )

    metadata_map, json_entries, bib_entries = _build_zotero_metadata_map(
        request.zotero_json_path,
        request.bibtex_path,
    )
    docs_summary, chunks, failed, skipped_files = await _ingest_files(
        files=pdf_candidates,
        collection_name=request.collection_name,
        metadata_map=metadata_map,
        existing_sources=existing_sources,
        progress_callback=progress_callback,
    )
    index_backend, index_warnings, qdrant_failed = _try_upsert_qdrant(request.collection_name, chunks)
    if qdrant_failed is not None:
        failed.append(qdrant_failed)

    matched = sum(1 for doc in docs_summary if doc.get("external_metadata_matched"))
    unmatched = max(0, len(pdf_candidates) - matched)

    merged_docs, merged_chunks = _merge_collection_data(existing_collection, docs_summary, chunks)
    store.upsert_collection(request.collection_name, merged_docs, merged_chunks)

    await _emit_progress(
        progress_callback,
        stage="persisted",
        message="zotero ingest persisted",
        total_files=len(pdf_candidates),
        processed_files=len(pdf_candidates),
        skipped_files=skipped_files,
        indexed_docs=len(docs_summary),
        chunks=len(chunks),
        failed_files=len(failed),
    )

    return ZoteroIngestResponse(
        collection_name=request.collection_name,
        indexed_docs=len(docs_summary),
        chunks=len(chunks),
        skipped_files=skipped_files,
        failed_files=failed,
        index_backend=index_backend,
        index_warnings=index_warnings,
        match_stats=ZoteroMatchStats(
            pdf_files=len(pdf_candidates),
            matched_metadata=matched,
            unmatched_pdf_files=unmatched,
            json_entries=json_entries,
            bib_entries=bib_entries,
        ),
    )


def _track_job_task(job_id: str, task: asyncio.Task[Any]) -> None:
    _RUNNING_JOBS[job_id] = task
    task.add_done_callback(lambda _: _RUNNING_JOBS.pop(job_id, None))


async def _run_ingest_job(job_id: str, request: MedicalIngestRequest) -> None:
    store = _get_job_store()
    await store.set_running(job_id)

    async def progress_callback(**progress_patch: Any) -> None:
        await store.update_progress(job_id, **progress_patch)

    try:
        response = await ingest_documents(request, progress_callback=progress_callback)
        await store.update_progress(
            job_id,
            stage="completed",
            message="ingest completed",
            indexed_docs=response.indexed_docs,
            chunks=response.chunks,
            skipped_files=response.skipped_files,
            failed_files=len(response.failed_files),
        )
        await store.set_completed(job_id, response.model_dump())
    except Exception as exc:
        await store.update_progress(job_id, stage="failed", message=str(exc))
        await store.set_failed(job_id, str(exc))
        logger.exception("medical.ingest async failed job_id=%s", job_id)


async def _run_zotero_ingest_job(job_id: str, request: ZoteroIngestRequest) -> None:
    store = _get_job_store()
    await store.set_running(job_id)

    async def progress_callback(**progress_patch: Any) -> None:
        await store.update_progress(job_id, **progress_patch)

    try:
        response = await ingest_zotero_documents(request, progress_callback=progress_callback)
        await store.update_progress(
            job_id,
            stage="completed",
            message="zotero ingest completed",
            indexed_docs=response.indexed_docs,
            chunks=response.chunks,
            skipped_files=response.skipped_files,
            failed_files=len(response.failed_files),
        )
        await store.set_completed(job_id, response.model_dump())
    except Exception as exc:
        await store.update_progress(job_id, stage="failed", message=str(exc))
        await store.set_failed(job_id, str(exc))
        logger.exception("medical.zotero_ingest async failed job_id=%s", job_id)


async def start_medical_ingest_job(request: MedicalIngestRequest) -> MedicalJobCreateResponse:
    job_id = uuid4().hex
    store = _get_job_store()
    await store.create_job(job_id=job_id, job_type="medical_ingest", payload=request.model_dump())
    task = asyncio.create_task(_run_ingest_job(job_id, request), name=f"medical-ingest-{job_id}")
    _track_job_task(job_id, task)
    return MedicalJobCreateResponse(job_id=job_id, status="pending")


async def start_zotero_ingest_job(request: ZoteroIngestRequest) -> MedicalJobCreateResponse:
    job_id = uuid4().hex
    store = _get_job_store()
    await store.create_job(job_id=job_id, job_type="zotero_ingest", payload=request.model_dump())
    task = asyncio.create_task(_run_zotero_ingest_job(job_id, request), name=f"medical-zotero-ingest-{job_id}")
    _track_job_task(job_id, task)
    return MedicalJobCreateResponse(job_id=job_id, status="pending")


async def get_medical_job_status(job_id: str) -> MedicalJobStatusResponse | None:
    store = _get_job_store()
    job = await store.get_job(job_id)
    if not job:
        return None

    progress_data = job.get("progress", {})
    return MedicalJobStatusResponse(
        job_id=job["job_id"],
        job_type=job.get("job_type", "unknown"),
        status=job.get("status", "pending"),
        created_at=job.get("created_at", 0),
        updated_at=job.get("updated_at", 0),
        progress=MedicalJobProgress(**progress_data),
        result=job.get("result"),
        error=job.get("error"),
    )


def _expand_query(query: str) -> str:
    expanded_terms = [query]
    lower_query = query.lower()
    for key, terms in _MESH_EXPANSION.items():
        if key in lower_query:
            expanded_terms.extend(terms)
    if "trial" in lower_query:
        expanded_terms.extend(["randomized controlled trial", "cohort study"])
    return " OR ".join(dict.fromkeys(expanded_terms))


def _extract_doi_from_text(value: str) -> str | None:
    match = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b", value)
    return match.group(0).lower() if match else None


def _extract_year_from_text(value: str) -> int | None:
    match = re.search(r"\b(19\d{2}|20\d{2})\b", value)
    if match:
        return int(match.group(1))
    return None


def _score_local_chunk(query: str, chunk: dict) -> float:
    score = _similarity(query, chunk.get("text", ""))
    lowered_query = query.lower()

    query_doi = _extract_doi_from_text(query)
    chunk_doi = (chunk.get("doi") or "").lower()
    if query_doi and chunk_doi and query_doi == chunk_doi:
        score += 0.25

    query_year = _extract_year_from_text(query)
    chunk_year = chunk.get("year")
    if query_year and isinstance(chunk_year, int) and query_year == chunk_year:
        score += 0.08

    journal = (chunk.get("journal") or "").strip()
    if journal:
        journal_tokens = _tokenize(journal)
        query_tokens = _tokenize(lowered_query)
        overlap = len(journal_tokens.intersection(query_tokens))
        if overlap > 0:
            score += min(0.12, overlap * 0.04)

    if isinstance(chunk_year, int):
        age = max(0, datetime.now().year - chunk_year)
        if age <= 2:
            score += 0.08
        elif age <= 5:
            score += 0.04

    if chunk.get("external_metadata_matched"):
        score += 0.04

    return max(0.0, min(1.0, score))


async def _local_search(query: str, collection_name: str, top_k: int) -> List[MedicalSearchResult]:
    pipeline = _get_retrieval_pipeline()
    hits = await pipeline.search(query=query, namespace=collection_name, top_k=top_k)
    results: list[MedicalSearchResult] = []
    for hit in hits:
        snippet = hit.snippet[:500]
        meta = hit.metadata or {}
        results.append(
            MedicalSearchResult(
                source_type="local",
                source=hit.source or "local",
                title=meta.get("title"),
                snippet=snippet,
                score=round(hit.score, 4),
                page=meta.get("page"),
                doi=meta.get("doi"),
                year=meta.get("year"),
                journal=meta.get("journal"),
            )
        )
    return results


def _rerank_local_results(query: str, results: list[MedicalSearchResult], top_k: int) -> list[MedicalSearchResult]:
    rescored: list[tuple[float, MedicalSearchResult]] = []
    for item in results:
        chunk_like = {
            "text": item.snippet,
            "doi": item.doi,
            "year": item.year,
            "journal": item.journal,
            "external_metadata_matched": bool(item.doi or item.journal),
        }
        metadata_score = _score_local_chunk(query, chunk_like)
        merged = min(1.0, (item.score * 0.6) + (metadata_score * 0.4))
        item.score = round(merged, 4)
        rescored.append((item.score, item))

    rescored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in rescored[:top_k]]


def _web_search(query: str, top_k: int) -> List[MedicalSearchResult]:
    results: list[MedicalSearchResult] = []

    try:
        pmc_results = PubMedCentralSearch(query).search(max_results=max(1, min(5, top_k))) or []
        for item in pmc_results:
            content = (item.get("raw_content") or "").strip()
            results.append(
                MedicalSearchResult(
                    source_type="web",
                    source="pubmed_central",
                    title=item.get("title"),
                    snippet=content[:500],
                    score=0.8,
                    url=item.get("url"),
                )
            )
    except Exception:
        pass

    try:
        scholar_results = SemanticScholarSearch(query).search(max_results=max(1, min(10, top_k))) or []
        for item in scholar_results:
            body = (item.get("body") or "").strip()
            results.append(
                MedicalSearchResult(
                    source_type="web",
                    source="semantic_scholar",
                    title=item.get("title"),
                    snippet=body[:500],
                    score=0.7,
                    url=item.get("href"),
                )
            )
    except Exception:
        pass

    return results[:top_k]


async def medical_search(request: MedicalSearchRequest) -> MedicalSearchResponse:
    expanded_query = _expand_query(request.query)

    results: list[MedicalSearchResult] = []
    if request.sources in {"local", "hybrid"}:
        local_backend_used = "json_fallback"
        local_results: list[MedicalSearchResult] = []
        vector_store = _get_vector_store()

        if vector_store.enabled and vector_store.healthy():
            try:
                local_results = vector_store.search(request.collection_name, expanded_query, request.top_k)
                if local_results:
                    local_backend_used = "qdrant"
                    logger.info(
                        "medical.search local backend=qdrant collection=%s results=%s",
                        request.collection_name,
                        len(local_results),
                    )
                else:
                    logger.info(
                        "medical.search local backend=qdrant-empty fallback=json collection=%s",
                        request.collection_name,
                    )
            except Exception as exc:
                logger.warning(
                    "medical.search local backend=qdrant error=%s fallback=json collection=%s",
                    type(exc).__name__,
                    request.collection_name,
                )

        if not local_results:
            local_results = await _local_search(expanded_query, request.collection_name, request.top_k)
            logger.info(
                "medical.search local backend=json_fallback collection=%s results=%s",
                request.collection_name,
                len(local_results),
            )

        local_results = _rerank_local_results(expanded_query, local_results, request.top_k)
        logger.debug("medical.search local_backend_used=%s", local_backend_used)
        results.extend(local_results)

    if request.sources in {"web", "hybrid"}:
        web_results = await asyncio.to_thread(_web_search, expanded_query, request.top_k)
        results.extend(web_results)

    results.sort(key=lambda item: item.score, reverse=True)
    return MedicalSearchResponse(query=request.query, expanded_query=expanded_query, results=results[: request.top_k])


def _split_sentences(text: str) -> List[str]:
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.strip()]
    if parts:
        return parts
    return [text.strip()] if text.strip() else []


def _mode_instruction(mode: str, journal_style: str | None) -> str:
    if mode == "concise":
        return "Make the writing concise, remove redundancy, and keep scientific meaning unchanged."
    if mode == "journal":
        style = journal_style or "target journal style"
        return f"Rewrite in formal journal style compatible with {style}."
    return "Improve academic clarity, grammar, and scientific tone without changing claims."


async def polish_text(request: MedicalPolishRequest) -> MedicalPolishResponse:
    risk_flags: List[str] = []
    evidence_map: List[EvidenceRef] = []

    sentences = _split_sentences(request.text)
    if not sentences:
        return MedicalPolishResponse(revisions=[], evidence_map=[], risk_flags=["empty_input"])

    if request.require_evidence:
        search_response = await medical_search(
            MedicalSearchRequest(
                query=request.text[:500],
                top_k=min(8, max(3, len(sentences))),
                sources="hybrid",
                collection_name=request.collection_name,
            )
        )

        def evidence_quality(item: MedicalSearchResult) -> float:
            quality = item.score
            if item.doi:
                quality += 0.12
            if item.journal:
                quality += 0.08
            if isinstance(item.year, int):
                age = max(0, datetime.now().year - item.year)
                if age <= 2:
                    quality += 0.08
                elif age <= 5:
                    quality += 0.04
            if item.source == "pubmed_central":
                quality += 0.06
            elif item.source == "semantic_scholar":
                quality += 0.04
            return min(1.0, max(0.0, quality))

        for idx, sentence in enumerate(sentences):
            sentence_id = f"s{idx + 1}"
            best = None
            best_combined = 0.0
            best_similarity = 0.0
            for item in search_response.results:
                similarity = _similarity(sentence, item.snippet)
                quality = evidence_quality(item)
                combined = (similarity * 0.65) + (quality * 0.35)
                if combined > best_combined:
                    best = item
                    best_combined = combined
                    best_similarity = similarity
            if best is None:
                continue
            evidence_map.append(
                EvidenceRef(
                    sentence_id=sentence_id,
                    source=best.source,
                    page=best.page,
                    snippet=best.snippet[:240],
                    confidence=round(best_combined, 4),
                    doi=best.doi,
                )
            )
            if best_similarity < 0.08:
                risk_flags.append(f"weak_evidence_alignment:{sentence_id}")

        local_count = sum(1 for item in evidence_map if item.source not in {"pubmed_central", "semantic_scholar"})
        web_count = len(evidence_map) - local_count
        logger.info(
            "medical.polish evidence_map total=%s local=%s web=%s",
            len(evidence_map),
            local_count,
            web_count,
        )

    cfg = Config(config_path="default")
    revised_text = request.text

    llm_available = bool(
        os.getenv("OPENAI_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or os.getenv("AZURE_OPENAI_API_KEY")
        or os.getenv("OPENROUTER_API_KEY")
    )

    if llm_available:
        strict_clause = (
            "Do not add new medical facts or numerical claims not present in input."
            if request.strict_fact_mode
            else "Preserve intent and scientific plausibility."
        )
        section_clause = f"Section type: {request.section_type}." if request.section_type else ""
        journal_clause = f"Target journal: {request.target_journal}." if request.target_journal else ""
        prompt = (
            "You are an expert biomedical scientific editor.\n"
            f"{_mode_instruction(request.mode, request.journal_style)}\n"
            f"{strict_clause}\n"
            "Keep citations markers if present.\n"
            f"{section_clause}\n"
            f"{journal_clause}\n"
            "Return only revised text."
        )

        try:
            revised_text = await create_chat_completion(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": request.text},
                ],
                model=cfg.smart_llm_model,
                llm_provider=cfg.smart_llm_provider,
                llm_kwargs=cfg.llm_kwargs,
                temperature=0.2,
                max_tokens=4000,
            )
        except Exception as exc:
            risk_flags.append(f"llm_failed:{type(exc).__name__}")
            revised_text = request.text
    else:
        risk_flags.append("llm_not_configured")

    revised_sentences = _split_sentences(revised_text)
    revisions = []
    for idx, original in enumerate(sentences):
        revised = revised_sentences[idx] if idx < len(revised_sentences) else original
        reason = "Academic rewrite" if revised != original else "No change"
        revisions.append(RevisionItem(sentence_id=f"s{idx + 1}", original=original, revised=revised, reason=reason))

    if request.strict_fact_mode and request.require_evidence:
        covered = {item.sentence_id for item in evidence_map if item.confidence > 0.2}
        missing = [f"s{idx + 1}" for idx in range(len(sentences)) if f"s{idx + 1}" not in covered]
        if missing:
            risk_flags.append(f"missing_evidence:{','.join(missing)}")

    return MedicalPolishResponse(revisions=revisions, evidence_map=evidence_map, risk_flags=risk_flags)


def _detect_citation_style(text: str) -> str:
    has_vancouver = bool(re.search(r"\[\d+(?:,\s*\d+|\-\d+)?\]", text))
    has_apa = bool(re.search(r"\([A-Z][A-Za-z\-]+,\s*\d{4}[a-z]?\)", text))
    if has_vancouver and has_apa:
        return "mixed"
    if has_vancouver:
        return "vancouver"
    if has_apa:
        return "apa"
    return "none"


def _contains_claim(sentence: str) -> bool:
    lowered = sentence.lower()
    return any(marker in lowered for marker in _CLAIM_MARKERS)


def _has_citation(sentence: str) -> bool:
    return bool(
        re.search(r"\[\d+(?:,\s*\d+|\-\d+)?\]", sentence)
        or re.search(r"\([A-Z][A-Za-z\-]+,\s*\d{4}[a-z]?\)", sentence)
    )


def _extract_vancouver_numbers(text: str) -> list[int]:
    values: list[int] = []
    for match in re.findall(r"\[(\d+(?:\s*[-,]\s*\d+)*)\]", text):
        for part in re.split(r"\s*,\s*", match):
            if "-" in part:
                bounds = [p.strip() for p in part.split("-", 1)]
                if len(bounds) == 2 and bounds[0].isdigit() and bounds[1].isdigit():
                    start = int(bounds[0])
                    end = int(bounds[1])
                    if start <= end:
                        values.extend(list(range(start, end + 1)))
            elif part.strip().isdigit():
                values.append(int(part.strip()))
    return sorted(set(values))


def _extract_apa_tags(text: str) -> list[str]:
    tags = []
    for author, year in re.findall(r"\(([A-Z][A-Za-z\-]+),\s*(\d{4}[a-z]?)\)", text):
        tags.append(f"{author.lower()}:{year.lower()}")
    return sorted(set(tags))


def _parse_reference_items(references: Sequence[str]) -> tuple[dict[int, str], dict[str, str]]:
    numbered: dict[int, str] = {}
    apa_map: dict[str, str] = {}
    for line in references:
        if not line:
            continue
        numbered_match = re.match(r"^\s*\[?(\d+)\]?[.)]?\s+(.*)$", line.strip())
        if numbered_match:
            numbered[int(numbered_match.group(1))] = numbered_match.group(2).strip()

        apa_match = re.search(r"([A-Z][A-Za-z\-]+).*?(\d{4}[a-z]?)", line)
        if apa_match:
            key = f"{apa_match.group(1).lower()}:{apa_match.group(2).lower()}"
            apa_map[key] = line.strip()
    return numbered, apa_map


def _reference_overlap(sentence: str, references: Sequence[str]) -> float:
    if not references:
        return 0.0
    return max((_similarity(sentence, ref) for ref in references), default=0.0)


async def citation_audit(request: CitationAuditRequest) -> CitationAuditResponse:
    sentences = _split_sentences(request.manuscript_text)
    missing: List[CitationIssue] = []
    weak: List[CitationIssue] = []
    unmatched: List[CitationIssue] = []
    format_issues: List[str] = []
    unused_references: List[str] = []

    detected = _detect_citation_style(request.manuscript_text)
    if detected == "mixed":
        format_issues.append("Mixed citation styles detected (APA + Vancouver).")
    elif request.format != "auto" and detected not in {"none", request.format}:
        format_issues.append(f"Expected {request.format} citation style but detected {detected}.")

    references = request.references or []
    numbered_refs, apa_refs = _parse_reference_items(references)
    used_numbered: set[int] = set()
    used_apa: set[str] = set()

    for idx, sentence in enumerate(sentences):
        sentence_id = f"s{idx + 1}"
        if _contains_claim(sentence) and not _has_citation(sentence):
            missing.append(
                CitationIssue(
                    sentence_id=sentence_id,
                    sentence=sentence,
                    reason="Claim-like sentence without citation marker",
                )
            )
        if _has_citation(sentence) and references:
            overlap = _reference_overlap(sentence, references)
            if overlap < 0.08:
                weak.append(
                    CitationIssue(
                        sentence_id=sentence_id,
                        sentence=sentence,
                        reason="Citation exists but support from provided references looks weak",
                    )
                )

            for num in _extract_vancouver_numbers(sentence):
                used_numbered.add(num)
                if numbered_refs and num not in numbered_refs:
                    unmatched.append(
                        CitationIssue(
                            sentence_id=sentence_id,
                            sentence=sentence,
                            reason=f"Vancouver citation [{num}] not found in provided references",
                        )
                    )

            for tag in _extract_apa_tags(sentence):
                used_apa.add(tag)
                if apa_refs and tag not in apa_refs:
                    unmatched.append(
                        CitationIssue(
                            sentence_id=sentence_id,
                            sentence=sentence,
                            reason=f"APA citation ({tag}) not found in provided references",
                        )
                    )

    if numbered_refs:
        for number, line in numbered_refs.items():
            if number not in used_numbered:
                unused_references.append(f"[{number}] {line}")
    elif apa_refs:
        for key, line in apa_refs.items():
            if key not in used_apa:
                unused_references.append(line)

    weighted_total = len(missing) + len(weak) + len(unmatched) + len(format_issues)
    sentence_count = max(1, len(sentences))
    consistency_score = max(0.0, min(1.0, 1.0 - (weighted_total / (sentence_count * 1.5))))

    return CitationAuditResponse(
        missing_citations=missing,
        weak_claims=weak,
        unmatched_citations=unmatched,
        unused_references=unused_references,
        format_issues=format_issues,
        consistency_score=round(consistency_score, 4),
    )
