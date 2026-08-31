import pytest

from catalog import load_catalog
from rally_adk.handoff import build_handoff
from store import MemoryRunStore


def test_handoff_preserves_policy_and_normalizes_task():
    handoff = build_handoff("  Add   rate limiting  ")
    assert handoff["task"] == "Add rate limiting"
    assert handoff["source"] == "google-adk"
    assert handoff["policy"]["requires_independent_verification"] is True


@pytest.mark.asyncio
async def test_request_key_is_idempotent():
    store = MemoryRunStore()
    first = {"run_id": "r-first", "request_key": "same", "status": "queued"}
    second = {"run_id": "r-second", "request_key": "same", "status": "queued"}
    assert await store.create(first) is True
    assert await store.create(second) is False
    assert (await store.get_by_request_key("same"))["run_id"] == "r-first"


@pytest.mark.asyncio
async def test_concurrent_request_key_has_one_winner():
    store = MemoryRunStore()
    records = [
        {"run_id": f"r-{index}", "request_key": "same", "status": "queued"} for index in range(20)
    ]
    results = await __import__("asyncio").gather(*(store.create(record) for record in records))
    assert results.count(True) == 1
    assert results.count(False) == 19


@pytest.mark.asyncio
async def test_failed_coordination_can_be_reclaimed_once():
    store = MemoryRunStore()
    record = {
        "run_id": "r-first",
        "request_key": "same",
        "status": "coordinator_failed",
        "attempts": 1,
    }
    assert await store.create(record) is True

    resumed = await store.reclaim("same", 9_999_999_999, "2026-08-29T08:00:00Z")
    duplicate = await store.reclaim("same", 9_999_999_999, "2026-08-29T08:00:01Z")

    assert resumed["status"] == "coordinating"
    assert resumed["attempts"] == 2
    assert duplicate is None


@pytest.mark.asyncio
async def test_older_attempt_cannot_overwrite_reclaimed_record():
    store = MemoryRunStore()
    record = {
        "run_id": "r-first",
        "request_key": "same",
        "status": "coordinator_failed",
        "attempts": 1,
    }
    assert await store.create(record) is True
    resumed = await store.reclaim("same", 9_999_999_999, "2026-08-29T08:00:00Z")
    assert resumed["attempts"] == 2

    stale = {**record, "status": "ready_for_rally"}
    assert await store.update("r-first", stale, expected_attempt=1) is False
    assert (await store.get("r-first"))["status"] == "coordinating"


def test_agent_catalog_has_distinct_families_and_governed_authority():
    catalog = load_catalog()
    families = {agent["family"] for agent in catalog["agents"]}

    assert {"anthropic", "google"} <= families
    assert catalog["policy"]["retention_days"] >= 30
    for agent in catalog["agents"]:
        assert agent["capabilities"]
        assert agent["authority"]
        assert agent["prohibited"]
