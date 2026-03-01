from gpt_researcher.core.documents import DefaultChunker, PDFSectionSplitter, RawDocument
from gpt_researcher.core.documents.types import ChunkPolicy


def test_core_pdf_section_splitter_basic():
    text = """
Title

Abstract
a

1 Introduction
b

References
c
""".strip()
    sections = PDFSectionSplitter.split(text)
    names = [s["section"] for s in sections]
    assert "abstract" in names
    assert "introduction" in names
    assert "reference" in names


def test_default_chunker_overlap():
    doc = RawDocument(source="a", raw_content="x" * 2600)
    chunker = DefaultChunker()
    chunks = chunker.chunk(doc, ChunkPolicy(chunk_size=1000, overlap=200))
    assert len(chunks) >= 3
    assert chunks[0].chunk_id != chunks[1].chunk_id
