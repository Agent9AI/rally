import datetime as dt
from contextlib import asynccontextmanager

import pytest
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

import hosted_connectors
from hosted_connectors import HostedConnectorError, McpConnectionVerifier, connector
from hosted_mcp_transport import MAX_HOSTED_MCP_RESPONSE_BYTES, CappedAsyncTransport


class FakeSession:
    def __init__(self, tools, result=None):
        self.tools = tools
        self.result = result or CallToolResult(
            content=[TextContent(type="text", text="private provider content")]
        )
        self.calls = []

    async def list_tools(self, cursor=None):
        assert cursor is None
        return ListToolsResult(tools=self.tools)

    async def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments))
        return self.result


class FakeWorkspaceSession(FakeSession):
    def __init__(self, service, tool_name, canary_calls):
        super().__init__([tool(tool_name)])
        self.service = service
        self.canary_calls = canary_calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def initialize(self):
        return None

    async def call_tool(self, name, arguments=None):
        self.canary_calls.append((self.service, name, arguments))
        return await super().call_tool(name, arguments)


class FakeHttpClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def tool(name, schema=None):
    return Tool(
        name=name,
        description="Read-only certification tool",
        inputSchema=schema or {"type": "object", "properties": {}},
    )


def install_workspace_bundle_fakes(monkeypatch, *, broken_service=None):
    item = connector("google-workspace")
    endpoint_to_service = {endpoint: service for service, endpoint in item.service_endpoints}
    service_tools = {
        "gmail": "list_labels",
        "drive": "list_recent_files",
        "docs": "read_doc",
        "sheets": "get_spreadsheet",
        "slides": "read_presentation",
        "calendar": "list_calendars",
        "chat": "search_conversations",
        "people": "get_user_profile",
    }
    visited = []
    canary_calls = []

    @asynccontextmanager
    async def fake_stream(endpoint, **kwargs):
        del kwargs
        visited.append(endpoint)
        yield endpoint, None, None

    def fake_session(read_stream, write_stream):
        del write_stream
        service = endpoint_to_service[read_stream]
        tool_name = "not_approved" if service == broken_service else service_tools[service]
        return FakeWorkspaceSession(service, tool_name, canary_calls)

    monkeypatch.setattr(hosted_connectors.httpx, "AsyncClient", FakeHttpClient)
    monkeypatch.setattr(hosted_connectors, "streamable_http_client", fake_stream)
    monkeypatch.setattr(hosted_connectors, "ClientSession", fake_session)
    return item, visited, canary_calls


@pytest.mark.asyncio
async def test_verifier_uses_the_capped_transport_with_a_mockable_http_client(monkeypatch):
    captured_kwargs = []
    session = FakeWorkspaceSession("github", "get_me", [])

    class CapturingHttpClient(FakeHttpClient):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            captured_kwargs.append(kwargs)

    @asynccontextmanager
    async def fake_stream(*args, **kwargs):
        del args, kwargs
        yield None, None, None

    monkeypatch.setattr(hosted_connectors.httpx, "AsyncClient", CapturingHttpClient)
    monkeypatch.setattr(hosted_connectors, "streamable_http_client", fake_stream)
    monkeypatch.setattr(hosted_connectors, "ClientSession", lambda *args: session)

    await McpConnectionVerifier().verify(
        connector("github"),
        {
            "credential": "provider-token",
            "endpoint": "https://api.githubcopilot.com/mcp",
            "scheme": "bearer",
            "account": None,
        },
    )

    assert len(captured_kwargs) == 1
    transport = captured_kwargs[0]["transport"]
    assert isinstance(transport, CappedAsyncTransport)
    assert transport.maximum_bytes == MAX_HOSTED_MCP_RESPONSE_BYTES


@pytest.mark.asyncio
async def test_certification_calls_fixed_read_canary_and_keeps_content_out_of_receipt():
    session = FakeSession([tool("get_me"), tool("search_repositories")])

    receipt = await McpConnectionVerifier().certify_session(session, connector("github"))

    assert session.calls == [("get_me", {})]
    assert receipt.tool_count == 2
    assert receipt.canary_tool == "get_me"
    assert len(receipt.tool_schema_sha256) == 64
    assert "private provider content" not in repr(receipt)


@pytest.mark.asyncio
async def test_n8n_canary_is_pinned_to_one_approved_workflow_without_execution():
    session = FakeSession([tool("get_workflow_details"), tool("execute_workflow")])

    receipt = await McpConnectionVerifier().certify_session(
        session,
        connector("n8n"),
        allowed_workflow_ids=("approved-workflow",),
    )

    assert receipt.canary_tool == "get_workflow_details"
    assert session.calls == [
        (
            "get_workflow_details",
            {"workflowId": "approved-workflow", "detailLevel": "execution"},
        )
    ]


@pytest.mark.asyncio
async def test_provider_tool_error_can_never_become_ready():
    session = FakeSession(
        [tool("get_stripe_account_info")],
        CallToolResult(
            content=[TextContent(type="text", text="provider rejected the call")],
            isError=True,
        ),
    )

    with pytest.raises(HostedConnectorError, match="canary_failed"):
        await McpConnectionVerifier().certify_session(session, connector("stripe"))


@pytest.mark.asyncio
async def test_cloudflare_canary_is_a_one_minute_bounded_read():
    session = FakeSession([tool("observability_keys")])

    await McpConnectionVerifier().certify_session(session, connector("cloudflare"))

    name, arguments = session.calls[0]
    query = arguments["keysQuery"]
    start = dt.datetime.fromisoformat(query["timeframe"]["from"])
    end = dt.datetime.fromisoformat(query["timeframe"]["to"])
    assert name == "observability_keys"
    assert end - start == dt.timedelta(seconds=60)
    assert query["datasets"] == []
    assert query["filters"] == []
    assert query["limit"] == 1


@pytest.mark.asyncio
async def test_google_aggregate_requires_all_services_and_certifies_only_live_read_products(
    monkeypatch,
):
    item, visited, canary_calls = install_workspace_bundle_fakes(monkeypatch)

    receipt = await McpConnectionVerifier().certify_service_bundle(
        item,
        {"Authorization": "Bearer provider-token"},
    )

    assert len(item.service_endpoints) == 8
    assert set(visited) == {endpoint for _, endpoint in item.service_endpoints}
    assert receipt.tool_count == 5
    assert receipt.canary_tool == "people.get_user_profile"
    assert {service for service, _, _ in canary_calls} == {
        "gmail",
        "drive",
        "calendar",
        "chat",
        "people",
    }
    assert ("gmail", "list_labels", {"pageSize": 1}) in canary_calls
    assert (
        "drive",
        "list_recent_files",
        {"pageSize": 1, "excludeContentSnippets": True},
    ) in canary_calls
    assert ("calendar", "list_calendars", {"pageSize": 1}) in canary_calls
    assert ("chat", "search_conversations", {"pageSize": 1}) in canary_calls
    assert ("people", "get_user_profile", {}) in canary_calls


@pytest.mark.asyncio
async def test_google_aggregate_fails_if_any_service_has_no_approved_read_tool(monkeypatch):
    item, visited, canary_calls = install_workspace_bundle_fakes(
        monkeypatch,
        broken_service="drive",
    )

    with pytest.raises(HostedConnectorError, match="safe_preset_mismatch"):
        await McpConnectionVerifier().certify_service_bundle(
            item,
            {"Authorization": "Bearer provider-token"},
        )

    assert len(visited) == 8
    assert all(service in {"gmail", "calendar", "chat", "people"} for service, _, _ in canary_calls)
