from gpt_researcher.core.export import ExportTarget, MarkdownReportExporter

_EXPORTER = MarkdownReportExporter()

async def write_to_file(filename: str, text: str) -> None:
    await _EXPORTER._write_to_file(filename, text)  # noqa: SLF001

async def write_text_to_md(text: str, path: str) -> str:
    return await _EXPORTER.to_markdown(text, ExportTarget(output_dir=path, filename=""))


async def write_md_to_pdf(text: str, path: str) -> str:
    return await _EXPORTER.to_pdf(text, ExportTarget(output_dir=path, filename=""))


async def write_md_to_word(text: str, path: str) -> str:
    return await _EXPORTER.to_docx(text, ExportTarget(output_dir=path, filename=""))
