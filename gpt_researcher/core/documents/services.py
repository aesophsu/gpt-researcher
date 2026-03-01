from __future__ import annotations

import asyncio
import os
import re
from hashlib import sha1
from pathlib import Path

from langchain_community.document_loaders import (
    BSHTMLLoader,
    PyMuPDFLoader,
    TextLoader,
    UnstructuredCSVLoader,
    UnstructuredExcelLoader,
    UnstructuredMarkdownLoader,
    UnstructuredPowerPointLoader,
    UnstructuredWordDocumentLoader,
)

from .pdf_section_splitter import PDFSectionSplitter
from .ports import ChunkerPort, DocumentLoaderPort, MetadataExtractorPort
from .types import Chunk, ChunkPolicy, DocumentMetadata, DocumentSource, RawDocument

SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".txt",
    ".doc",
    ".docx",
    ".pptx",
    ".csv",
    ".xls",
    ".xlsx",
    ".md",
    ".html",
    ".htm",
}


def list_files(path: Path, recursive: bool) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() in SUPPORTED_EXTENSIONS else []
    if not path.exists():
        return []
    pattern = "**/*" if recursive else "*"
    return [p for p in path.glob(pattern) if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS]


def loader_for_file(file_path: Path):
    extension = file_path.suffix.lower()
    if extension == ".pdf":
        return PyMuPDFLoader(str(file_path))
    if extension == ".txt":
        return TextLoader(str(file_path))
    if extension in {".doc", ".docx"}:
        return UnstructuredWordDocumentLoader(str(file_path))
    if extension == ".pptx":
        return UnstructuredPowerPointLoader(str(file_path))
    if extension == ".csv":
        return UnstructuredCSVLoader(str(file_path), mode="elements")
    if extension in {".xls", ".xlsx"}:
        return UnstructuredExcelLoader(str(file_path), mode="elements")
    if extension == ".md":
        return UnstructuredMarkdownLoader(str(file_path))
    if extension in {".html", ".htm"}:
        return BSHTMLLoader(str(file_path))
    return None


class DefaultDocumentLoader(DocumentLoaderPort):
    async def load(self, source: DocumentSource) -> list[RawDocument]:
        paths: list[Path] = []
        if isinstance(source.path, list):
            paths = [Path(p).expanduser().resolve() for p in source.path]
        else:
            base = Path(source.path).expanduser().resolve()
            paths = list_files(base, recursive=source.recursive)

        docs: list[RawDocument] = []
        tasks = [self._load_file(path) for path in paths if path.exists()]
        for loaded in await asyncio.gather(*tasks):
            docs.extend(loaded)

        if not docs:
            raise ValueError("Failed to load any documents")
        return docs

    async def _load_file(self, file_path: Path) -> list[RawDocument]:
        loader = loader_for_file(file_path)
        if loader is None:
            return []

        try:
            pages = await asyncio.to_thread(loader.load)
        except Exception:
            return []

        if not pages:
            return []

        source = str(file_path)
        extension = file_path.suffix.lower()
        result: list[RawDocument] = []

        if extension == ".pdf":
            full_text = "\n\n".join(page.page_content for page in pages if page.page_content).strip()
            for section in PDFSectionSplitter.split(full_text):
                result.append(
                    RawDocument(
                        source=source,
                        raw_content=section["raw_content"],
                        section=section["section"],
                        metadata={"source": source, "file_extension": extension},
                    )
                )
            return result

        for page in pages:
            text = (page.page_content or "").strip()
            if not text:
                continue
            page_no = page.metadata.get("page") if isinstance(page.metadata.get("page"), int) else None
            if isinstance(page_no, int):
                page_no += 1
            result.append(
                RawDocument(
                    source=source,
                    raw_content=text,
                    metadata={"source": source, "file_extension": extension, "page": page_no},
                )
            )
        return result


class DefaultChunker(ChunkerPort):
    def chunk(self, doc: RawDocument, policy: ChunkPolicy) -> list[Chunk]:
        text = (doc.raw_content or "").strip()
        if not text:
            return []

        parts: list[str] = []
        if len(text) <= policy.chunk_size:
            parts = [text]
        else:
            start = 0
            while start < len(text):
                end = min(len(text), start + policy.chunk_size)
                parts.append(text[start:end].strip())
                if end >= len(text):
                    break
                start = max(0, end - policy.overlap)

        chunks: list[Chunk] = []
        for idx, piece in enumerate(parts):
            if not piece:
                continue
            chunk_id = sha1(f"{doc.source}:{doc.section}:{idx}:{piece[:64]}".encode("utf-8")).hexdigest()[:20]
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    source=doc.source,
                    text=piece,
                    page=doc.metadata.get("page"),
                    metadata={
                        "section": doc.section,
                        **doc.metadata,
                    },
                )
            )
        return chunks


class DefaultMetadataExtractor(MetadataExtractorPort):
    def extract(self, doc: RawDocument) -> DocumentMetadata:
        text = doc.raw_content or ""
        title = None
        year = None
        doi = None

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if lines:
            title = lines[0][:240]

        year_match = re.search(r"\b(19\d{2}|20\d{2})\b", text)
        if year_match:
            year = int(year_match.group(1))

        doi_match = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b", text)
        if doi_match:
            doi = doi_match.group(0)

        return DocumentMetadata(title=title, year=year, doi=doi, journal=None)
