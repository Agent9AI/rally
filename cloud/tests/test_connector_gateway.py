import json

import pytest

from connector_gateway import ConnectorGatewayError, call_allowed_tool


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
