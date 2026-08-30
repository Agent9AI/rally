import httpx
import pytest

import control_plane
from credential_vault import MemoryConnectorVault
from user_auth import UserIdentity


@pytest.fixture
def web_control_plane():
    vault = MemoryConnectorVault()
    identity = UserIdentity(uid="google-user-one", email="owner@example.com", name="Owner")
    control_plane.app.dependency_overrides[control_plane.require_user] = lambda: identity
    control_plane.app.dependency_overrides[control_plane.get_vault] = lambda: vault
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
    assert stored.json()["status"] == "stored_unverified"
    assert stored.json()["verified"] is False
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

    assert unknown.status_code == 404
    assert oversized.status_code == 422
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
