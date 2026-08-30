import json
from contextlib import asynccontextmanager

import pytest

import connector_approvals
import connector_gateway
from connector_gateway import MAX_ARGUMENT_BYTES, ConnectorGatewayError, call_allowed_tool


@pytest.mark.asyncio
async def test_denied_tool_never_reaches_remote_and_writes_content_free_receipt(tmp_path):
    receipt_path = tmp_path / "receipts.jsonl"
    authority = {
        "schema_version": "rally.connector-authority/v1",
        "run_id": "r-test",
        "default_decision": "deny",
        "receipt_path": str(receipt_path),
        "connectors": [{
            "id": "bigquery",
            "name": "BigQuery",
            "endpoint": "https://should-not-be-called.invalid/mcp",
            "tool_policy": {},
        }],
    }
    with pytest.raises(ConnectorGatewayError, match="not on this run's tool allowlist"):
        await call_allowed_tool(authority, "bigquery", "delete_dataset", {"secret": "value"})
    receipt = json.loads(receipt_path.read_text())
    assert receipt["decision"] == "denied"
    assert receipt["reason"] == "not_allowlisted"
    assert receipt["tool"] == "delete_dataset"
    assert "secret" not in receipt_path.read_text()
    assert "value" not in receipt_path.read_text()


@pytest.mark.asyncio
async def test_oversized_arguments_are_denied_before_remote_connection(tmp_path):
    receipt_path = tmp_path / "receipts.jsonl"
    authority = {
        "schema_version": "rally.connector-authority/v1",
        "run_id": "r-test",
        "default_decision": "deny",
        "receipt_path": str(receipt_path),
        "connectors": [{
            "id": "bigquery",
            "name": "BigQuery",
            "endpoint": "https://should-not-be-called.invalid/mcp",
            "tool_policy": {"execute_sql": {"risk": "read"}},
        }],
    }
    with pytest.raises(ConnectorGatewayError, match="arguments violate"):
        await call_allowed_tool(
            authority, "bigquery", "execute_sql", {"query": "x" * MAX_ARGUMENT_BYTES}
        )
    receipt = json.loads(receipt_path.read_text())
    assert receipt["decision"] == "denied"
    assert receipt["reason"] == "arguments_too_large"
    assert "xxxxx" not in receipt_path.read_text()


@pytest.mark.asyncio
async def test_argument_allowlist_is_enforced_before_remote_connection(tmp_path):
    receipt_path = tmp_path / "receipts.jsonl"
    authority = {
        "schema_version": "rally.connector-authority/v1",
        "run_id": "r-test",
        "default_decision": "deny",
        "receipt_path": str(receipt_path),
        "connectors": [{
            "id": "n8n",
            "name": "n8n",
            "endpoint": "https://should-not-be-called.invalid/mcp",
            "tool_policy": {"execute_workflow": {
                "risk": "read",
                "constraints": {"arguments": {"workflowId": {
                    "required": True,
                    "allowed_values": ["wf-approved"],
                }}},
            }},
        }],
    }
    with pytest.raises(ConnectorGatewayError, match="argument_outside_allowlist"):
        await call_allowed_tool(
            authority, "n8n", "execute_workflow", {"workflowId": "wf-other"}
        )
    receipt = json.loads(receipt_path.read_text())
    assert receipt["decision"] == "denied"
    assert receipt["reason"] == "argument_outside_allowlist"


@pytest.mark.asyncio
async def test_human_approval_is_exact_single_use_and_precedes_remote_call(
    tmp_path, monkeypatch
):
    receipt_path = tmp_path / "receipts.jsonl"
    approval_path = tmp_path / "approvals.json"
    authority = {
        "schema_version": "rally.connector-authority/v1",
        "run_id": "r-test",
        "default_decision": "deny",
        "receipt_path": str(receipt_path),
        "approval_path": str(approval_path),
        "policy": {"human_approval_tools_enabled": True},
        "connectors": [{
            "id": "n8n",
            "name": "n8n",
            "endpoint": "https://tenant.app.n8n.cloud/mcp-server/http",
            "tool_policy": {"execute_workflow": {
                "risk": "human_approval",
                "constraints": {"arguments": {"workflowId": {
                    "required": True,
                    "allowed_values": ["wf-approved"],
                }}},
            }},
        }],
    }
    calls = []

    class Result:
        isError = False

        def model_dump(self, **_):
            return {"content": [{"type": "text", "text": "started"}]}

    class Session:
        async def call_tool(self, tool_name, arguments):
            calls.append((tool_name, arguments))
            return Result()

    @asynccontextmanager
    async def fake_remote_session(_connector):
        yield Session()

    monkeypatch.setattr(connector_gateway, "remote_session", fake_remote_session)
    arguments = {"workflowId": "wf-approved"}

    with pytest.raises(ConnectorGatewayError, match="requires human approval"):
        await call_allowed_tool(
            authority, "n8n", "execute_workflow", arguments
        )
    assert calls == []
    pending = connector_approvals.list_public(approval_path, status="pending")
    assert len(pending) == 1
    approval_id = pending[0]["approval_id"]
    connector_approvals.approve(
        approval_path, approval_id, human_identity="human-operator"
    )

    result = await call_allowed_tool(
        authority,
        "n8n",
        "execute_workflow",
        arguments,
        approval_id,
    )
    assert result["content"][0]["text"] == "started"
    assert calls == [("execute_workflow", arguments)]

    with pytest.raises(ConnectorGatewayError, match="approval was refused"):
        await call_allowed_tool(
            authority,
            "n8n",
            "execute_workflow",
            arguments,
            approval_id,
        )
    assert calls == [("execute_workflow", arguments)]
    receipt_text = receipt_path.read_text()
    assert "wf-approved" not in receipt_text
    assert '"decision": "pending_approval"' in receipt_text
    assert '"decision": "allowed"' in receipt_text


@pytest.mark.asyncio
async def test_bundled_provider_dispatch_strips_only_the_pinned_service_prefix(
    tmp_path, monkeypatch
):
    receipt_path = tmp_path / "receipts.jsonl"
    authority = {
        "schema_version": "rally.connector-authority/v1",
        "run_id": "r-test",
        "default_decision": "deny",
        "receipt_path": str(receipt_path),
        "connectors": [{
            "id": "google-workspace",
            "name": "Google Workspace",
            "endpoint": "",
            "dispatch": {
                "strategy": "tool_prefix",
                "separator": ".",
                "services": {
                    "gmail": "https://gmailmcp.googleapis.com/mcp/v1",
                    "drive": "https://drivemcp.googleapis.com/mcp/v1",
                },
            },
            "tool_policy": {"gmail.search_threads": {"risk": "read"}},
        }],
    }
    calls = []

    class Result:
        isError = False

        def model_dump(self, **_):
            return {"content": []}

    class Session:
        async def call_tool(self, tool_name, arguments):
            calls.append((tool_name, arguments))
            return Result()

    @asynccontextmanager
    async def fake_remote_session(connector):
        calls.append(("endpoint", connector["endpoint"]))
        yield Session()

    monkeypatch.setattr(connector_gateway, "remote_session", fake_remote_session)
    await call_allowed_tool(
        authority,
        "google-workspace",
        "gmail.search_threads",
        {"query": "launch"},
    )
    assert calls == [
        ("endpoint", "https://gmailmcp.googleapis.com/mcp/v1"),
        ("search_threads", {"query": "launch"}),
    ]

    with pytest.raises(ConnectorGatewayError, match="not on this run's tool allowlist"):
        await call_allowed_tool(
            authority,
            "google-workspace",
            "drive.search_threads",
            {"query": "launch"},
        )
    assert len(calls) == 2
