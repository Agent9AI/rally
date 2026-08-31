import datetime as dt
import json
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest

import connector_oauth
import control_plane
from auth_sessions import MemoryAuthSessionStore
from connector_oauth import (
    ConnectorOAuthBroker,
    HostedOAuthError,
    MemoryOAuthFlowStore,
    OAuthCompletion,
    OAuthFlow,
)
from credential_vault import (
    ConnectorSecret,
    CredentialVaultError,
    MemoryConnectorVault,
    certified_manifest_sha256,
)
from hosted_connectors import (
    ConnectionCertification,
    connector,
    make_oauth_material,
    resolve_token_endpoint,
)
from user_auth import UserIdentity

NOW = dt.datetime(2026, 8, 30, 18, 0, tzinfo=dt.UTC)
BROWSER_BINDING = "b" * 43


class FlowSnapshot:
    def __init__(self, value):
        self.value = value
        self.exists = value is not None

    def to_dict(self):
        return dict(self.value or {})


class FlowDocument:
    def __init__(self, collection, key):
        self.collection = collection
        self.key = key

    async def get(self, transaction=None):
        return FlowSnapshot(self.collection.values.get(self.key))


class FlowCollection:
    def __init__(self):
        self.values = {}

    def document(self, key):
        return FlowDocument(self, key)


class FlowTransaction:
    def create(self, document, value):
        assert document.key not in document.collection.values
        document.collection.values[document.key] = dict(value)

    def set(self, document, value):
        document.collection.values[document.key] = dict(value)

    def delete(self, document):
        document.collection.values.pop(document.key, None)


class FlowFirestore:
    def __init__(self):
        self.flows = FlowCollection()

    def collection(self, name):
        assert name == "rally_connector_oauth_flows"
        return self.flows

    def transaction(self):
        return FlowTransaction()


class FlowCipher:
    def seal(self, plaintext, associated_data):
        return {
            "schema": "rally.connector-oauth-flow/v1",
            "payload": plaintext.decode(),
            "associated_data": associated_data.decode(),
        }

    def open(self, envelope, associated_data):
        assert envelope["associated_data"] == associated_data.decode()
        return envelope["payload"].encode()


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
                "revocation_endpoint": "https://hyperagent.com/oauth/revoke",
                "code_challenge_methods_supported": ["S256"],
                "client_id_metadata_document_supported": True,
            },
        )
    if request.method == "POST" and url == "https://hyperagent.com/oauth/token":
        form = parse_qs(request.content.decode())
        assert form["grant_type"] == ["authorization_code"]
        assert form["code"] == ["provider-code"]
        assert form["client_id"] == ["https://rally.agent9.dev/oauth/client-metadata.json"]
        assert form["resource"] == ["https://hyperagent.com/api/mcp"]
        assert len(form["code_verifier"][0]) == 128
        return httpx.Response(
            200,
            json={
                "access_token": "provider-access-token",
                "refresh_token": "provider-refresh-token",
                "token_type": "bearer",
                "expires_in": 3600,
                "scope": "threads:read approvals:read offline_access",
            },
        )
    if request.method == "POST" and url == "https://hyperagent.com/oauth/revoke":
        form = parse_qs(request.content.decode())
        assert form["token"] == ["provider-refresh-token"]
        assert form["token_type_hint"] == ["refresh_token"]
        return httpx.Response(200)
    return httpx.Response(404)


@pytest.mark.asyncio
async def test_workspace_uses_rally_registered_confidential_client_and_read_only_scopes(
    monkeypatch,
):
    monkeypatch.setenv(
        "RALLY_GOOGLE_WORKSPACE_CLIENT_ID",
        "workspace-client.apps.googleusercontent.com",
    )
    monkeypatch.setenv("RALLY_GOOGLE_WORKSPACE_CLIENT_SECRET", "server-only-secret")

    def transport(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://oauth2.googleapis.com/token"
        form = parse_qs(request.content.decode())
        assert form["client_secret"] == ["server-only-secret"]
        assert form["code_verifier"]
        assert "resource" not in form
        return httpx.Response(
            200,
            json={
                "access_token": "workspace-access",
                "refresh_token": "workspace-refresh",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )

    store = MemoryOAuthFlowStore(clock=lambda: NOW)
    broker = ConnectorOAuthBroker(
        store,
        transport=httpx.MockTransport(transport),
        clock=lambda: NOW,
    )
    authorization = await broker.start(
        connector("google-workspace"),
        UserIdentity(uid="user", email="owner@example.com"),
        None,
    )
    authorization_url = authorization.authorization_url
    query = parse_qs(urlsplit(authorization_url).query)
    scope = query["scope"][0]
    assert authorization_url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert "gmail.readonly" in scope
    assert "gmail.compose" not in scope
    assert "drive.file" not in scope
    flow = await broker.consume(
        query["state"][0],
        authorization.browser_binding,
        "https://accounts.google.com",
    )
    assert flow is not None
    completion = await broker.exchange(flow, "google-code")
    assert completion.access_material["credential"] == "workspace-access"
    assert "server-only-secret" in completion.stored_material
    assert json.loads(completion.stored_material)["resource"] is None

    partial_scope_revocations = []

    def partial_scope_transport(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://oauth2.googleapis.com/revoke":
            form = parse_qs(request.content.decode())
            partial_scope_revocations.append(form["token"][0])
            assert form["token_type_hint"] == ["refresh_token"]
            return httpx.Response(200)
        assert str(request.url) == "https://oauth2.googleapis.com/token"
        return httpx.Response(
            200,
            json={
                "access_token": "workspace-access",
                "refresh_token": "workspace-refresh",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "https://www.googleapis.com/auth/contacts.readonly",
            },
        )

    partial_scope_broker = ConnectorOAuthBroker(
        store,
        transport=httpx.MockTransport(partial_scope_transport),
        clock=lambda: NOW,
    )
    with pytest.raises(HostedOAuthError, match="oauth_scope_incomplete"):
        await partial_scope_broker.exchange(flow, "google-code")
    assert partial_scope_revocations == ["workspace-refresh"]


@pytest.mark.asyncio
async def test_oauth_start_uses_pkce_cimd_and_one_use_hashed_state():
    store = MemoryOAuthFlowStore(clock=lambda: NOW)
    broker = ConnectorOAuthBroker(
        store,
        transport=httpx.MockTransport(oauth_transport),
        clock=lambda: NOW,
    )
    identity = UserIdentity(uid="google-user-one", email="owner@example.com")

    authorization = await broker.start(
        connector("hyperagent"),
        identity,
        None,
    )
    authorization_url = authorization.authorization_url
    query = parse_qs(urlsplit(authorization_url).query)
    state = query["state"][0]

    assert authorization_url.startswith("https://hyperagent.com/oauth/authorize?")
    assert query["client_id"] == ["https://rally.agent9.dev/oauth/client-metadata.json"]
    assert query["redirect_uri"] == ["https://rally.agent9.dev/admin/connect/callback"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == ["threads:read approvals:read offline_access"]
    assert state not in repr(store._flows)
    assert all(len(state_hash) == 64 for state_hash in store._flows)
    with pytest.raises(HostedOAuthError, match="oauth_in_progress"):
        await broker.start(connector("hyperagent"), identity, None)

    assert await broker.consume(state, "x" * 43) is None
    assert (
        await broker.consume(
            state,
            authorization.browser_binding,
            "https://wrong.example",
        )
        is None
    )
    flow = await broker.consume(
        state,
        authorization.browser_binding,
        "https://hyperagent.com",
    )
    assert flow is not None
    assert flow.identity.uid == identity.uid
    assert await broker.consume(state, authorization.browser_binding) is None
    assert store._active == {}

    completion = await broker.exchange(flow, "provider-code")
    assert completion.access_material["credential"] == "provider-access-token"
    assert "provider-refresh-token" in completion.stored_material
    assert json.loads(completion.stored_material)["resource"] == ("https://hyperagent.com/api/mcp")
    assert await broker.revoke(connector("hyperagent"), completion.stored_material) is True
    assert resolve_token_endpoint(connector("atlassian")) == "https://mcp.atlassian.com/v1/mcp"

    unsupported_revocations = []

    def unsupported_token_transport(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and str(request.url) == "https://hyperagent.com/oauth/token":
            return httpx.Response(
                200,
                json={"access_token": "wrong-scheme", "token_type": "Basic"},
            )
        if request.method == "POST" and str(request.url) == "https://hyperagent.com/oauth/revoke":
            form = parse_qs(request.content.decode())
            unsupported_revocations.append(form["token"][0])
            assert form["token_type_hint"] == ["access_token"]
            return httpx.Response(200)
        return oauth_transport(request)

    unsupported = ConnectorOAuthBroker(
        store,
        transport=httpx.MockTransport(unsupported_token_transport),
        clock=lambda: NOW,
    )
    with pytest.raises(HostedOAuthError, match="oauth_token_exchange_failed"):
        await unsupported.exchange(flow, "provider-code")
    assert unsupported_revocations == ["wrong-scheme"]

    widened_revocations = []

    def widened_scope_transport(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and str(request.url) == "https://hyperagent.com/oauth/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "provider-access-token",
                    "refresh_token": "provider-refresh-token",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": "threads:read approvals:read offline_access admin:write",
                },
            )
        if request.method == "POST" and str(request.url) == "https://hyperagent.com/oauth/revoke":
            form = parse_qs(request.content.decode())
            widened_revocations.append(form["token"][0])
        return oauth_transport(request)

    widened = ConnectorOAuthBroker(
        store,
        transport=httpx.MockTransport(widened_scope_transport),
        clock=lambda: NOW,
    )
    with pytest.raises(HostedOAuthError, match="oauth_scope_widened"):
        await widened.exchange(flow, "provider-code")
    assert widened_revocations == ["provider-refresh-token"]

    access_revocations = []

    def no_refresh_transport(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and str(request.url) == "https://hyperagent.com/oauth/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "provider-access-token",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": "threads:read approvals:read",
                },
            )
        if request.method == "POST" and str(request.url) == "https://hyperagent.com/oauth/revoke":
            form = parse_qs(request.content.decode())
            access_revocations.append(form["token"][0])
            assert form["token_type_hint"] == ["access_token"]
            return httpx.Response(200)
        return oauth_transport(request)

    no_refresh = ConnectorOAuthBroker(
        store,
        transport=httpx.MockTransport(no_refresh_transport),
        clock=lambda: NOW,
    )
    with pytest.raises(HostedOAuthError, match="oauth_refresh_required"):
        await no_refresh.exchange(flow, "provider-code")
    assert access_revocations == ["provider-access-token"]

    def failed_cleanup_transport(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and str(request.url) == "https://hyperagent.com/oauth/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "provider-access-token",
                    "refresh_token": "provider-refresh-token",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": "threads:read approvals:read offline_access admin:write",
                },
            )
        if request.method == "POST" and str(request.url) == "https://hyperagent.com/oauth/revoke":
            return httpx.Response(503)
        return oauth_transport(request)

    failed_cleanup = ConnectorOAuthBroker(
        store,
        transport=httpx.MockTransport(failed_cleanup_transport),
        clock=lambda: NOW,
    )
    with pytest.raises(HostedOAuthError, match="oauth_provider_cleanup_required"):
        await failed_cleanup.exchange(flow, "provider-code")


@pytest.mark.asyncio
async def test_firestore_flow_reservation_is_single_active_and_stale_consume_is_safe(
    monkeypatch,
):
    monkeypatch.setattr(
        "google.cloud.firestore.async_transactional",
        lambda function: function,
    )
    fake = FlowFirestore()
    store = object.__new__(connector_oauth.FirestoreOAuthFlowStore)
    store.client = fake
    store.collection = fake.flows
    store.cipher = FlowCipher()
    identity = UserIdentity(uid="user", email="owner@example.com")

    def flow(expires_at):
        return OAuthFlow(
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
            issuer="https://hyperagent.com",
            browser_binding_hash=connector_oauth._browser_binding_hash(BROWSER_BINDING) or "",
            expires_at=expires_at,
        )

    now = dt.datetime.now(dt.UTC)
    await store.put("a" * 32, flow(now + dt.timedelta(minutes=10)))
    with pytest.raises(HostedOAuthError, match="oauth_in_progress"):
        await store.put("b" * 32, flow(now + dt.timedelta(minutes=10)))
    assert await store.consume("a" * 32, "wrong-binding" * 4) is None
    consumed = await store.consume("a" * 32, BROWSER_BINDING)
    assert consumed is not None

    await store.put("c" * 32, flow(now - dt.timedelta(seconds=1)))
    await store.put("d" * 32, flow(now + dt.timedelta(minutes=10)))
    assert await store.consume("c" * 32, BROWSER_BINDING) is None
    active_keys = [key for key in fake.flows.values if key.startswith("active-")]
    assert len(active_keys) == 1
    assert fake.flows.values[active_keys[0]]["state_hash"] == connector_oauth._state_hash("d" * 32)
    assert (await store.consume("d" * 32, BROWSER_BINDING)).connector_id == "hyperagent"
    assert [key for key in fake.flows.values if key.startswith("active-")] == []


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
        self.exchange_calls = []

    async def consume(self, state: str, browser_binding: str, issuer: str | None = None):
        assert browser_binding == BROWSER_BINDING
        if issuer is not None:
            assert issuer == "https://hyperagent.com"
        return self.flow if state == "s" * 32 else None

    async def exchange(self, flow: OAuthFlow, code: str):
        assert flow is self.flow
        assert code == "provider-code"
        self.exchange_calls.append(code)
        return OAuthCompletion(
            stored_material=make_oauth_material(
                endpoint="https://hyperagent.com/api/mcp",
                access_token="provider-access-token",
                refresh_token="provider-refresh-token",
                token_type="Bearer",
                expires_in=3600,
                scope="mcp:tools",
                client_id="rally-client",
                client_secret=None,
                token_endpoint="https://hyperagent.com/oauth/token",
                revocation_endpoint=None,
                token_auth_method="none",
                resource="https://hyperagent.com/api/mcp",
            ),
            access_material={
                "credential": "provider-access-token",
                "endpoint": "https://hyperagent.com/api/mcp",
                "scheme": "bearer",
                "account": None,
            },
        )


class CallbackVerifier:
    def __init__(self):
        self.calls = []

    async def verify(self, item, material, **kwargs):
        assert item.id == "hyperagent"
        assert material["credential"] == "provider-access-token"
        assert kwargs["allowed_workflow_ids"] == ()
        self.calls.append(item.id)
        manifest = (
            ("get_agent", "a" * 64),
            ("get_run", "c" * 64),
            ("list_agents", "b" * 64),
            ("list_runs", "d" * 64),
            ("search_runs", "e" * 64),
        )
        return ConnectionCertification(
            tool_count=5,
            canary_tool="list_agents",
            tool_schema_sha256="b" * 64,
            certified_tools=manifest,
            certified_manifest_sha256=certified_manifest_sha256(manifest),
        )


@pytest.mark.asyncio
async def test_callback_restores_session_before_separate_live_certification(monkeypatch):
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
        issuer="https://hyperagent.com",
        browser_binding_hash=connector_oauth._browser_binding_hash(BROWSER_BINDING) or "",
        expires_at=NOW + dt.timedelta(minutes=10),
    )
    vault = MemoryConnectorVault()
    auth_store = MemoryAuthSessionStore(clock=lambda: NOW)
    broker = CallbackBroker(flow)
    verifier = CallbackVerifier()
    control_plane.app.dependency_overrides[control_plane.get_oauth_broker] = lambda: broker
    control_plane.app.dependency_overrides[control_plane.get_vault] = lambda: vault
    control_plane.app.dependency_overrides[control_plane.get_auth_store] = lambda: auth_store
    control_plane.app.dependency_overrides[control_plane.get_connection_verifier] = lambda: verifier
    control_plane.app.dependency_overrides[control_plane.require_user] = lambda: identity
    monkeypatch.setenv("RALLY_ADMIN_RETURN_URL", "https://rally.agent9.dev/admin/")

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=control_plane.app),
            base_url="http://rally",
            follow_redirects=False,
        ) as client:
            callback = await client.post(
                "/auth/connector/callback/form",
                content=urlencode({"state": "s" * 32, "code": "provider-code"}),
                headers={
                    "content-type": "application/x-www-form-urlencoded",
                    "x-rally-oauth-binding": BROWSER_BINDING,
                },
            )
            fragment = parse_qs(urlsplit(callback.headers["location"]).fragment)
            exchanged = await client.post(
                "/v1/auth/exchange",
                json={"code": fragment["rally-login-code"][0]},
            )
            before = await client.get("/v1/connections")
            assert verifier.calls == []
            certified = await client.post("/v1/connections/hyperagent/verify")
            listed = await client.get("/v1/connections")
    finally:
        control_plane.app.dependency_overrides.clear()

    assert callback.status_code == 303
    assert fragment["rally-connection"] == ["hyperagent"]
    assert fragment["rally-connection-status"] == ["verifying"]
    assert exchanged.status_code == 200
    assert before.json()["connections"][0]["status"] == "stored_unverified"
    assert certified.status_code == 200
    assert certified.json()["status"] == "ready"
    assert listed.json()["connections"][0]["status"] == "ready"
    assert listed.json()["connections"][0]["tool_count"] == 5
    assert listed.json()["connections"][0]["certification"]["live_read"] is True
    assert "provider-access-token" not in callback.text
    assert "provider-access-token" not in listed.text
    assert broker.exchange_calls == ["provider-code"]
    assert verifier.calls == ["hyperagent"]


@pytest.mark.asyncio
async def test_callback_never_overwrites_an_existing_oauth_grant(monkeypatch):
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
        issuer="https://hyperagent.com",
        browser_binding_hash=connector_oauth._browser_binding_hash(BROWSER_BINDING) or "",
        expires_at=NOW + dt.timedelta(minutes=10),
    )
    broker = CallbackBroker(flow)
    vault = MemoryConnectorVault()
    previous = ConnectorSecret("previous-sealed-oauth-grant", "oauth_refresh_token")
    await vault.put(identity.uid, "hyperagent", previous)
    auth_store = MemoryAuthSessionStore(clock=lambda: NOW)
    control_plane.app.dependency_overrides[control_plane.get_oauth_broker] = lambda: broker
    control_plane.app.dependency_overrides[control_plane.get_vault] = lambda: vault
    control_plane.app.dependency_overrides[control_plane.get_auth_store] = lambda: auth_store
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
                headers={"x-rally-oauth-binding": BROWSER_BINDING},
            )
    finally:
        control_plane.app.dependency_overrides.clear()

    fragment = parse_qs(urlsplit(callback.headers["location"]).fragment)
    assert callback.status_code == 303
    assert fragment["rally-connection-status"] == ["disconnect-first"]
    assert broker.exchange_calls == []
    assert await vault.get_secret(identity.uid, "hyperagent") == previous


@pytest.mark.asyncio
async def test_callback_persists_unverified_grant_without_claiming_verifier(monkeypatch):
    class BeginMustNotRunVault(MemoryConnectorVault):
        async def begin_verification(self, *args, **kwargs):
            del args, kwargs
            raise AssertionError("the browser callback must not reserve the verification lease")

    class NoRevokeCallbackBroker(CallbackBroker):
        async def revoke(self, *args, **kwargs):
            del args, kwargs
            raise AssertionError("a concurrently certified grant must not be revoked")

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
        issuer="https://hyperagent.com",
        browser_binding_hash=connector_oauth._browser_binding_hash(BROWSER_BINDING) or "",
        expires_at=NOW + dt.timedelta(minutes=10),
    )
    broker = NoRevokeCallbackBroker(flow)
    vault = BeginMustNotRunVault()
    auth_store = MemoryAuthSessionStore(clock=lambda: NOW)
    control_plane.app.dependency_overrides[control_plane.get_oauth_broker] = lambda: broker
    control_plane.app.dependency_overrides[control_plane.get_vault] = lambda: vault
    control_plane.app.dependency_overrides[control_plane.get_auth_store] = lambda: auth_store
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
                headers={"x-rally-oauth-binding": BROWSER_BINDING},
            )
    finally:
        control_plane.app.dependency_overrides.clear()

    fragment = parse_qs(urlsplit(callback.headers["location"]).fragment)
    assert callback.status_code == 303
    assert fragment["rally-connection-status"] == ["verifying"]
    [record] = await vault.list(identity.uid)
    assert record.status == "stored_unverified"
    assert record.credential_generation
    assert record.execution_lease is None


@pytest.mark.asyncio
async def test_callback_revokes_a_grant_that_cannot_be_persisted(monkeypatch):
    class FailingPutVault(MemoryConnectorVault):
        async def put(self, *args, **kwargs):
            del args, kwargs
            raise CredentialVaultError("simulated sealed-write failure")

    class CleanupCallbackBroker(CallbackBroker):
        def __init__(self, flow, *, revoked):
            super().__init__(flow)
            self.revoked = revoked
            self.revoke_calls = []

        async def revoke(self, item, stored_material):
            self.revoke_calls.append((item.id, stored_material))
            return self.revoked

    identity = UserIdentity(uid="google-user-one", email="owner@example.com")
    flow = OAuthFlow(
        identity=identity,
        connector_id="hyperagent",
        endpoint="https://hyperagent.com/api/mcp",
        authorization_endpoint="https://hyperagent.com/oauth/authorize",
        token_endpoint="https://hyperagent.com/oauth/token",
        revocation_endpoint="https://hyperagent.com/oauth/revoke",
        client_id="rally-client",
        client_secret=None,
        token_auth_method="none",
        code_verifier="v" * 128,
        scope="mcp:tools",
        resource="https://hyperagent.com/api/mcp",
        allowed_workflow_ids=(),
        issuer="https://hyperagent.com",
        browser_binding_hash=connector_oauth._browser_binding_hash(BROWSER_BINDING) or "",
        expires_at=NOW + dt.timedelta(minutes=10),
    )
    monkeypatch.setenv("RALLY_ADMIN_RETURN_URL", "https://rally.agent9.dev/admin/")

    def dependency(value):
        def provide():
            return value

        return provide

    for revoked, expected_status in (
        (True, "needs-attention"),
        (False, "provider-cleanup-required"),
    ):
        broker = CleanupCallbackBroker(flow, revoked=revoked)
        vault = FailingPutVault()
        auth_store = MemoryAuthSessionStore(clock=lambda: NOW)
        control_plane.app.dependency_overrides[control_plane.get_oauth_broker] = dependency(broker)
        control_plane.app.dependency_overrides[control_plane.get_vault] = dependency(vault)
        control_plane.app.dependency_overrides[control_plane.get_auth_store] = dependency(
            auth_store
        )
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=control_plane.app),
                base_url="http://rally",
                follow_redirects=False,
            ) as client:
                callback = await client.post(
                    "/auth/connector/callback",
                    json={"state": "s" * 32, "code": "provider-code"},
                    headers={"x-rally-oauth-binding": BROWSER_BINDING},
                )
        finally:
            control_plane.app.dependency_overrides.clear()

        fragment = parse_qs(urlsplit(callback.headers["location"]).fragment)
        assert fragment["rally-connection-status"] == [expected_status]
        assert broker.exchange_calls == ["provider-code"]
        assert len(broker.revoke_calls) == 1
        assert broker.revoke_calls[0][0] == "hyperagent"
        assert "provider-refresh-token" in broker.revoke_calls[0][1]
        assert await vault.list(identity.uid) == []

    class UntrackedGrantBroker(CallbackBroker):
        async def exchange(self, flow, code):
            del flow, code
            raise HostedOAuthError("oauth_provider_cleanup_required")

    broker = UntrackedGrantBroker(flow)
    vault = MemoryConnectorVault()
    auth_store = MemoryAuthSessionStore(clock=lambda: NOW)
    control_plane.app.dependency_overrides[control_plane.get_oauth_broker] = dependency(broker)
    control_plane.app.dependency_overrides[control_plane.get_vault] = dependency(vault)
    control_plane.app.dependency_overrides[control_plane.get_auth_store] = dependency(auth_store)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=control_plane.app),
            base_url="http://rally",
            follow_redirects=False,
        ) as client:
            callback = await client.post(
                "/auth/connector/callback",
                json={"state": "s" * 32, "code": "provider-code"},
                headers={"x-rally-oauth-binding": BROWSER_BINDING},
            )
            oversized = await client.post(
                "/auth/connector/callback",
                content=b"{" + (b"x" * (control_plane._MAX_CALLBACK_BODY_BYTES + 1)),
                headers={"content-type": "application/json"},
            )
    finally:
        control_plane.app.dependency_overrides.clear()

    fragment = parse_qs(urlsplit(callback.headers["location"]).fragment)
    assert fragment["rally-connection-status"] == ["provider-cleanup-required"]
    assert oversized.status_code == 413
    assert await vault.list(identity.uid) == []


@pytest.mark.asyncio
async def test_oauth_start_requires_disconnect_before_reconnect(monkeypatch):
    class NeverStartBroker:
        async def start(self, *args, **kwargs):
            raise AssertionError("provider OAuth must not start over an existing grant")

    identity = UserIdentity(uid="google-user-one", email="owner@example.com")
    vault = MemoryConnectorVault()
    previous = ConnectorSecret("previous-sealed-oauth-grant", "oauth_refresh_token")
    await vault.put(identity.uid, "hyperagent", previous)
    control_plane.app.dependency_overrides[control_plane.require_user] = lambda: identity
    control_plane.app.dependency_overrides[control_plane.get_vault] = lambda: vault
    control_plane.app.dependency_overrides[control_plane.get_oauth_broker] = lambda: (
        NeverStartBroker()
    )

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=control_plane.app),
            base_url="http://rally",
        ) as client:
            response = await client.post(
                "/v1/connections/hyperagent/oauth/start",
                json={"endpoint": None, "workflow_ids": []},
            )
    finally:
        control_plane.app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json()["detail"] == "disconnect_existing_connection"
    assert await vault.get_secret(identity.uid, "hyperagent") == previous


@pytest.mark.asyncio
async def test_separate_certification_timeout_is_recoverable_on_the_card():
    class TimeoutVerifier:
        async def verify(self, *args, **kwargs):
            raise TimeoutError

    identity = UserIdentity(uid="google-user-one", email="owner@example.com")
    vault = MemoryConnectorVault()
    material = make_oauth_material(
        endpoint="https://hyperagent.com/api/mcp",
        access_token="provider-access-token",
        refresh_token="provider-refresh-token",
        token_type="Bearer",
        expires_in=3600,
        scope="mcp:tools",
        client_id="rally-client",
        client_secret=None,
        token_endpoint="https://hyperagent.com/oauth/token",
        revocation_endpoint=None,
        token_auth_method="none",
        resource="https://hyperagent.com/api/mcp",
    )
    await vault.put(
        identity.uid,
        "hyperagent",
        ConnectorSecret(material, "oauth_refresh_token"),
    )
    await vault.mark(identity.uid, "hyperagent", status="verifying")
    control_plane.app.dependency_overrides[control_plane.require_user] = lambda: identity
    control_plane.app.dependency_overrides[control_plane.get_vault] = lambda: vault
    control_plane.app.dependency_overrides[control_plane.get_connection_verifier] = lambda: (
        TimeoutVerifier()
    )

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=control_plane.app),
            base_url="http://rally",
        ) as client:
            response = await client.post("/v1/connections/hyperagent/verify")
            listed = await client.get("/v1/connections")
    finally:
        control_plane.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "needs_attention"
    assert response.json()["error_code"] == "verification_timeout"
    assert listed.json()["connections"][0]["status"] == "needs_attention"
    assert await vault.get_secret(identity.uid, "hyperagent") is not None
