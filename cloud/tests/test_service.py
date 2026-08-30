import httpx
import pytest

import service
from store import MemoryRunStore


@pytest.fixture
def cloud_service(monkeypatch):
    monkeypatch.setenv("RALLY_SERVICE_TOKEN", "test-token")
    monkeypatch.delenv("RALLY_ALLOW_INSECURE_DEV", raising=False)
    service.store = MemoryRunStore()
    return httpx.ASGITransport(app=service.app)


def headers(request_key="mail-1"):
    return {
        "X-Rally-Service-Token": "test-token",
        "Idempotency-Key": request_key,
    }


@pytest.mark.asyncio
async def test_commission_is_durable_and_duplicate_safe(cloud_service, monkeypatch):
    async def fake_coordinate(task, run_id, attempt=1):
        return f"accepted {run_id} attempt {attempt}: {task}"

    monkeypatch.setattr(service, "coordinate", fake_coordinate)
    async with httpx.AsyncClient(
        transport=cloud_service, base_url="http://rally"
    ) as client:
        first = await client.post(
            "/v1/commissions",
            json={"task": "Ship it", "run_id": "r-test-123"},
            headers=headers(),
        )
        duplicate = await client.post(
            "/v1/commissions",
            json={"task": "Ship it", "run_id": "r-test-123"},
            headers=headers(),
        )

    assert first.status_code == 202
    assert first.json()["status"] == "ready_for_rally"
    assert first.json()["attempts"] == 1
    assert duplicate.status_code == 202
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["attempts"] == 1


@pytest.mark.asyncio
async def test_failed_coordination_resumes_without_changing_request(cloud_service, monkeypatch):
    calls = 0

    async def flaky_coordinate(task, run_id, attempt=1):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient failure")
        return f"recovered {run_id} attempt {attempt}: {task}"

    monkeypatch.setattr(service, "coordinate", flaky_coordinate)
    async with httpx.AsyncClient(
        transport=cloud_service, base_url="http://rally"
    ) as client:
        failed = await client.post(
            "/v1/commissions",
            json={"task": "Ship it", "run_id": "r-test-123"},
            headers=headers(),
        )
        resumed = await client.post(
            "/v1/commissions",
            json={"task": "Ship it", "run_id": "r-test-123"},
            headers=headers(),
        )

    assert failed.status_code == 502
    assert resumed.status_code == 202
    assert resumed.json()["status"] == "ready_for_rally"
    assert resumed.json()["attempts"] == 2


@pytest.mark.asyncio
async def test_idempotency_key_rejects_conflicting_task(cloud_service, monkeypatch):
    async def fake_coordinate(task, run_id, attempt=1):
        return "accepted"

    monkeypatch.setattr(service, "coordinate", fake_coordinate)
    async with httpx.AsyncClient(
        transport=cloud_service, base_url="http://rally"
    ) as client:
        await client.post(
            "/v1/commissions",
            json={"task": "Ship it", "run_id": "r-test-123"},
            headers=headers(),
        )
        conflict = await client.post(
            "/v1/commissions",
            json={"task": "Delete it", "run_id": "r-test-123"},
            headers=headers(),
        )

    assert conflict.status_code == 409


@pytest.mark.asyncio
async def test_agent_catalog_requires_service_auth(cloud_service):
    async with httpx.AsyncClient(
        transport=cloud_service, base_url="http://rally"
    ) as client:
        denied = await client.get("/v1/agents")
        allowed = await client.get("/v1/agents", headers=headers())

    assert denied.status_code == 401
    assert allowed.status_code == 200
    catalog = allowed.json()["agents"]
    assert len(catalog) == 4
    assert any(
        agent["id"] == "rally-openai-worker" and agent["family"] == "openai"
        for agent in catalog
    )
