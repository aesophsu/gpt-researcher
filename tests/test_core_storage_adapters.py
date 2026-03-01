from pathlib import Path

import pytest

from gpt_researcher.core.storage.adapters import JsonReportStoreAdapter


@pytest.mark.asyncio
async def test_json_report_store_crud(tmp_path: Path):
    store = JsonReportStoreAdapter(tmp_path / "reports.json")
    await store.upsert_report("r1", {"id": "r1", "timestamp": 1})

    got = await store.get_report("r1")
    assert got is not None
    assert got["id"] == "r1"

    listed = await store.list_reports()
    assert len(listed) == 1

    deleted = await store.delete_report("r1")
    assert deleted is True
    assert await store.get_report("r1") is None
