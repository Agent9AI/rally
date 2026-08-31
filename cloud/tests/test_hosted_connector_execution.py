import asyncio
import base64
import datetime as dt
import json
from contextlib import asynccontextmanager
from urllib.parse import parse_qs

import httpx
import pytest
from mcp.types import ListToolsResult, Tool

import control_plane
import hosted_connector_execution
from credential_vault import (
    ConnectorSecret,
    MemoryConnectorVault,
    certified_manifest_sha256,
)
from hosted_connector_execution import (
    FirestoreExecutionReceiptStore,
    HostedCallResult,
    HostedConnectorExecutor,
    HostedExecutionError,
    HostedMcpCaller,
    HostedOAuthRefresher,
    MemoryExecutionReceiptStore,
)
from hosted_connectors import HostedConnectorError, connector, make_oauth_material, pack_secret
from hosted_mcp_transport import MAX_HOSTED_MCP_RESPONSE_BYTES, CappedAsyncTransport
from user_auth import UserIdentity


def certification(tool_name="get_me", schema_sha256="a" * 64):
    manifest = ((tool_name, schema_sha256),)
    return {
        "status": "ready",
        "tool_count": 1,
        "canary_tool": tool_name,
        "tool_schema_sha256": schema_sha256,
        "proof_version": "rally.connection-certification/v1",
        "certified_tools": manifest,
        "certified_manifest_sha256": certified_manifest_sha256(manifest),
    }


CERTIFICATION = certification()


class FakeCaller:
    def __init__(self, payload=None, *, is_error=False, errors=()):
        self.payload = payload or {"content": [{"type": "text", "text": "private provider result"}]}
        self.is_error = is_error
        self.errors = list(errors)
        self.calls = []

    async def call(self, **kwargs):
        self.calls.append(kwargs)
        if self.errors:
            raise HostedExecutionError(self.errors.pop(0))
        return HostedCallResult(payload=self.payload, is_error=self.is_error)


class FakeRefresher:
    def __init__(self, value=None, *, error=None):
        self.value = value
        self.error = error
        self.calls = []

    async def refresh(self, item, stored_value):
        self.calls.append((item.id, stored_value))
        if self.error:
            raise HostedExecutionError(self.error)
        return self.value


class BlockingCaller:
    def __init__(self):
        self.started = asyncio.Event()

    async def call(self, **kwargs):
        del kwargs
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class ConcurrentReconnectVault(MemoryConnectorVault):
    async def quarantine(
        self,
        uid,
        connector_id,
        *,
        expected_generation,
        expected_lease,
        expected,
        error_code,
    ):
        await self.delete(
            uid,
            connector_id,
            expected_generation=expected_generation,
        )
        replacement = ConnectorSecret(
            pack_secret(
                credential="newly-reconnected-secret",
                endpoint="https://api.githubcopilot.com/mcp",
            ),
            "bearer_token",
        )
        await self.put(uid, connector_id, replacement)
        await self.mark(uid, connector_id, **CERTIFICATION)
        return await super().quarantine(
            uid,
            connector_id,
            expected_generation=expected_generation,
            expected_lease=expected_lease,
            expected=expected,
            error_code=error_code,
        )


@pytest.mark.asyncio
async def test_mcp_transport_maps_authenticated_401_without_provider_details(monkeypatch):
    @asynccontextmanager
    async def unauthorized_stream(*args, **kwargs):
        del args, kwargs
        request = httpx.Request("POST", "https://mcp.stripe.com")
        response = httpx.Response(401, request=request, text="private provider diagnostic")
        raise httpx.HTTPStatusError(
            "private provider diagnostic", request=request, response=response
        )
        yield  # pragma: no cover

    monkeypatch.setattr(
        hosted_connector_execution,
        "streamable_http_client",
        unauthorized_stream,
    )

    with pytest.raises(HostedExecutionError) as denied:
        await HostedMcpCaller().call(
            endpoint="https://mcp.stripe.com",
            headers={"Authorization": "Bearer private-access-token"},
            tool_name="get_stripe_account_info",
            arguments={},
            expected_schema_sha256="a" * 64,
        )

    assert denied.value.code == "provider_authentication_failed"
    assert "private" not in repr(denied.value)


async def ready_connection(
    vault,
    uid,
    connector_id="github",
    *,
    credential="tenant-one-secret",
    endpoint="https://api.githubcopilot.com/mcp",
    workflow_ids=(),
):
    material = pack_secret(
        credential=credential,
        endpoint=endpoint,
        allowed_workflow_ids=workflow_ids,
    )
    await vault.put(uid, connector_id, ConnectorSecret(material, "bearer_token"))
    canary = "get_me"
    if connector_id == "n8n":
        canary = "get_workflow_details"
    elif connector_id == "stripe":
        canary = "get_stripe_account_info"
    await vault.mark(uid, connector_id, **certification(canary))


def final_receipt(receipts, uid):
    owner_hash = __import__("hashlib").sha256(uid.encode()).hexdigest()
    matching = [value for (owner, _), value in receipts.items.items() if owner == owner_hash]
    assert len(matching) == 1
    return matching[0]


@pytest.mark.asyncio
async def test_exact_tenant_secret_drives_only_allowlisted_read_and_receipt_is_content_free():
    vault = MemoryConnectorVault()
    receipts = MemoryExecutionReceiptStore()
    caller = FakeCaller()
    await ready_connection(vault, "tenant-one")

    completed = await HostedConnectorExecutor(vault, receipts, caller).execute(
        uid="tenant-one",
        connector_id="github",
        tool_name="get_me",
        arguments={},
    )

    assert caller.calls == [
        {
            "endpoint": "https://api.githubcopilot.com/mcp",
            "headers": {
                "Authorization": "Bearer tenant-one-secret",
                "X-MCP-Toolsets": "context,repos,issues,pull_requests,users",
                "X-MCP-Readonly": "true",
                "X-MCP-Lockdown": "true",
            },
            "tool_name": "get_me",
            "arguments": {},
            "expected_schema_sha256": "a" * 64,
        }
    ]
    assert completed.payload == caller.payload
    receipt = final_receipt(receipts, "tenant-one")
    assert receipt["decision"] == "allowed"
    assert receipt["argument_bytes"] == 2
    assert len(receipt["arguments_sha256"]) == 64
    assert len(receipt["result_sha256"]) == 64
    assert len(receipt["credential_generation"]) == 32
    assert len(receipt["certified_manifest_sha256"]) == 64
    assert len(receipt["policy_sha256"]) == 64
    encoded_receipt = json.dumps(receipt)
    assert "tenant-one" not in encoded_receipt
    assert "tenant-one-secret" not in encoded_receipt
    assert "private provider result" not in encoded_receipt
    assert "arguments" not in receipt
    assert "result" not in receipt


@pytest.mark.asyncio
async def test_total_execution_deadline_returns_a_receipt_and_releases_the_lease():
    vault = MemoryConnectorVault()
    receipts = MemoryExecutionReceiptStore()
    caller = BlockingCaller()
    await ready_connection(vault, "tenant-one")

    with pytest.raises(HostedExecutionError) as timed_out:
        await HostedConnectorExecutor(
            vault,
            receipts,
            caller,
            execution_deadline_seconds=0.02,
            cleanup_timeout_seconds=0.2,
        ).execute(
            uid="tenant-one",
            connector_id="github",
            tool_name="get_me",
            arguments={},
        )

    assert timed_out.value.code == "execution_timeout"
    assert timed_out.value.receipt is not None
    assert timed_out.value.receipt.decision == "failed"
    assert timed_out.value.receipt.error_code == "execution_timeout"
    connection = await vault.get_connection("tenant-one", "github")
    assert connection is not None
    assert connection.record.execution_lease is None

    recovered = await HostedConnectorExecutor(
        vault,
        MemoryExecutionReceiptStore(),
        FakeCaller(),
    ).execute(
        uid="tenant-one",
        connector_id="github",
        tool_name="get_me",
        arguments={},
    )
    assert recovered.receipt.decision == "allowed"


@pytest.mark.asyncio
async def test_cancellation_waits_for_lease_release_before_propagating():
    vault = MemoryConnectorVault()
    receipts = MemoryExecutionReceiptStore()
    caller = BlockingCaller()
    await ready_connection(vault, "tenant-one")
    task = asyncio.create_task(
        HostedConnectorExecutor(
            vault,
            receipts,
            caller,
            execution_deadline_seconds=1,
            cleanup_timeout_seconds=0.2,
        ).execute(
            uid="tenant-one",
            connector_id="github",
            tool_name="get_me",
            arguments={},
        )
    )
    await asyncio.wait_for(caller.started.wait(), timeout=0.5)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    connection = await vault.get_connection("tenant-one", "github")
    assert connection is not None
    assert connection.record.execution_lease is None
    assert len(receipts.items) == 1
    cancelled_receipt = next(iter(receipts.items.values()))
    assert cancelled_receipt["decision"] == "failed"
    assert cancelled_receipt["error_code"] == "execution_cancelled"
    assert cancelled_receipt["completed_at"]
    recovered = await HostedConnectorExecutor(
        vault,
        MemoryExecutionReceiptStore(),
        FakeCaller(),
    ).execute(
        uid="tenant-one",
        connector_id="github",
        tool_name="get_me",
        arguments={},
    )
    assert recovered.receipt.decision == "allowed"


@pytest.mark.asyncio
async def test_cross_tenant_lookup_never_calls_provider_or_reveals_connection():
    vault = MemoryConnectorVault()
    receipts = MemoryExecutionReceiptStore()
    caller = FakeCaller()
    await ready_connection(vault, "tenant-one")

    with pytest.raises(HostedExecutionError) as denied:
        await HostedConnectorExecutor(vault, receipts, caller).execute(
            uid="tenant-two",
            connector_id="github",
            tool_name="get_me",
            arguments={},
        )

    assert denied.value.code == "connection_not_found"
    assert caller.calls == []
    receipt = final_receipt(receipts, "tenant-two")
    assert receipt["decision"] == "denied"
    assert receipt["error_code"] == "connection_not_found"


@pytest.mark.asyncio
async def test_preset_tool_added_after_certification_cannot_be_invoked():
    vault = MemoryConnectorVault()
    receipts = MemoryExecutionReceiptStore()
    caller = FakeCaller()
    await ready_connection(vault, "tenant-one")

    with pytest.raises(HostedExecutionError) as denied:
        await HostedConnectorExecutor(vault, receipts, caller).execute(
            uid="tenant-one",
            connector_id="github",
            tool_name="search_repositories",
            arguments={"query": "rally"},
        )

    assert denied.value.code == "tool_not_certified"
    assert caller.calls == []


@pytest.mark.asyncio
async def test_mcp_caller_rejects_schema_drift_before_tool_dispatch(monkeypatch):
    captured_client_kwargs = []

    class FakeHttpClient:
        def __init__(self, **kwargs):
            captured_client_kwargs.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class DriftSession:
        called = False

        def __init__(self, *args):
            del args

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def initialize(self):
            return None

        async def list_tools(self, cursor=None):
            assert cursor is None
            return ListToolsResult(
                tools=[
                    Tool(
                        name="get_me",
                        description="Changed provider contract",
                        inputSchema={"type": "object", "properties": {"new": {"type": "string"}}},
                    )
                ]
            )

        async def call_tool(self, *args, **kwargs):
            self.called = True
            raise AssertionError("schema drift must fail before dispatch")

    @asynccontextmanager
    async def fake_stream(*args, **kwargs):
        del args, kwargs
        yield None, None, None

    monkeypatch.setattr(hosted_connector_execution.httpx, "AsyncClient", FakeHttpClient)
    monkeypatch.setattr(hosted_connector_execution, "streamable_http_client", fake_stream)
    monkeypatch.setattr(hosted_connector_execution, "ClientSession", DriftSession)

    with pytest.raises(HostedExecutionError) as denied:
        await HostedMcpCaller().call(
            endpoint="https://api.githubcopilot.com/mcp",
            headers={},
            tool_name="get_me",
            arguments={},
            expected_schema_sha256="a" * 64,
        )

    assert denied.value.code == "tool_schema_changed"
    assert len(captured_client_kwargs) == 1
    transport = captured_client_kwargs[0]["transport"]
    assert isinstance(transport, CappedAsyncTransport)
    assert transport.maximum_bytes == MAX_HOSTED_MCP_RESPONSE_BYTES


@pytest.mark.asyncio
async def test_non_read_n8n_tool_and_unapproved_workflow_are_denied_before_provider():
    vault = MemoryConnectorVault()
    receipts = MemoryExecutionReceiptStore()
    caller = FakeCaller()
    endpoint = "https://company.app.n8n.cloud/mcp-server/http"
    await ready_connection(
        vault,
        "tenant-one",
        "n8n",
        endpoint=endpoint,
        workflow_ids=("approved-workflow",),
    )
    executor = HostedConnectorExecutor(vault, receipts, caller)

    with pytest.raises(HostedExecutionError) as write_denied:
        await executor.execute(
            uid="tenant-one",
            connector_id="n8n",
            tool_name="execute_workflow",
            arguments={
                "workflowId": "approved-workflow",
                "executionMode": "production",
            },
        )
    with pytest.raises(HostedExecutionError) as scope_denied:
        await executor.execute(
            uid="tenant-one",
            connector_id="n8n",
            tool_name="get_workflow_details",
            arguments={"workflowId": "other-workflow", "detailLevel": "execution"},
        )

    assert write_denied.value.code == "human_approval_required"
    assert scope_denied.value.code == "argument_not_allowed"
    assert caller.calls == []


@pytest.mark.asyncio
async def test_argument_and_result_caps_are_enforced_on_both_sides_of_call():
    vault = MemoryConnectorVault()
    receipts = MemoryExecutionReceiptStore()
    await ready_connection(
        vault,
        "tenant-one",
        "stripe",
        credential="stripe-secret",
        endpoint="https://mcp.stripe.com",
    )
    caller = FakeCaller({"content": [{"type": "text", "text": "z" * (70 * 1024)}]})
    executor = HostedConnectorExecutor(vault, receipts, caller)

    with pytest.raises(HostedExecutionError) as arguments_denied:
        await executor.execute(
            uid="tenant-one",
            connector_id="stripe",
            tool_name="get_stripe_account_info",
            arguments={"padding": "x" * (65 * 1024)},
        )
    with pytest.raises(HostedExecutionError) as result_denied:
        await executor.execute(
            uid="tenant-one",
            connector_id="stripe",
            tool_name="get_stripe_account_info",
            arguments={},
        )

    assert arguments_denied.value.code == "arguments_too_large"
    assert result_denied.value.code == "result_too_large"
    assert len(caller.calls) == 1
    assert result_denied.value.receipt.result_bytes > 64 * 1024
    assert "z" * 100 not in json.dumps(result_denied.value.receipt.public())


@pytest.mark.asyncio
async def test_provider_cannot_reflect_any_vault_secret_in_response():
    vault = MemoryConnectorVault()
    receipts = MemoryExecutionReceiptStore()
    await ready_connection(vault, "tenant-one", credential="reflection-secret")
    caller = FakeCaller({"content": [{"type": "text", "text": "token=reflection-secret"}]})

    with pytest.raises(HostedExecutionError) as denied:
        await HostedConnectorExecutor(vault, receipts, caller).execute(
            uid="tenant-one",
            connector_id="github",
            tool_name="get_me",
            arguments={},
        )

    assert denied.value.code == "secret_detected"
    assert "reflection-secret" not in json.dumps(denied.value.receipt.public())


@pytest.mark.asyncio
async def test_expired_oauth_refresh_rotates_sealed_material_before_provider_call():
    vault = MemoryConnectorVault()
    receipts = MemoryExecutionReceiptStore()
    caller = FakeCaller()
    material = make_oauth_material(
        endpoint="https://mcp.stripe.com",
        access_token="expired-access-token",
        refresh_token="refresh-token",
        token_type="Bearer",
        expires_in=60,
        scope="mcp",
        client_id="client-id",
        client_secret="client-secret",
        token_endpoint="https://access.stripe.com/oauth/token",
        revocation_endpoint=None,
        token_auth_method="client_secret_post",
    )
    await vault.put(
        "tenant-one",
        "stripe",
        ConnectorSecret(material, "oauth_refresh_token"),
    )
    await vault.mark("tenant-one", "stripe", **certification("get_stripe_account_info"))
    original_generation = (await vault.list("tenant-one"))[0].credential_generation

    refreshed = json.loads(material)
    refreshed.update(
        {
            "access_token": "rotated-access-token",
            "refresh_token": "rotated-refresh-token",
            "expires_in": 3600,
            "obtained_at": (dt.datetime.now(dt.UTC) + dt.timedelta(minutes=2)).isoformat(),
        }
    )
    refreshed_value = json.dumps(refreshed, separators=(",", ":"))
    refresher = FakeRefresher(refreshed_value)

    result = await HostedConnectorExecutor(
        vault,
        receipts,
        caller,
        refresher,
        clock=lambda: dt.datetime.now(dt.UTC) + dt.timedelta(minutes=2),
    ).execute(
        uid="tenant-one",
        connector_id="stripe",
        tool_name="get_stripe_account_info",
        arguments={},
    )

    assert result.receipt.decision == "allowed"
    assert refresher.calls == [("stripe", material)]
    assert caller.calls[0]["headers"]["Authorization"] == "Bearer rotated-access-token"
    rotated = await vault.get_secret("tenant-one", "stripe")
    assert rotated is not None
    assert json.loads(rotated.value)["refresh_token"] == "rotated-refresh-token"
    record = (await vault.list("tenant-one"))[0]
    assert record.credential_generation != original_generation
    assert result.receipt.credential_generation == record.credential_generation
    assert record.status == "ready"
    assert record.proof_version == "rally.connection-certification/v1"


@pytest.mark.asyncio
async def test_refresh_failure_retains_prior_sealed_material_and_never_calls_provider():
    vault = MemoryConnectorVault()
    receipts = MemoryExecutionReceiptStore()
    caller = FakeCaller()
    material = make_oauth_material(
        endpoint="https://mcp.stripe.com",
        access_token="expired-access-token",
        refresh_token="refresh-token",
        token_type="Bearer",
        expires_in=60,
        scope="mcp",
        client_id="client-id",
        client_secret="client-secret",
        token_endpoint="https://access.stripe.com/oauth/token",
        revocation_endpoint=None,
        token_auth_method="client_secret_post",
    )
    original = ConnectorSecret(material, "oauth_refresh_token")
    await vault.put("tenant-one", "stripe", original)
    await vault.mark("tenant-one", "stripe", **certification("get_stripe_account_info"))
    refresher = FakeRefresher(error="credential_refresh_failed")

    with pytest.raises(HostedExecutionError) as failed:
        await HostedConnectorExecutor(
            vault,
            receipts,
            caller,
            refresher,
            clock=lambda: dt.datetime.now(dt.UTC) + dt.timedelta(minutes=2),
        ).execute(
            uid="tenant-one",
            connector_id="stripe",
            tool_name="get_stripe_account_info",
            arguments={},
        )

    assert failed.value.code == "reconnect_required"
    assert await vault.get_secret("tenant-one", "stripe") == original
    assert caller.calls == []
    assert failed.value.receipt.error_code == "reconnect_required"
    record = (await vault.list("tenant-one"))[0]
    assert record.status == "needs_attention"
    assert record.error_code == "reconnect_required"
    assert record.proof_version is None
    assert record.canary_tool is None
    assert record.tool_schema_sha256 is None
    projected = control_plane.public_connection(record)
    assert projected["verified"] is False
    assert projected["certification"] is None


@pytest.mark.asyncio
async def test_authenticated_401_refreshes_once_rotates_then_retries_same_read():
    vault = MemoryConnectorVault()
    receipts = MemoryExecutionReceiptStore()
    caller = FakeCaller(errors=("provider_authentication_failed",))
    material = make_oauth_material(
        endpoint="https://mcp.stripe.com",
        access_token="apparently-current-access",
        refresh_token="durable-refresh-token",
        token_type="Bearer",
        expires_in=3600,
        scope="mcp",
        client_id="client-id",
        client_secret="client-secret",
        token_endpoint="https://access.stripe.com/oauth/token",
        revocation_endpoint=None,
        token_auth_method="client_secret_post",
    )
    await vault.put(
        "tenant-one",
        "stripe",
        ConnectorSecret(material, "oauth_refresh_token"),
    )
    await vault.mark("tenant-one", "stripe", **certification("get_stripe_account_info"))
    refreshed = json.loads(material)
    refreshed.update(
        {
            "access_token": "fresh-access-token",
            "refresh_token": "rotated-durable-refresh",
            "obtained_at": dt.datetime.now(dt.UTC).isoformat(),
        }
    )
    refresher = FakeRefresher(json.dumps(refreshed, separators=(",", ":")))

    result = await HostedConnectorExecutor(vault, receipts, caller, refresher).execute(
        uid="tenant-one",
        connector_id="stripe",
        tool_name="get_stripe_account_info",
        arguments={},
    )

    assert result.receipt.decision == "allowed"
    assert len(caller.calls) == 2
    assert caller.calls[0]["headers"]["Authorization"] == ("Bearer apparently-current-access")
    assert caller.calls[1]["headers"]["Authorization"] == "Bearer fresh-access-token"
    assert refresher.calls == [("stripe", material)]
    stored = await vault.get_secret("tenant-one", "stripe")
    assert stored is not None
    assert json.loads(stored.value)["refresh_token"] == "rotated-durable-refresh"
    assert (await vault.list("tenant-one"))[0].status == "ready"


@pytest.mark.asyncio
async def test_terminal_token_401_clears_certification_and_requires_reconnect():
    vault = MemoryConnectorVault()
    receipts = MemoryExecutionReceiptStore()
    caller = FakeCaller(errors=("provider_authentication_failed",))
    await ready_connection(vault, "tenant-one")

    with pytest.raises(HostedExecutionError) as denied:
        await HostedConnectorExecutor(vault, receipts, caller).execute(
            uid="tenant-one",
            connector_id="github",
            tool_name="get_me",
            arguments={},
        )

    assert denied.value.code == "reconnect_required"
    record = (await vault.list("tenant-one"))[0]
    assert record.status == "needs_attention"
    assert record.error_code == "reconnect_required"
    assert record.proof_version is None


@pytest.mark.asyncio
async def test_oauth_401_retries_only_once_then_clears_certification():
    vault = MemoryConnectorVault()
    receipts = MemoryExecutionReceiptStore()
    caller = FakeCaller(errors=("provider_authentication_failed", "provider_authentication_failed"))
    material = make_oauth_material(
        endpoint="https://mcp.stripe.com",
        access_token="apparently-current-access",
        refresh_token="durable-refresh-token",
        token_type="Bearer",
        expires_in=3600,
        scope="mcp",
        client_id="client-id",
        client_secret="client-secret",
        token_endpoint="https://access.stripe.com/oauth/token",
        revocation_endpoint=None,
        token_auth_method="client_secret_post",
    )
    await vault.put(
        "tenant-one",
        "stripe",
        ConnectorSecret(material, "oauth_refresh_token"),
    )
    await vault.mark("tenant-one", "stripe", **certification("get_stripe_account_info"))
    refreshed = json.loads(material)
    refreshed.update(
        {
            "access_token": "fresh-but-rejected-access",
            "obtained_at": dt.datetime.now(dt.UTC).isoformat(),
        }
    )
    refresher = FakeRefresher(json.dumps(refreshed, separators=(",", ":")))

    with pytest.raises(HostedExecutionError) as denied:
        await HostedConnectorExecutor(vault, receipts, caller, refresher).execute(
            uid="tenant-one",
            connector_id="stripe",
            tool_name="get_stripe_account_info",
            arguments={},
        )

    assert denied.value.code == "reconnect_required"
    assert len(caller.calls) == 2
    assert len(refresher.calls) == 1
    record = (await vault.list("tenant-one"))[0]
    assert record.status == "needs_attention"
    assert record.proof_version is None


@pytest.mark.asyncio
async def test_needs_attention_connection_cannot_invoke_even_with_sealed_credential():
    vault = MemoryConnectorVault()
    receipts = MemoryExecutionReceiptStore()
    caller = FakeCaller()
    await ready_connection(vault, "tenant-one")
    await vault.mark(
        "tenant-one",
        "github",
        status="needs_attention",
        error_code="reconnect_required",
    )

    with pytest.raises(HostedExecutionError) as denied:
        await HostedConnectorExecutor(vault, receipts, caller).execute(
            uid="tenant-one",
            connector_id="github",
            tool_name="get_me",
            arguments={},
        )

    assert denied.value.code == "connection_not_ready"
    assert caller.calls == []


@pytest.mark.asyncio
async def test_terminal_failure_cannot_quarantine_a_concurrent_reconnect():
    vault = ConcurrentReconnectVault()
    receipts = MemoryExecutionReceiptStore()
    caller = FakeCaller(errors=("provider_authentication_failed",))
    await ready_connection(vault, "tenant-one")

    with pytest.raises(HostedExecutionError) as conflicted:
        await HostedConnectorExecutor(vault, receipts, caller).execute(
            uid="tenant-one",
            connector_id="github",
            tool_name="get_me",
            arguments={},
        )

    assert conflicted.value.code == "credential_refresh_conflict"
    current = await vault.get_secret("tenant-one", "github")
    assert current is not None
    assert "newly-reconnected-secret" in current.value
    record = (await vault.list("tenant-one"))[0]
    assert record.status == "ready"
    assert record.proof_version == "rally.connection-certification/v1"


@pytest.mark.asyncio
async def test_refresh_exchange_is_provider_pinned_bounded_and_uses_stored_client_auth():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "access_token": "new-access-token",
                "refresh_token": "new-refresh-token",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "mcp",
            },
        )

    material = make_oauth_material(
        endpoint="https://hyperagent.com/api/mcp",
        access_token="old-access-token",
        refresh_token="old-refresh-token",
        token_type="Bearer",
        expires_in=60,
        scope="mcp additional-scope",
        client_id="client-id",
        client_secret="client-secret",
        token_endpoint="https://hyperagent.com/oauth/token",
        revocation_endpoint=None,
        token_auth_method="client_secret_basic",
        resource="https://hyperagent.com/api/mcp",
    )
    refresher = HostedOAuthRefresher(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    rotated = await refresher.refresh(connector("hyperagent"), material)

    assert len(seen) == 1
    request = seen[0]
    assert str(request.url) == "https://hyperagent.com/oauth/token"
    assert parse_qs(request.content.decode()) == {
        "grant_type": ["refresh_token"],
        "refresh_token": ["old-refresh-token"],
        "client_id": ["client-id"],
        "resource": ["https://hyperagent.com/api/mcp"],
    }
    scheme, encoded = request.headers["authorization"].split(" ", 1)
    assert scheme == "Basic"
    assert base64.b64decode(encoded).decode() == "client-id:client-secret"
    parsed = json.loads(rotated)
    assert parsed["access_token"] == "new-access-token"
    assert parsed["refresh_token"] == "new-refresh-token"
    assert parsed["scope"] == "mcp"
    assert "old-access-token" not in rotated


@pytest.mark.asyncio
async def test_google_refresh_with_no_resource_omits_rfc8707_parameter():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "access_token": "new-google-access",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )

    material = make_oauth_material(
        endpoint="https://people.googleapis.com/mcp/v1",
        access_token="old-google-access",
        refresh_token="old-google-refresh",
        token_type="Bearer",
        expires_in=60,
        scope="https://www.googleapis.com/auth/contacts.readonly",
        client_id="google-client",
        client_secret="google-client-secret",
        token_endpoint="https://oauth2.googleapis.com/token",
        revocation_endpoint="https://oauth2.googleapis.com/revoke",
        token_auth_method="client_secret_post",
        resource=None,
    )
    refresher = HostedOAuthRefresher(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    refreshed = await refresher.refresh(connector("google-workspace"), material)

    form = parse_qs(seen[0].content.decode())
    assert str(seen[0].url) == "https://oauth2.googleapis.com/token"
    assert "resource" not in form
    assert form["client_secret"] == ["google-client-secret"]
    assert json.loads(refreshed)["refresh_token"] == "old-google-refresh"


def test_sealed_oauth_material_rejects_untrusted_resource_uri():
    with pytest.raises(HostedConnectorError):
        make_oauth_material(
            endpoint="https://hyperagent.com/api/mcp",
            access_token="access-token",
            refresh_token="refresh-token",
            token_type="Bearer",
            expires_in=60,
            scope="mcp",
            client_id="client-id",
            client_secret=None,
            token_endpoint="https://hyperagent.com/oauth/token",
            revocation_endpoint=None,
            token_auth_method="none",
            resource="https://attacker.invalid/mcp",
        )


@pytest.mark.asyncio
async def test_refresh_rejects_unpinned_token_endpoint_before_network():
    calls = []
    material = json.loads(
        make_oauth_material(
            endpoint="https://mcp.stripe.com",
            access_token="old-access-token",
            refresh_token="old-refresh-token",
            token_type="Bearer",
            expires_in=60,
            scope="mcp",
            client_id="client-id",
            client_secret="client-secret",
            token_endpoint="https://access.stripe.com/oauth/token",
            revocation_endpoint=None,
            token_auth_method="client_secret_post",
        )
    )
    material["token_endpoint"] = "https://attacker.invalid/token"

    def client_factory():
        calls.append(True)
        return httpx.AsyncClient()

    with pytest.raises(HostedExecutionError) as denied:
        await HostedOAuthRefresher(client_factory=client_factory).refresh(
            connector("stripe"),
            json.dumps(material),
        )

    assert denied.value.code == "credential_refresh_failed"
    assert calls == []


class FakeDocument:
    def __init__(self):
        self.value = None

    async def set(self, value):
        self.value = value


class FakeCollection:
    def __init__(self):
        self.documents = {}

    def document(self, key):
        return self.documents.setdefault(key, FakeDocument())


class FakeFirestore:
    def __init__(self):
        self.receipts = FakeCollection()

    def collection(self, name):
        assert name == "connector_execution_receipts"
        return self.receipts


@pytest.mark.asyncio
async def test_firestore_receipt_contains_owner_hash_but_no_uid_or_content():
    fake = FakeFirestore()
    store = FirestoreExecutionReceiptStore("project", client=fake)
    vault = MemoryConnectorVault()
    caller = FakeCaller()
    await ready_connection(vault, "private-tenant")

    await HostedConnectorExecutor(vault, store, caller).execute(
        uid="private-tenant",
        connector_id="github",
        tool_name="get_me",
        arguments={},
    )

    stored = next(iter(fake.receipts.documents.values())).value
    assert stored["owner_hash"] != "private-tenant"
    assert len(stored["owner_hash"]) == 64
    assert "uid" not in stored
    assert "arguments" not in stored
    assert "result" not in stored
    assert isinstance(stored["expires_at"], dt.datetime)
    assert "private provider result" not in json.dumps(stored, default=str)


@pytest.mark.asyncio
async def test_control_plane_endpoint_is_authenticated_bounded_and_content_safe():
    vault = MemoryConnectorVault()
    receipts = MemoryExecutionReceiptStore()
    caller = FakeCaller()
    await ready_connection(vault, "google-user-one")
    identity = UserIdentity(uid="google-user-one", email="owner@example.com", name="Owner")
    control_plane.app.dependency_overrides[control_plane.require_user] = lambda: identity
    control_plane.app.dependency_overrides[control_plane.get_vault] = lambda: vault
    control_plane.app.dependency_overrides[control_plane.get_execution_receipt_store] = lambda: (
        receipts
    )
    control_plane.app.dependency_overrides[control_plane.get_hosted_tool_caller] = lambda: caller
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=control_plane.app),
            base_url="http://rally",
        ) as client:
            invoked = await client.post(
                "/v1/connections/github/invoke",
                json={"tool_name": "get_me", "arguments": {}},
            )
            oversized = await client.post(
                "/v1/connections/github/invoke",
                content=json.dumps(
                    {"tool_name": "get_me", "arguments": {"padding": "x" * (73 * 1024)}}
                ),
                headers={"content-type": "application/json"},
            )
            timeout_caller = FakeCaller(errors=("execution_timeout",))
            control_plane.app.dependency_overrides[control_plane.get_hosted_tool_caller] = lambda: (
                timeout_caller
            )
            timed_out = await client.post(
                "/v1/connections/github/invoke",
                json={"tool_name": "get_me", "arguments": {}},
            )
    finally:
        control_plane.app.dependency_overrides.clear()

    assert invoked.status_code == 200
    assert invoked.json()["receipt"]["decision"] == "allowed"
    assert invoked.json()["result"] == caller.payload
    assert "tenant-one-secret" not in invoked.text
    assert oversized.status_code == 413
    assert oversized.json()["detail"] == "invocation request is too large"
    assert timed_out.status_code == 504
    assert timed_out.json()["detail"]["code"] == "execution_timeout"
    assert timed_out.json()["detail"]["receipt"]["decision"] == "failed"
