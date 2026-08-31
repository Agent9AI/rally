import asyncio
import datetime as dt
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest

import control_plane
from auth_sessions import MemoryAuthSessionStore
from connector_oauth import HostedOAuthError
from credential_vault import (
    ConnectionRecord,
    ConnectorSecret,
    MemoryConnectorVault,
    certified_manifest_sha256,
)
from hosted_connectors import ConnectionCertification, make_oauth_material
from user_auth import UserIdentity


class PassingVerifier:
    async def verify(self, item, material, **kwargs):
        assert item.id == "github"
        assert material["credential"] == "extremely-secret"
        assert kwargs["allowed_workflow_ids"] == ()
        manifest = tuple(
            (name, "a" * 64)
            for name in (
                "get_me",
                "get_file_contents",
                "list_branches",
                "list_commits",
                "list_releases",
                "list_tags",
                "issue_read",
            )
        )
        return ConnectionCertification(
            tool_count=7,
            canary_tool="get_me",
            tool_schema_sha256="a" * 64,
            certified_tools=manifest,
            certified_manifest_sha256=certified_manifest_sha256(manifest),
        )


class FailingRevoker:
    async def revoke(self, item, stored_material):
        assert item.id == "hyperagent"
        assert stored_material == "sealed-oauth-material"
        raise HostedOAuthError("oauth_revocation_failed")


class PassingRevoker:
    def __init__(self, vault):
        self.vault = vault
        self.calls = []

    async def revoke(self, item, stored_material):
        assert await self.vault.get_secret("google-user-one", item.id) is not None
        self.calls.append((item.id, stored_material))
        return True


@pytest.fixture
def web_control_plane():
    vault = MemoryConnectorVault()
    identity = UserIdentity(uid="google-user-one", email="owner@example.com", name="Owner")
    control_plane.app.dependency_overrides[control_plane.require_user] = lambda: identity
    control_plane.app.dependency_overrides[control_plane.get_vault] = lambda: vault
    control_plane.app.dependency_overrides[control_plane.get_connection_verifier] = lambda: (
        PassingVerifier()
    )
    yield httpx.ASGITransport(app=control_plane.app), vault
    control_plane.app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_account_and_connection_round_trip_never_echoes_secret(web_control_plane):
    transport, vault = web_control_plane
    async with httpx.AsyncClient(transport=transport, base_url="http://rally") as client:
        account = await client.get("/v1/me")
        stored = await client.put(
            "/v1/connections/github",
            json={"credential": "extremely-secret", "kind": "bearer_token"},
        )
        listed = await client.get("/v1/connections")
        disconnected = await client.delete("/v1/connections/github")

    assert account.status_code == 200
    assert account.json()["uid"] == "google-user-one"
    assert stored.status_code == 200
    assert stored.json()["status"] == "ready"
    assert stored.json()["verified"] is True
    assert stored.json()["tool_count"] == 7
    assert stored.json()["certification"]["live_read"] is True
    assert stored.json()["certification"]["canary_tool"] == "get_me"
    assert "extremely-secret" not in stored.text
    assert "extremely-secret" not in listed.text
    assert disconnected.json()["disconnected"] is True
    assert await vault.get_secret("google-user-one", "github") is None


@pytest.mark.asyncio
async def test_manual_connection_must_disconnect_before_replacement(web_control_plane):
    transport, vault = web_control_plane
    async with httpx.AsyncClient(transport=transport, base_url="http://rally") as client:
        first = await client.put(
            "/v1/connections/github",
            json={"credential": "extremely-secret", "kind": "bearer_token"},
        )
        replacement = await client.put(
            "/v1/connections/github",
            json={"credential": "replacement-secret", "kind": "bearer_token"},
        )

    assert first.status_code == 200
    assert replacement.status_code == 409
    assert replacement.json()["detail"] == "disconnect_existing_connection"
    retained = await vault.get_secret("google-user-one", "github")
    assert retained is not None
    assert "extremely-secret" in retained.value
    assert "replacement-secret" not in retained.value


def test_legacy_ready_record_projects_as_needs_attention_until_recertified():
    legacy = ConnectionRecord(
        connector_id="github",
        credential_kind="bearer_token",
        status="ready",
        created_at="2026-08-29T00:00:00Z",
        updated_at="2026-08-29T00:01:00Z",
        tool_count=7,
        verified_at="2026-08-29T00:01:00Z",
    )

    projected = control_plane.public_connection(legacy)

    assert projected["status"] == "needs_attention"
    assert projected["verified"] is False
    assert projected["error_code"] == "recertification_required"
    assert projected["certification"] is None


@pytest.mark.asyncio
async def test_oauth_revocation_failure_retains_encrypted_credential(
    web_control_plane,
    monkeypatch,
):
    transport, vault = web_control_plane
    secret = ConnectorSecret("sealed-oauth-material", "oauth_refresh_token")
    await vault.put("google-user-one", "hyperagent", secret)
    await vault.mark(
        "google-user-one",
        "hyperagent",
        status="ready",
        tool_count=1,
        canary_tool="list_agents",
        tool_schema_sha256="a" * 64,
        proof_version="rally.connection-certification/v1",
        certified_tools=(("list_agents", "a" * 64),),
        certified_manifest_sha256=certified_manifest_sha256((("list_agents", "a" * 64),)),
    )
    monkeypatch.setattr(control_plane, "get_oauth_broker", lambda: FailingRevoker())

    async with httpx.AsyncClient(transport=transport, base_url="http://rally") as client:
        response = await client.delete("/v1/connections/hyperagent")

    assert response.status_code == 502
    assert response.json()["detail"] == (
        "provider revocation did not complete; the connection remains sealed"
    )
    assert await vault.get_secret("google-user-one", "hyperagent") == secret
    [retained] = await vault.list("google-user-one")
    assert retained.status == "needs_attention"
    assert retained.error_code == "disconnect_pending"
    assert retained.proof_version is None


@pytest.mark.asyncio
async def test_successful_oauth_revocation_deletes_encrypted_credential(
    web_control_plane,
    monkeypatch,
):
    transport, vault = web_control_plane
    await vault.put(
        "google-user-one",
        "hyperagent",
        ConnectorSecret("sealed-oauth-material", "oauth_refresh_token"),
    )
    broker = PassingRevoker(vault)
    monkeypatch.setattr(control_plane, "get_oauth_broker", lambda: broker)

    async with httpx.AsyncClient(transport=transport, base_url="http://rally") as client:
        response = await client.delete("/v1/connections/hyperagent")

    assert response.status_code == 200
    assert response.json() == {
        "connector_id": "hyperagent",
        "disconnected": True,
        "provider_revoked": True,
        "provider_action_required": False,
    }
    assert broker.calls == [("hyperagent", "sealed-oauth-material")]
    assert await vault.get_secret("google-user-one", "hyperagent") is None


@pytest.mark.asyncio
async def test_stale_verification_cannot_resurrect_disconnect_pending_connection(
    web_control_plane,
    monkeypatch,
):
    class DeferredVerifier:
        def __init__(self):
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def verify(self, *args, **kwargs):
            del args, kwargs
            self.started.set()
            await self.release.wait()
            manifest = (("list_agents", "a" * 64),)
            return ConnectionCertification(
                tool_count=1,
                canary_tool="list_agents",
                tool_schema_sha256="a" * 64,
                certified_tools=manifest,
                certified_manifest_sha256=certified_manifest_sha256(manifest),
            )

    class DeferredFailingRevoker:
        async def revoke(self, item, stored_material):
            del item, stored_material
            raise HostedOAuthError("oauth_revocation_failed")

    transport, vault = web_control_plane
    material = make_oauth_material(
        endpoint="https://hyperagent.com/api/mcp",
        access_token="provider-access",
        refresh_token="provider-refresh",
        token_type="Bearer",
        expires_in=3600,
        scope="threads:read approvals:read offline_access",
        client_id="client-id",
        client_secret=None,
        token_endpoint="https://hyperagent.com/oauth/token",
        revocation_endpoint="https://hyperagent.com/oauth/revoke",
        token_auth_method="none",
        resource="https://hyperagent.com/api/mcp",
    )
    await vault.put(
        "google-user-one",
        "hyperagent",
        ConnectorSecret(material, "oauth_refresh_token"),
    )
    verifier = DeferredVerifier()
    control_plane.app.dependency_overrides[control_plane.get_connection_verifier] = lambda: verifier
    monkeypatch.setattr(control_plane, "get_oauth_broker", lambda: DeferredFailingRevoker())

    async with httpx.AsyncClient(transport=transport, base_url="http://rally") as client:
        verifying = asyncio.create_task(client.post("/v1/connections/hyperagent/verify"))
        await verifier.started.wait()
        disconnected = await client.delete("/v1/connections/hyperagent")
        verifier.release.set()
        verified = await verifying

    assert disconnected.status_code == 502
    assert verified.status_code == 409
    assert verified.json()["detail"] == "disconnect_pending"
    [retained] = await vault.list("google-user-one")
    assert retained.error_code == "disconnect_pending"
    assert retained.proof_version is None


@pytest.mark.asyncio
async def test_unknown_connector_and_oversized_credentials_fail(web_control_plane):
    transport, _ = web_control_plane
    async with httpx.AsyncClient(transport=transport, base_url="http://rally") as client:
        unknown = await client.put(
            "/v1/connections/not-real",
            json={"credential": "secret", "kind": "api_key"},
        )
        oversized = await client.put(
            "/v1/connections/github",
            json={"credential": "x" * 65537, "kind": "api_key"},
        )
        wrong_scheme = await client.put(
            "/v1/connections/github",
            json={
                "credential": "secret",
                "kind": "bearer_token",
                "scheme": "basic",
                "account": "owner@example.com",
            },
        )

    assert unknown.status_code == 404
    assert oversized.status_code == 422
    assert wrong_scheme.status_code == 422
    assert wrong_scheme.json()["detail"] == "credential_scheme_not_allowed"
    assert "x" * 100 not in oversized.text


@pytest.mark.asyncio
async def test_control_plane_is_no_store_and_denies_unauthenticated_requests(monkeypatch):
    control_plane.app.dependency_overrides.clear()
    monkeypatch.delenv("RALLY_GOOGLE_WEB_CLIENT_IDS", raising=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=control_plane.app),
        base_url="http://rally",
    ) as client:
        denied = await client.get("/v1/me")

    assert denied.status_code == 401
    assert denied.headers["cache-control"] == "no-store"
    assert denied.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"

    now = [dt.datetime(2026, 8, 30, 16, 0, tzinfo=dt.UTC)]
    auth_store = MemoryAuthSessionStore(clock=lambda: now[0])
    identity = UserIdentity(uid="google-user-one", email="owner@example.com", name="Owner")
    monkeypatch.setattr(control_plane, "_auth_store", auth_store)
    monkeypatch.setattr(
        control_plane,
        "verify_google_id_token",
        lambda token: identity if token == "signed-google-token" else None,
    )
    monkeypatch.setenv("RALLY_ADMIN_RETURN_URL", "https://rally.agent9.dev/admin/")
    form = urlencode({"credential": "signed-google-token", "g_csrf_token": "csrf-value"})

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=control_plane.app),
            base_url="http://rally",
            follow_redirects=False,
        ) as client:
            csrf_denied = await client.post(
                "/auth/google/callback",
                content=form,
                headers={
                    "content-type": "application/x-www-form-urlencoded",
                    "cookie": "g_csrf_token=wrong-value",
                },
            )
            callback = await client.post(
                "/auth/google/callback",
                content=form,
                headers={
                    "content-type": "application/x-www-form-urlencoded",
                    "cookie": "g_csrf_token=csrf-value",
                },
            )
            code = parse_qs(urlsplit(callback.headers["location"]).fragment)["rally-login-code"][0]
            assert code not in repr(auth_store._codes)
            assert all(len(token_hash) == 64 for token_hash in auth_store._codes)
            exchanged = await client.post("/v1/auth/exchange", json={"code": code})
            session_token = exchanged.json()["session_token"]
            replayed = await client.post("/v1/auth/exchange", json={"code": code})
            account = await client.get("/v1/me", headers={"X-Rally-Session": session_token})
            signed_out = await client.post(
                "/v1/auth/logout",
                headers={"X-Rally-Session": session_token},
            )
            revoked = await client.get(
                "/v1/me",
                headers={"X-Rally-Session": session_token},
            )
            ambiguous = await client.get(
                "/v1/me",
                headers={
                    "X-Rally-ID-Token": "signed-google-token",
                    "X-Rally-Session": session_token,
                },
            )
            now[0] += dt.timedelta(minutes=31)
            expired = await client.get("/v1/me", headers={"X-Rally-Session": session_token})
            expiring_code = await auth_store.issue_code(identity)
            assert expiring_code not in repr(auth_store._codes)
            now[0] += dt.timedelta(minutes=3)
            expired_code = await auth_store.exchange_code(expiring_code)
    finally:
        control_plane._auth_store = None

    assert csrf_denied.status_code == 400
    assert callback.status_code == 303
    assert callback.headers["location"].startswith(
        "https://rally.agent9.dev/admin/#rally-login-code="
    )
    assert callback.headers["cache-control"] == "no-store"
    assert exchanged.status_code == 200
    assert exchanged.json()["expires_in"] == 1800
    assert exchanged.json()["account"]["uid"] == "google-user-one"
    assert replayed.status_code == 401
    assert account.status_code == 200
    assert signed_out.status_code == 200
    assert signed_out.json() == {"signed_out": True}
    assert revoked.status_code == 401
    assert account.json()["email"] == "owner@example.com"
    assert ambiguous.status_code == 401
    assert expired.status_code == 401
    assert expired_code is None
    assert code not in repr(auth_store._codes)
    assert session_token not in repr(auth_store._sessions)
    assert "signed-google-token" not in repr(auth_store._codes)
