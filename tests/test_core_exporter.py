import urllib.parse

import pytest

from gpt_researcher.core.export import ExportTarget, MarkdownReportExporter


@pytest.mark.asyncio
async def test_exporter_markdown(tmp_path):
    exporter = MarkdownReportExporter()
    encoded = await exporter.to_markdown("hello", ExportTarget(output_dir=str(tmp_path), filename="report"))
    path = urllib.parse.unquote(encoded)
    with open(path, "r", encoding="utf-8") as f:
        assert f.read() == "hello"
