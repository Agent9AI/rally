import datetime as dt

import httpx
import pytest

import connector_oauth
import control_plane
from connector_oauth import (
    ConnectorOAuthBroker,
    HostedOAuthError,
    MemoryOAuthFlowStore,
    OAuthFlow,
)
from user_auth import UserIdentity

NOW = dt.datetime(2026, 8, 31, 12, 0, tzinfo=dt.UTC)
STATE = "s" * 32
BINDING = "b" * 32


def flow(identity: UserIdentity, *, connector_id: str = "hyperagent") -> OAuthFlow:
    return OAuthFlow(
        identity=identity,
        connector_id=connector_id,
        endpoint="https://hyperagent.com/api/mcp",
        authorization_endpoint="https://hyperagent.com/oauth/authorize",
        token_endpoint="https://hyperagent.com/oauth/token",
        revocation_endpoint="https://hyperagent.com/oauth/revoke",
        client_id="rally-client",
        client_secret=None,
        token_auth_method="none",
        code_verifier="v" * 128,
        scope="threads:read approvals:read offline_access",
        resource="https://hyperagent.com/api/mcp",
        allowed_workflow_ids=(),
        issuer="https://hyperagent.com",
        browser_binding_hash=connector_oauth._browser_binding_hash(BINDING) or "",
        expires_at=NOW + dt.timedelta(minutes=10),
    )


class Snapshot:
    def __init__(self, value):
        self.value = value
        self.exists = value is not None

    def to_dict(self):
        return dict(self.value or {})


class Document:
    def __init__(self, collection, key):
        self.collection = collection
        self.key = key

    async def get(self, transaction=None):
        return Snapshot(self.collection.values.get(self.key))


class Collection:
    def __init__(self):
        self.values = {}

    def document(self, key):
        return Document(self, key)


class Transaction:
    def create(self, document, value):
        assert document.key not in document.collection.values
        document.collection.values[document.key] = dict(value)

    def set(self, document, value):
        document.collection.values[document.key] = dict(value)

    def delete(self, document):
        document.collection.values.pop(document.key, None)


class Firestore:
    def __init__(self):
        self.flows = Collection()

    def collection(self, name):
        assert name == "rally_connector_oauth_flows"
        return self.flows

    def transaction(self):
        return Transaction()


class Cipher:
    def seal(self, plaintext, associated_data):
        return {
            "schema": "rally.connector-oauth-flow/v1",
            "payload": plaintext.decode(),
            "associated_data": associated_data.decode(),
        }

    def open(self, envelope, associated_data):
        assert envelope["associated_data"] == associated_data.decode()
        return envelope["payload"].encode()


@pytest.mark.asyncio
async def test_memory_cancel_is_exactly_tenant_and_connector_bound():
    owner = UserIdentity(uid="owner", email="owner@example.com")
    other = UserIdentity(uid="other", email="other@example.com")
    store = MemoryOAuthFlowStore(clock=lambda: NOW)
    await store.put(STATE, flow(owner))

    assert await store.cancel(other.uid, "hyperagent") is False
    assert await store.cancel(owner.uid, "stripe") is False
    assert await store.consume(STATE, BINDING, "https://wrong.example") is None
    assert await store.cancel(owner.uid, "hyperagent") is True
    assert await store.cancel(owner.uid, "hyperagent") is False
    assert await store.consume(STATE, BINDING, "https://hyperagent.com") is None


@pytest.mark.asyncio
async def test_firestore_cancel_atomically_removes_only_exact_active_flow(monkeypatch):
    monkeypatch.setattr("google.cloud.firestore.async_transactional", lambda function: function)
    fake = Firestore()
    store = object.__new__(connector_oauth.FirestoreOAuthFlowStore)
    store.client = fake
    store.collection = fake.flows
    store.cipher = Cipher()
    owner = UserIdentity(uid="owner", email="owner@example.com")
    await store.put(STATE, flow(owner))

    assert await store.cancel("other", "hyperagent") is False
    assert len(fake.flows.values) == 2
    assert await store.cancel(owner.uid, "hyperagent") is True
    assert fake.flows.values == {}


@pytest.mark.asyncio
async def test_firestore_cancel_fails_closed_on_mismatched_active_record(monkeypatch):
    monkeypatch.setattr("google.cloud.firestore.async_transactional", lambda function: function)
    fake = Firestore()
    store = object.__new__(connector_oauth.FirestoreOAuthFlowStore)
    store.client = fake
    store.collection = fake.flows
    store.cipher = Cipher()
    owner = UserIdentity(uid="owner", email="owner@example.com")
    await store.put(STATE, flow(owner))
    active_key = connector_oauth._flow_active_key_for(owner.uid, "hyperagent")
    state_hash = fake.flows.values[active_key]["state_hash"]
    fake.flows.values[state_hash]["active_key"] = connector_oauth._flow_active_key_for(
        "other", "hyperagent"
    )

    with pytest.raises(HostedOAuthError, match="oauth_store_unavailable"):
        await store.cancel(owner.uid, "hyperagent")
    assert active_key in fake.flows.values
    assert state_hash in fake.flows.values


@pytest.mark.asyncio
async def test_authenticated_cancel_endpoint_never_touches_another_tenant():
    owner = UserIdentity(uid="owner", email="owner@example.com")
    other = UserIdentity(uid="other", email="other@example.com")
    store = MemoryOAuthFlowStore(clock=lambda: NOW)
    broker = ConnectorOAuthBroker(store, clock=lambda: NOW)
    await store.put(STATE, flow(owner))
    control_plane.app.dependency_overrides[control_plane.get_oauth_broker] = lambda: broker
    control_plane.app.dependency_overrides[control_plane.require_user] = lambda: other

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=control_plane.app),
            base_url="http://rally",
        ) as client:
            denied_by_binding = await client.delete("/v1/connections/hyperagent/oauth/pending")
            control_plane.app.dependency_overrides[control_plane.require_user] = lambda: owner
            cancelled = await client.delete("/v1/connections/hyperagent/oauth/pending")
            repeated = await client.delete("/v1/connections/hyperagent/oauth/pending")
    finally:
        control_plane.app.dependency_overrides.clear()

    assert denied_by_binding.status_code == 200
    assert denied_by_binding.json() == {
        "connector_id": "hyperagent",
        "cancelled": False,
    }
    assert cancelled.json() == {"connector_id": "hyperagent", "cancelled": True}
    assert repeated.json() == {"connector_id": "hyperagent", "cancelled": False}
