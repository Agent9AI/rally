import asyncio
import json
import uuid
from pathlib import Path

import httpx
import pytest
from a2a.client import ClientConfig, ClientFactory
from a2a.types import (
    GetTaskRequest,
    ListTasksRequest,
    Message,
    Part,
    Role,
    SendMessageRequest,
    TaskState,
)
from a2a.utils.constants import TransportProtocol
from sse_starlette.sse import AppStatus

import service
from a2a_adapter import MAX_TASK_CHARS, build_agent_card
from store import MemoryRunStore

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def a2a_service(monkeypatch):
    monkeypatch.setenv("RALLY_SERVICE_TOKEN", "test-token")
    monkeypatch.delenv("RALLY_ALLOW_INSECURE_DEV", raising=False)
    service.store = MemoryRunStore()

    async def fake_coordinate(task, run_id, attempt=1):
        return f"accepted {run_id} attempt {attempt}: {task}"

    monkeypatch.setattr(service, "coordinate", fake_coordinate)
    return httpx.ASGITransport(app=service.app)


def a2a_message(text: str, message_id: str | None = None) -> SendMessageRequest:
    return SendMessageRequest(
        message=Message(
            message_id=message_id or f"msg-{uuid.uuid4().hex}",
            role=Role.ROLE_USER,
            parts=[Part(text=text)],
        )
    )


async def official_client(transport, protocol):
    http = httpx.AsyncClient(
        transport=transport,
        base_url="http://rally",
        headers={"X-Rally-Service-Token": "test-token"},
    )
    config = ClientConfig(
        httpx_client=http,
        supported_protocol_bindings=[protocol],
        use_client_preference=True,
    )
    return ClientFactory(config).create(build_agent_card("http://rally"))


async def close_official_client(client):
    """Close the SDK client and let sse-starlette's loop watcher exit cleanly."""
    await client.close()
    AppStatus.should_exit = True
    await asyncio.sleep(0.55)
    AppStatus.should_exit = False


@pytest.mark.asyncio
async def test_agent_card_is_public_precise_and_cacheable(a2a_service):
    async with httpx.AsyncClient(transport=a2a_service, base_url="http://rally") as client:
        response = await client.get("/.well-known/agent-card.json")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=300"
    card = response.json()
    assert card["version"] == "1.0.0"
    assert [interface["protocolBinding"] for interface in card["supportedInterfaces"]] == [
        "JSONRPC",
        "HTTP+JSON",
    ]
    assert card["capabilities"] == {
        "streaming": True,
        "pushNotifications": False,
        "extendedAgentCard": False,
    }
    assert set(card["securityRequirements"][0]["schemes"]) == {
        "google_cloud_identity",
        "rally_service_token",
    }
    assert [skill["id"] for skill in card["skills"]] == ["commission_governed_run"]
    assert "test-token" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,payload",
    [
        (
            "/",
            {"jsonrpc": "2.0", "id": "root", "method": "tasks/list", "params": {}},
        ),
        (
            "/a2a",
            {"jsonrpc": "2.0", "id": "1", "method": "tasks/list", "params": {}},
        ),
        (
            "/a2a/rest/message:send",
            {
                "message": {
                    "messageId": "msg-auth",
                    "role": "ROLE_USER",
                    "parts": [{"text": "Ship it"}],
                }
            },
        ),
    ],
)
async def test_a2a_work_routes_require_rally_service_auth(a2a_service, path, payload):
    async with httpx.AsyncClient(transport=a2a_service, base_url="http://rally") as client:
        response = await client.post(path, json=payload, headers={"A2A-Version": "1.0"})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "RallyServiceToken"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,expected_status,expected_code",
    [("/", 200, -32005), ("/a2a/rest/message:send", 415, 415)],
)
async def test_a2a_rejects_unsupported_http_content_type(
    a2a_service, path, expected_status, expected_code
):
    async with httpx.AsyncClient(transport=a2a_service, base_url="http://rally") as client:
        response = await client.post(
            path,
            content="not-json",
            headers={
                "A2A-Version": "1.0",
                "Content-Type": "text/plain",
                "X-Rally-Service-Token": "test-token",
            },
        )

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "protocol", [TransportProtocol.JSONRPC, TransportProtocol.HTTP_JSON]
)
async def test_official_a2a_client_can_stream_poll_and_list(a2a_service, protocol):
    client = await official_client(a2a_service, protocol)
    objective = "Repair webhook replay risk and independently verify it."
    try:
        events = [event async for event in client.send_message(a2a_message(objective))]
        assert [event.WhichOneof("payload") for event in events] == [
            "task",
            "status_update",
            "artifact_update",
            "status_update",
        ]
        task_id = events[0].task.id
        receipt = json.loads(events[2].artifact_update.artifact.parts[0].text)
        assert receipt["accepted"] is True
        assert receipt["status"] == "ready_for_rally"
        assert receipt["verification_invariant"] == "owner != verified_by"
        assert objective not in json.dumps(receipt)

        stored = await client.get_task(GetTaskRequest(id=task_id))
        assert stored.status.state == TaskState.TASK_STATE_COMPLETED
        assert len(stored.artifacts) == 1
        listed = await client.list_tasks(ListTasksRequest(include_artifacts=True))
        assert task_id in {task.id for task in listed.tasks}
    finally:
        await close_official_client(client)


@pytest.mark.asyncio
async def test_a2a_duplicate_message_reuses_the_rally_run(a2a_service):
    message_id = f"msg-{uuid.uuid4().hex}"
    client = await official_client(a2a_service, TransportProtocol.JSONRPC)
    try:
        first = [
            event async for event in client.send_message(a2a_message("Ship it", message_id))
        ]
        second = [
            event async for event in client.send_message(a2a_message("Ship it", message_id))
        ]
    finally:
        await close_official_client(client)

    first_receipt = json.loads(first[2].artifact_update.artifact.parts[0].text)
    second_receipt = json.loads(second[2].artifact_update.artifact.parts[0].text)
    assert first_receipt["rally_run_id"] == second_receipt["rally_run_id"]
    assert first_receipt["duplicate"] is False
    assert second_receipt["duplicate"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("objective", ["", "x" * (MAX_TASK_CHARS + 1)])
async def test_a2a_rejects_empty_and_oversized_objectives(a2a_service, objective):
    client = await official_client(a2a_service, TransportProtocol.HTTP_JSON)
    try:
        events = [event async for event in client.send_message(a2a_message(objective))]
    finally:
        await close_official_client(client)

    assert events[-1].status_update.status.state == TaskState.TASK_STATE_REJECTED
    assert service.store.records == {}


@pytest.mark.asyncio
async def test_a2a_conflicting_replay_fails_closed(a2a_service):
    message_id = f"msg-{uuid.uuid4().hex}"
    client = await official_client(a2a_service, TransportProtocol.JSONRPC)
    try:
        _ = [
            event async for event in client.send_message(a2a_message("Ship it", message_id))
        ]
        conflict = [
            event
            async for event in client.send_message(a2a_message("Delete it", message_id))
        ]
    finally:
        await close_official_client(client)

    assert conflict[-1].status_update.status.state == TaskState.TASK_STATE_FAILED
    assert len(service.store.records) == 1


def test_tck_fixture_mode_is_absent_from_production_configuration():
    for path in (
        ROOT / "cloud" / "Dockerfile",
        ROOT / "cloud" / "infra" / "main.tf",
        ROOT / "cloud" / "infra" / "variables.tf",
    ):
        assert "RALLY_A2A_TCK_MODE" not in path.read_text()
