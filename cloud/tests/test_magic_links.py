import base64
import datetime as dt
import json

import httpx
import pytest

import control_plane
from auth_sessions import MemoryAuthSessionStore
from magic_links import MemoryMagicLinkDeliveryQueue, MemoryMagicLinkStore
from user_auth import UserIdentity

NOW = dt.datetime.now(dt.UTC).replace(microsecond=0)
SIGNING_KEY = "test-magic-link-signing-key-that-is-long-enough-2026"


@pytest.mark.asyncio
async def test_signed_link_is_email_workspace_bound_short_lived_and_one_time():
    now = [NOW]
    store = MemoryMagicLinkStore(SIGNING_KEY, clock=lambda: now[0])
    identity = UserIdentity(uid="email:user", email="terry@agent9.dev", name="Terry")

    token = await store.issue(identity, "agent9-rally")

    assert token.startswith("ml1.")
    assert token not in repr(store._links)
    assert all(len(token_hash) == 64 for token_hash in store._links)
    assert await store.consume(token, "agent9-rally") is None
    await store.activate(token)
    assert await store.consume(token, "another-workspace") is None
    consumed = await store.consume(token, "agent9-rally")
    assert consumed == identity
    assert await store.consume(token, "agent9-rally") is None

    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert await store.consume(tampered, "agent9-rally") is None

    expiring = await store.issue(identity, "agent9-rally")
    await store.activate(expiring)
    now[0] += dt.timedelta(minutes=11)
    assert await store.consume(expiring, "agent9-rally") is None


@pytest.mark.asyncio
async def test_magic_link_rate_limit_is_durable_per_identity_and_requester():
    store = MemoryMagicLinkStore(SIGNING_KEY, clock=lambda: NOW)

    for _ in range(5):
        assert await store.reserve_request("terry@agent9.dev") is True
    assert await store.reserve_request("terry@agent9.dev") is False


@pytest.mark.asyncio
async def test_queued_delivery_is_deterministic_pending_then_active():
    store = MemoryMagicLinkStore(SIGNING_KEY, clock=lambda: NOW)
    identity = UserIdentity(uid="email:user", email="terry@agent9.dev")
    expiry = NOW + dt.timedelta(minutes=10)
    token = await store.issue(
        identity,
        "agent9-rally",
        delivery_id="A" * 32,
        expires_at=expiry,
    )
    retry = await store.issue(
        identity,
        "agent9-rally",
        delivery_id="A" * 32,
        expires_at=expiry,
    )
    assert retry == token
    assert await store.consume(token, "agent9-rally") is None
    await store.activate(token)
    assert await store.consume(token, "agent9-rally") == identity


class RecordingMailer:
    def __init__(self):
        self.deliveries = []

    async def send(self, email, token):
        self.deliveries.append((email, token))


@pytest.mark.asyncio
async def test_magic_link_request_is_nondisclosing_and_uses_existing_session_exchange(monkeypatch):
    now = [NOW]
    magic_store = MemoryMagicLinkStore(SIGNING_KEY, clock=lambda: now[0])
    auth_store = MemoryAuthSessionStore(clock=lambda: now[0])
    mailer = RecordingMailer()
    queue = MemoryMagicLinkDeliveryQueue(clock=lambda: now[0])
    monkeypatch.setenv("RALLY_ALLOWED_USER_EMAILS", "imterryim@gmail.com,terry@agent9.dev")
    monkeypatch.setenv("RALLY_WORKSPACE_ID", "agent9-rally")
    control_plane._magic_link_store = magic_store
    control_plane._magic_link_mailer = mailer
    control_plane._magic_link_queue = queue
    control_plane._auth_store = auth_store
    monkeypatch.setattr(control_plane, "_verify_pubsub_push", lambda _authorization: None)

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=control_plane.app),
            base_url="http://rally",
        ) as client:
            approved = await client.post(
                "/v1/auth/magic-link/request",
                json={"email": "  Terry@Agent9.dev "},
                headers={"x-forwarded-for": "203.0.113.42"},
            )
            unknown = await client.post(
                "/v1/auth/magic-link/request",
                json={"email": "unknown@example.com"},
                headers={"x-forwarded-for": "203.0.113.42"},
            )
            assert approved.status_code == unknown.status_code == 202
            assert approved.json() == unknown.json()
            assert "approved" in approved.json()["detail"].lower()
            assert [item.email for item in queue.deliveries] == ["terry@agent9.dev", ""]
            delivery = queue.deliveries[0]
            encoded = base64.b64encode(
                json.dumps(
                    {
                        "v": 1,
                        "delivery_id": delivery.delivery_id,
                        "email": delivery.email,
                        "workspace_id": delivery.workspace_id,
                        "expires_at": int(delivery.expires_at.timestamp()),
                    }
                ).encode()
            ).decode()
            pushed = await client.post(
                "/v1/internal/magic-link/deliver",
                json={"message": {"data": encoded}},
                headers={"Authorization": "Bearer test"},
            )
            assert pushed.status_code == 200
            assert len(mailer.deliveries) == 1
            email, token = mailer.deliveries[0]
            assert email == "terry@agent9.dev"

            consumed = await client.post(
                "/v1/auth/magic-link/consume", json={"token": token}
            )
            assert consumed.status_code == 200
            code = consumed.json()["login_code"]
            exchanged = await client.post("/v1/auth/exchange", json={"code": code})
            session = exchanged.json()["session_token"]
            account = await client.get("/v1/me", headers={"X-Rally-Session": session})
            monkeypatch.setenv("RALLY_ALLOWED_USER_EMAILS", "imterryim@gmail.com")
            revoked = await client.get("/v1/me", headers={"X-Rally-Session": session})
            replay = await client.post(
                "/v1/auth/magic-link/consume", json={"token": token}
            )
            oversized = await client.post(
                "/v1/auth/magic-link/request",
                content=b'{"email":"' + (b"a" * 5000) + b'"}',
                headers={"Content-Type": "application/json"},
            )

            async def oversized_chunks():
                yield b'{"email":"'
                yield b"a" * 5000
                yield b'"}'

            oversized_chunked = await client.post(
                "/v1/auth/magic-link/request",
                content=oversized_chunks(),
                headers={"Content-Type": "application/json"},
            )

        assert exchanged.status_code == 200
        assert account.status_code == 200
        assert account.json()["email"] == "terry@agent9.dev"
        assert account.json()["workspace_id"] == "agent9-rally"
        assert account.json()["uid"].startswith("email:")
        assert revoked.status_code == 403
        assert replay.status_code == 401
        assert oversized.status_code == 413
        assert oversized_chunked.status_code == 413
        assert token not in repr(magic_store._links)
        assert code not in repr(auth_store._codes)
        assert session not in repr(auth_store._sessions)
    finally:
        control_plane._magic_link_store = None
        control_plane._magic_link_mailer = None
        control_plane._magic_link_queue = None
        control_plane._auth_store = None
