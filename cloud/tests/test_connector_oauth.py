import datetime as dt
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

import control_plane
from auth_sessions import MemoryAuthSessionStore
from connector_oauth import (
    ConnectorOAuthBroker,
    HostedOAuthError,
    MemoryOAuthFlowStore,
    OAuthCompletion,
    OAuthFlow,
)
from credential_vault import MemoryConnectorVault
from hosted_connectors import connector, resolve_token_endpoint
from user_auth import UserIdentity

NOW = dt.datetime(2026, 8, 30, 18, 0, tzinfo=dt.UTC)


def oauth_transport(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if request.method == "POST" and url == "https://hyperagent.com/api/mcp":
        return httpx.Response(
            401,
            headers={
                "WWW-Authenticate": (
                    'Bearer resource_metadata="https://hyperagent.com/'
                    '.well-known/oauth-protected-resource/api/mcp"'
                )
            },
        )
    if url == "https://hyperagent.com/.well-known/oauth-protected-resource/api/mcp":
        return httpx.Response(
            200,
            json={
                "resource": "https://hyperagent.com/api/mcp",
                "authorization_servers": ["https://hyperagent.com"],
                "scopes_supported": [
                    "threads:read",
                    "threads:write",
                    "approvals:read",
                    "approvals:write",
                    "offline_access",
                ],
            },
        )
    if url == "https://hyperagent.com/.well-known/oauth-authorization-server":
        return httpx.Response(
            200,
            json={
                "issuer": "https://hyperagent.com",
                "authorization_endpoint": "https://hyperagent.com/oauth/authorize",
                "token_endpoint": "https://hyperagent.com/oauth/token",
                "code_challenge_methods_supported": ["S256"],
                "client_id_metadata_document_supported": True,
            },
        )
    if request.method == "POST" and url == "https://hyperagent.com/oauth/token":
        form = parse_qs(request.content.decode())
        assert form["grant_type"] == ["authorization_code"]
        assert form["code"] == ["provider-code"]
        assert form["client_id"] == ["https://rally.agent9.dev/oauth/client-metadata.json"]
        assert len(form["code_verifier"][0]) == 128
        return httpx.Response(
            200,
            json={
                "access_token": "provider-access-token",
                "refresh_token": "provider-refresh-token",
                "token_type": "bearer",
                "expires_in": 3600,
                "scope": "mcp:tools",
            },
        )
    return httpx.Response(404)


@pytest.mark.asyncio
async def test_oauth_start_uses_pkce_cimd_and_one_use_hashed_state():
    store = MemoryOAuthFlowStore(clock=lambda: NOW)
    broker = ConnectorOAuthBroker(
        store,
        transport=httpx.MockTransport(oauth_transport),
        clock=lambda: NOW,
    )
    identity = UserIdentity(uid="google-user-one", email="owner@example.com")

    authorization_url = await broker.start(
        connector("hyperagent"),
        identity,
        None,
    )
    query = parse_qs(urlsplit(authorization_url).query)
    state = query["state"][0]

    assert authorization_url.startswith("https://hyperagent.com/oauth/authorize?")
    assert query["client_id"] == ["https://rally.agent9.dev/oauth/client-metadata.json"]
    assert query["redirect_uri"] == ["https://rally.agent9.dev/admin/connect/callback"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == ["threads:read approvals:read offline_access"]
    assert state not in repr(store._flows)
    assert all(len(state_hash) == 64 for state_hash in store._flows)

    flow = await broker.consume(state)
    assert flow is not None
    assert flow.identity.uid == identity.uid
    assert await broker.consume(state) is None

    completion = await broker.exchange(flow, "provider-code")
    assert completion.access_material["credential"] == "provider-access-token"
    assert "provider-refresh-token" in completion.stored_material
    assert resolve_token_endpoint(connector("atlassian")) == "https://mcp.atlassian.com/v1/mcp"

    def unsupported_token_transport(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and str(request.url) == "https://hyperagent.com/oauth/token":
            return httpx.Response(
                200,
                json={"access_token": "wrong-scheme", "token_type": "Basic"},
            )
        return oauth_transport(request)

    unsupported = ConnectorOAuthBroker(
        store,
        transport=httpx.MockTransport(unsupported_token_transport),
        clock=lambda: NOW,
    )
    with pytest.raises(HostedOAuthError, match="oauth_token_exchange_failed"):
        await unsupported.exchange(flow, "provider-code")


@pytest.mark.asyncio
async def test_oauth_rejects_discovery_outside_provider_boundary():
    def malicious_transport(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                401,
                headers={
                    "WWW-Authenticate": (
                        'Bearer resource_metadata="https://hyperagent.com/'
                        '.well-known/oauth-protected-resource/api/mcp"'
                    )
                },
            )
        return httpx.Response(
            200,
            json={
                "resource": "https://hyperagent.com/api/mcp",
                "authorization_servers": ["https://attacker.example"],
            },
        )

    broker = ConnectorOAuthBroker(
        MemoryOAuthFlowStore(clock=lambda: NOW),
        transport=httpx.MockTransport(malicious_transport),
        clock=lambda: NOW,
    )
    with pytest.raises(HostedOAuthError, match="oauth_endpoint_not_allowed"):
        await broker.start(
            connector("hyperagent"),
            UserIdentity(uid="user", email="owner@example.com"),
            None,
        )


@pytest.mark.asyncio
async def test_n8n_oauth_requires_an_explicit_workflow_boundary():
    broker = ConnectorOAuthBroker(
        MemoryOAuthFlowStore(clock=lambda: NOW),
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
        clock=lambda: NOW,
    )
    identity = UserIdentity(uid="user", email="owner@example.com")

    with pytest.raises(HostedOAuthError, match="policy_configuration_required"):
        await broker.start(
            connector("n8n"),
            identity,
            "https://company.app.n8n.cloud/mcp-server/http",
        )


@pytest.mark.asyncio
async def test_oauth_rejects_requested_scope_the_provider_does_not_advertise():
    def transport(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                401,
                headers={
                    "WWW-Authenticate": (
                        'Bearer resource_metadata="https://hyperagent.com/'
                        '.well-known/oauth-protected-resource"'
                    )
                },
            )
        if str(request.url).endswith("oauth-protected-resource"):
            return httpx.Response(
                200,
                json={
                    "resource": "https://hyperagent.com/api/mcp",
                    "authorization_servers": ["https://hyperagent.com"],
                    "scopes_supported": ["threads:read"],
                },
            )
        return httpx.Response(
            200,
            json={
                "issuer": "https://hyperagent.com",
                "authorization_endpoint": "https://hyperagent.com/oauth/authorize",
                "token_endpoint": "https://hyperagent.com/oauth/token",
                "client_id_metadata_document_supported": True,
            },
        )

    broker = ConnectorOAuthBroker(
        MemoryOAuthFlowStore(clock=lambda: NOW),
        transport=httpx.MockTransport(transport),
        clock=lambda: NOW,
    )
    with pytest.raises(HostedOAuthError, match="oauth_scope_unavailable"):
        await broker.start(
            connector("hyperagent"),
            UserIdentity(uid="user", email="owner@example.com"),
            None,
        )


class CallbackBroker:
    def __init__(self, flow: OAuthFlow):
        self.flow = flow

    async def consume(self, state: str):
        return self.flow if state == "s" * 32 else None

    async def exchange(self, flow: OAuthFlow, code: str):
        assert flow is self.flow
        assert code == "provider-code"
        return OAuthCompletion(
            stored_material=(
                '{"schema":"rally.oauth-material/v1","access_token":"provider-access-token"}'
            ),
            access_material={
                "credential": "provider-access-token",
                "endpoint": "https://hyperagent.com/api/mcp",
                "scheme": "bearer",
                "account": None,
            },
        )


class CallbackVerifier:
    async def verify(self, item, material, **kwargs):
        assert item.id == "hyperagent"
        assert material["credential"] == "provider-access-token"
        assert kwargs["allowed_workflow_ids"] == ()
        return 5


@pytest.mark.asyncio
async def test_callback_restores_session_and_marks_exact_connector_ready(monkeypatch):
    identity = UserIdentity(uid="google-user-one", email="owner@example.com")
    flow = OAuthFlow(
        identity=identity,
        connector_id="hyperagent",
        endpoint="https://hyperagent.com/api/mcp",
        authorization_endpoint="https://hyperagent.com/oauth/authorize",
        token_endpoint="https://hyperagent.com/oauth/token",
        revocation_endpoint=None,
        client_id="rally-client",
        client_secret=None,
        token_auth_method="none",
        code_verifier="v" * 128,
        scope="mcp:tools",
        resource="https://hyperagent.com/api/mcp",
        allowed_workflow_ids=(),
        expires_at=NOW + dt.timedelta(minutes=10),
    )
    vault = MemoryConnectorVault()
    auth_store = MemoryAuthSessionStore(clock=lambda: NOW)
    control_plane.app.dependency_overrides[control_plane.get_oauth_broker] = lambda: CallbackBroker(
        flow
    )
    control_plane.app.dependency_overrides[control_plane.get_vault] = lambda: vault
    control_plane.app.dependency_overrides[control_plane.get_auth_store] = lambda: auth_store
    control_plane.app.dependency_overrides[control_plane.get_connection_verifier] = lambda: (
        CallbackVerifier()
    )
    control_plane.app.dependency_overrides[control_plane.require_user] = lambda: identity
    monkeypatch.setenv("RALLY_ADMIN_RETURN_URL", "https://rally.agent9.dev/admin/")

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=control_plane.app),
            base_url="http://rally",
            follow_redirects=False,
        ) as client:
            callback = await client.post(
                "/auth/connector/callback",
                json={"state": "s" * 32, "code": "provider-code"},
            )
            fragment = parse_qs(urlsplit(callback.headers["location"]).fragment)
            exchanged = await client.post(
                "/v1/auth/exchange",
                json={"code": fragment["rally-login-code"][0]},
            )
            listed = await client.get("/v1/connections")
    finally:
        control_plane.app.dependency_overrides.clear()

    assert callback.status_code == 303
    assert fragment["rally-connection"] == ["hyperagent"]
    assert fragment["rally-connection-status"] == ["ready"]
    assert exchanged.status_code == 200
    assert listed.json()["connections"][0]["status"] == "ready"
    assert listed.json()["connections"][0]["tool_count"] == 5
    assert "provider-access-token" not in callback.text
    assert "provider-access-token" not in listed.text
