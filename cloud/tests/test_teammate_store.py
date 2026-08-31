import datetime as dt

import httpx
import pytest

import control_plane
from teammate_store import (
    MemoryTeammateStore,
    TeammateConflict,
    TeammateStoreError,
    _record_from_mapping,
    public_teammate,
)
from user_auth import UserIdentity


def teammate_values(**changes):
    values = {
        "workspace_id": "workspace-one",
        "created_by_uid": "google-user-one",
        "name": "Rally Research",
        "role": "research",
        "custom_role": None,
        "human_owner_email": "owner@example.com",
        "email_local_part": "research",
        "email_domain": "ai.example.com",
        "email_provider": "company_subdomain",
        "connection_method": "dns",
        "email_status": "dns_required",
        "reachability": "selected_senders",
        "allowed_senders": ("owner@example.com",),
    }
    values.update(changes)
    return values


@pytest.mark.asyncio
async def test_memory_store_scopes_pending_customer_addresses_to_workspace():
    clock = lambda: dt.datetime(2026, 8, 31, 16, 0, tzinfo=dt.UTC)
    store = MemoryTeammateStore(clock=clock)
    created = await store.create(**teammate_values())

    assert [record.teammate_id for record in await store.list("workspace-one")] == [
        created.teammate_id
    ]
    assert await store.list("workspace-two") == []
    with pytest.raises(TeammateConflict):
        await store.create(**teammate_values())

    second_workspace = await store.create(
        **teammate_values(
            workspace_id="workspace-two",
            created_by_uid="google-user-two",
        )
    )
    assert second_workspace.email_address == created.email_address


@pytest.mark.asyncio
async def test_rally_trial_address_is_globally_unique():
    store = MemoryTeammateStore()
    trial = teammate_values(
        email_provider="rally_trial",
        connection_method="trial",
        email_status="trial_activation_required",
        email_domain="updates.agent9.dev",
    )
    await store.create(**trial)

    with pytest.raises(TeammateConflict):
        await store.create(
            **{
                **trial,
                "workspace_id": "workspace-two",
                "created_by_uid": "google-user-two",
            }
        )


@pytest.mark.asyncio
async def test_public_teammate_omits_workspace_and_google_subject():
    store = MemoryTeammateStore()
    record = await store.create(**teammate_values())
    public = public_teammate(record)

    assert public["email"]["address"] == "research@ai.example.com"
    assert public["email"]["status"] == "dns_required"
    assert "workspace_id" not in public
    assert "created_by_uid" not in public
    assert "google-user-one" not in str(public)
    with pytest.raises(TeammateStoreError, match="stored teammate record is invalid"):
        _record_from_mapping({**record.__dict__, "allowed_senders": "owner@example.com"})


@pytest.fixture
def teammate_control_plane(monkeypatch):
    store = MemoryTeammateStore()
    identity = UserIdentity(uid="google-user-one", email="owner@example.com", name="Owner")
    control_plane.app.dependency_overrides[control_plane.require_user] = lambda: identity
    control_plane.app.dependency_overrides[control_plane.get_teammate_store] = lambda: store
    monkeypatch.setenv("RALLY_WORKSPACE_ID", "workspace-one")
    monkeypatch.setenv("RALLY_TRIAL_EMAIL_DOMAIN", "updates.agent9.dev")
    monkeypatch.setenv("RALLY_PILOT_EMAIL_ADDRESS", "rally@updates.agent9.dev")
    yield httpx.ASGITransport(app=control_plane.app), store
    control_plane.app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_teammate_routes_require_an_authenticated_workspace_user():
    transport = httpx.ASGITransport(app=control_plane.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://rally") as client:
        providers = await client.get("/v1/email-provider-options")
        listed = await client.get("/v1/teammates")
        created = await client.post("/v1/teammates", json={})

    assert providers.status_code == 401
    assert listed.status_code == 401
    assert created.status_code == 401


@pytest.mark.asyncio
async def test_teammate_onboarding_persists_identity_and_sender_policy(
    teammate_control_plane,
):
    transport, _ = teammate_control_plane
    payload = {
        "name": "Rally Research",
        "role": "research",
        "human_owner_email": "Owner@Example.com",
        "email_local_part": "Research",
        "email_domain": "AI.Example.com.",
        "email_provider": "company_subdomain",
        "connection_method": "dns",
        "reachability": "approved_domains",
        "allowed_senders": ["@example.com", "analyst@example.com"],
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://rally") as client:
        created = await client.post("/v1/teammates", json=payload)
        listed = await client.get("/v1/teammates")

    assert created.status_code == 201
    body = created.json()
    assert body["email"] == {
        "address": "research@ai.example.com",
        "local_part": "research",
        "domain": "ai.example.com",
        "provider": "company_subdomain",
        "connection_method": "dns",
        "status": "dns_required",
    }
    assert body["allowed_senders"] == [
        "@example.com",
        "analyst@example.com",
        "owner@example.com",
    ]
    assert listed.json()["teammates"] == [body]


@pytest.mark.asyncio
async def test_trial_is_explicit_and_duplicate_addresses_fail_closed(
    teammate_control_plane,
):
    transport, _ = teammate_control_plane
    payload = {
        "name": "Rally Trial",
        "role": "general",
        "human_owner_email": "owner@example.com",
        "email_local_part": "trial-team",
        "email_provider": "rally_trial",
        "connection_method": "trial",
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://rally") as client:
        first = await client.post("/v1/teammates", json=payload)
        duplicate = await client.post("/v1/teammates", json=payload)

    assert first.status_code == 201
    assert first.json()["email"]["address"] == "trial-team@updates.agent9.dev"
    assert first.json()["email"]["status"] == "trial_activation_required"
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "email address is already assigned"


@pytest.mark.asyncio
async def test_invalid_domain_and_provider_method_are_rejected_without_echo(
    teammate_control_plane,
):
    transport, _ = teammate_control_plane
    base = {
        "name": "Rally Research",
        "role": "research",
        "human_owner_email": "owner@example.com",
        "email_local_part": "research",
        "email_domain": "ai.example.com",
        "email_provider": "google_workspace",
        "connection_method": "oauth",
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://rally") as client:
        wrong_method = await client.post(
            "/v1/teammates",
            json={**base, "connection_method": "api_key"},
        )
        unsafe_domain = await client.post(
            "/v1/teammates",
            json={**base, "email_domain": "https://secret.example.com/path"},
        )
        reserved_domain = await client.post(
            "/v1/teammates",
            json={
                **base,
                "email_provider": "company_subdomain",
                "connection_method": "dns",
                "email_domain": "updates.agent9.dev",
            },
        )
        invalid_local_part = await client.post(
            "/v1/teammates",
            json={**base, "email_local_part": "research..team"},
        )
        invalid_trimmed_name = await client.post(
            "/v1/teammates",
            json={**base, "name": " a"},
        )

    assert wrong_method.status_code == 422
    assert unsafe_domain.status_code == 422
    assert reserved_domain.status_code == 422
    assert invalid_local_part.status_code == 422
    assert invalid_trimmed_name.status_code == 422
    assert wrong_method.json() == {"detail": "invalid request"}
    assert reserved_domain.json() == {"detail": "email domain is reserved for Rally trials"}
    assert "secret.example.com" not in unsafe_domain.text


@pytest.mark.parametrize(
    "owner",
    [".owner@example.com", "owner.@example.com", "owner..admin@example.com"],
)
@pytest.mark.asyncio
async def test_invalid_human_owner_dot_atoms_fail_closed(
    teammate_control_plane,
    owner,
):
    transport, _ = teammate_control_plane
    payload = {
        "name": "Rally Research",
        "role": "research",
        "human_owner_email": owner,
        "email_local_part": "research",
        "email_domain": "ai.example.com",
        "email_provider": "company_subdomain",
        "connection_method": "dns",
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://rally") as client:
        response = await client.post("/v1/teammates", json=payload)

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid request"}


@pytest.mark.asyncio
async def test_provider_catalog_distinguishes_planning_from_live_activation(
    teammate_control_plane,
):
    transport, _ = teammate_control_plane
    async with httpx.AsyncClient(transport=transport, base_url="http://rally") as client:
        response = await client.get("/v1/email-provider-options")

    assert response.status_code == 200
    providers = {item["id"]: item for item in response.json()["providers"]}
    assert providers["resend"]["connection_methods"] == ["oauth", "api_key"]
    assert providers["resend"]["activation_available"] is False
    assert providers["cloudflare_email"]["connection_methods"] == ["api_key"]
    assert providers["cloudflare_email"]["resulting_status"] == "configuration_required"
    assert providers["company_subdomain"]["setup_available"] is True
    assert providers["company_subdomain"]["activation_available"] is False
    assert providers["company_subdomain"]["group"] == "company"
    assert providers["company_subdomain"]["recommended"] is True
    assert providers["resend"]["group"] == "infrastructure"
    assert providers["rally_trial"]["group"] == "trial"
    assert providers["rally_trial"]["resulting_status"] == "trial_activation_required"
    assert response.json()["trial_domain"] == "updates.agent9.dev"
    assert response.json()["pilot_address"] == "rally@updates.agent9.dev"
