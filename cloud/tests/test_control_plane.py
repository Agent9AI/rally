import datetime as dt
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest

import control_plane
from auth_sessions import MemoryAuthSessionStore
from credential_vault import MemoryConnectorVault
from user_auth import UserIdentity


class PassingVerifier:
    async def verify(self, item, material, **kwargs):
        assert item.id == "github"
        assert material["credential"] == "extremely-secret"
        assert kwargs["allowed_workflow_ids"] == ()
        return 7


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
    assert "extremely-secret" not in stored.text
    assert "extremely-secret" not in listed.text
    assert disconnected.json()["disconnected"] is True
    assert await vault.get_secret("google-user-one", "github") is None


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
    assert account.json()["email"] == "owner@example.com"
    assert ambiguous.status_code == 401
    assert expired.status_code == 401
    assert expired_code is None
    assert code not in repr(auth_store._codes)
    assert session_token not in repr(auth_store._sessions)
    assert "signed-google-token" not in repr(auth_store._codes)
