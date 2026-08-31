"""Allowlisted, one-time company-email authentication for Rally."""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Final, Protocol

from google.api_core.exceptions import AlreadyExists, GoogleAPICallError

from user_auth import UserIdentity


class MagicLinkError(RuntimeError):
    """Magic-link state or delivery could not be completed safely."""


_TOKEN: Final = re.compile(
    r"^ml1\.[A-Za-z0-9_-]{43}\.[0-9]{10}\.[A-Za-z0-9_-]{24}\.[A-Za-z0-9_-]{43}$"
)
_LINK_TTL_SECONDS: Final = 10 * 60
_RATE_WINDOW_SECONDS: Final = 15 * 60
_EMAIL_RATE_LIMIT: Final = 5
_GLOBAL_RATE_LIMIT: Final = 10_000


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sign(secret: bytes, value: str) -> bytes:
    return hmac.new(secret, value.encode("utf-8"), hashlib.sha256).digest()


def _identity(record: dict[str, Any]) -> UserIdentity | None:
    uid = record.get("uid")
    email = record.get("email")
    if not isinstance(uid, str) or not uid or not isinstance(email, str) or not email:
        return None
    return UserIdentity(
        uid=uid,
        email=email,
        name=record.get("name") if isinstance(record.get("name"), str) else None,
        picture=None,
        hosted_domain=(
            record.get("hosted_domain")
            if isinstance(record.get("hosted_domain"), str)
            else None
        ),
    )


class MagicLinkStore(Protocol):
    async def reserve_request(self, email: str) -> bool: ...

    async def issue(
        self,
        identity: UserIdentity,
        workspace_id: str,
        *,
        delivery_id: str | None = None,
        expires_at: dt.datetime | None = None,
    ) -> str: ...

    async def activate(self, token: str) -> None: ...

    async def consume(self, token: str, workspace_id: str) -> UserIdentity | None: ...

    async def invalidate(self, token: str) -> None: ...


@dataclass(frozen=True)
class MagicLinkDelivery:
    delivery_id: str
    email: str
    workspace_id: str
    expires_at: dt.datetime


class MagicLinkDeliveryQueue(Protocol):
    async def publish(self, email: str | None, workspace_id: str) -> None: ...


class MemoryMagicLinkDeliveryQueue:
    """Deterministic test queue; production uses Google Pub/Sub."""

    def __init__(self, *, clock: Any = _utc_now) -> None:
        self._clock = clock
        self.deliveries: list[MagicLinkDelivery] = []

    async def publish(self, email: str | None, workspace_id: str) -> None:
        self.deliveries.append(
            MagicLinkDelivery(
                delivery_id=secrets.token_urlsafe(24),
                email=email or "",
                workspace_id=workspace_id,
                expires_at=self._clock() + dt.timedelta(seconds=_LINK_TTL_SECONDS),
            )
        )


class PubSubMagicLinkDeliveryQueue:
    """Durable delivery queue; no usable sign-in token enters Pub/Sub."""

    def __init__(
        self,
        project_id: str,
        topic_id: str,
        publisher: Any | None = None,
    ) -> None:
        if not project_id or not topic_id:
            raise MagicLinkError("magic-link delivery queue is not configured")
        if publisher is None:
            from google.cloud import pubsub_v1

            publisher = pubsub_v1.PublisherClient()
        self.publisher = publisher
        self.topic_path = self.publisher.topic_path(project_id, topic_id)

    async def publish(self, email: str | None, workspace_id: str) -> None:
        payload = {
            "v": 1,
            "delivery_id": secrets.token_urlsafe(24),
            "email": email or "",
            "workspace_id": workspace_id,
            "expires_at": int(
                (_utc_now() + dt.timedelta(seconds=_LINK_TTL_SECONDS)).timestamp()
            ),
        }
        try:
            future = self.publisher.publish(
                self.topic_path,
                json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            )
            await asyncio.to_thread(lambda: future.result(timeout=10))
        except Exception as exc:
            raise MagicLinkError("could not queue sign-in delivery") from exc


def decode_magic_link_delivery(encoded: str, *, now: dt.datetime | None = None) -> MagicLinkDelivery:
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > 2048:
            raise ValueError("message is too large")
        payload = json.loads(raw)
        delivery_id = payload["delivery_id"]
        email = payload["email"]
        workspace_id = payload["workspace_id"]
        expires = int(payload["expires_at"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MagicLinkError("invalid sign-in delivery message") from exc
    if (
        payload.get("v") != 1
        or not isinstance(delivery_id, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{32}", delivery_id)
        or not isinstance(email, str)
        or len(email) > 320
        or not isinstance(workspace_id, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,95}", workspace_id)
    ):
        raise MagicLinkError("invalid sign-in delivery message")
    current = now or _utc_now()
    expires_at = dt.datetime.fromtimestamp(expires, tz=dt.UTC)
    if expires_at <= current or expires_at > current + dt.timedelta(seconds=_LINK_TTL_SECONDS):
        raise MagicLinkError("sign-in delivery expired")
    return MagicLinkDelivery(delivery_id, email, workspace_id, expires_at)


class MemoryMagicLinkStore:
    """Test/development store with the same token and replay contract as Firestore."""

    def __init__(self, signing_key: str, *, clock: Any = _utc_now) -> None:
        self._secret = _validated_secret(signing_key)
        self._clock = clock
        self._links: dict[str, dict[str, Any]] = {}
        self._rates: dict[str, tuple[int, int]] = {}
        self._lock = asyncio.Lock()

    def _rate_key(self, kind: str, value: str, window: int) -> str:
        return _b64url(_sign(self._secret, f"rate\0{kind}\0{value}\0{window}"))

    async def reserve_request(self, email: str) -> bool:
        window = int(self._clock().timestamp()) // _RATE_WINDOW_SECONDS
        keys = (
            (self._rate_key("email", email, window), _EMAIL_RATE_LIMIT),
            (self._rate_key("global", "all", window), _GLOBAL_RATE_LIMIT),
        )
        async with self._lock:
            allowed = all(self._rates.get(key, (window, 0))[1] < limit for key, limit in keys)
            for key, _ in keys:
                _, count = self._rates.get(key, (window, 0))
                self._rates[key] = (window, count + 1)
            return allowed

    async def issue(
        self,
        identity: UserIdentity,
        workspace_id: str,
        *,
        delivery_id: str | None = None,
        expires_at: dt.datetime | None = None,
    ) -> str:
        token, token_hash, expires_at = _new_token(
            self._secret,
            identity.email,
            workspace_id,
            self._clock(),
            delivery_id=delivery_id,
            expires_at=expires_at,
        )
        async with self._lock:
            self._links.setdefault(
                token_hash,
                {
                    **asdict(identity),
                    "workspace_id": workspace_id,
                    "expires_at": expires_at,
                    "active_at": None,
                    "disabled_at": None,
                    "consumed_at": None,
                },
            )
        return token

    async def activate(self, token: str) -> None:
        token_hash = _sha256(token)
        async with self._lock:
            record = self._links.get(token_hash)
            if not record or record.get("consumed_at") is not None:
                raise MagicLinkError("could not activate sign-in link")
            record["active_at"] = self._clock()
            record["disabled_at"] = None

    async def consume(self, token: str, workspace_id: str) -> UserIdentity | None:
        token_hash = _validated_token_hash(self._secret, token, self._clock())
        if token_hash is None:
            return None
        async with self._lock:
            record = self._links.get(token_hash)
            if (
                not record
                or record.get("workspace_id") != workspace_id
                or not isinstance(record.get("active_at"), dt.datetime)
                or record.get("disabled_at") is not None
                or record.get("consumed_at") is not None
                or not isinstance(record.get("expires_at"), dt.datetime)
                or record["expires_at"] <= self._clock()
            ):
                return None
            if not _binding_matches(self._secret, token, record["email"], workspace_id):
                return None
            record["consumed_at"] = self._clock()
            return _identity(record)

    async def invalidate(self, token: str) -> None:
        token_hash = _sha256(token)
        async with self._lock:
            record = self._links.get(token_hash)
            if record and record.get("consumed_at") is None:
                record["active_at"] = None
                record["disabled_at"] = self._clock()


class FirestoreMagicLinkStore:
    """Durable signed-link store; documents are indexed only by token hashes."""

    def __init__(
        self,
        project_id: str,
        signing_key: str,
        firestore_client: Any | None = None,
    ) -> None:
        if not project_id:
            raise MagicLinkError("Google Cloud project is not configured")
        self._secret = _validated_secret(signing_key)
        if firestore_client is None:
            from google.cloud import firestore

            firestore_client = firestore.AsyncClient(project=project_id)
        self.client = firestore_client
        self.links = self.client.collection("rally_magic_links")
        self.rates = self.client.collection("rally_magic_link_rate_limits")

    def _rate_key(self, kind: str, value: str, window: int) -> str:
        return _b64url(_sign(self._secret, f"rate\0{kind}\0{value}\0{window}"))

    async def reserve_request(self, email: str) -> bool:
        from google.cloud import firestore

        now = _utc_now()
        window = int(now.timestamp()) // _RATE_WINDOW_SECONDS
        specs = (
            (self.rates.document(self._rate_key("email", email, window)), _EMAIL_RATE_LIMIT),
            (self.rates.document(self._rate_key("global", "all", window)), _GLOBAL_RATE_LIMIT),
        )

        @firestore.async_transactional
        async def reserve(transaction: Any) -> bool:
            snapshots = [await reference.get(transaction=transaction) for reference, _ in specs]
            counts = [int((snapshot.to_dict() or {}).get("count", 0)) for snapshot in snapshots]
            allowed = all(count < limit for count, (_, limit) in zip(counts, specs))
            for count, (reference, _) in zip(counts, specs):
                transaction.set(
                    reference,
                    {
                        "count": count + 1,
                        "window": window,
                        "expires_at": now + dt.timedelta(days=1),
                    },
                )
            return allowed

        try:
            return await reserve(self.client.transaction())
        except Exception as exc:
            raise MagicLinkError("could not enforce sign-in rate limit") from exc

    async def issue(
        self,
        identity: UserIdentity,
        workspace_id: str,
        *,
        delivery_id: str | None = None,
        expires_at: dt.datetime | None = None,
    ) -> str:
        token, token_hash, expires_at = _new_token(
            self._secret,
            identity.email,
            workspace_id,
            _utc_now(),
            delivery_id=delivery_id,
            expires_at=expires_at,
        )
        try:
            await self.links.document(token_hash).create(
                {
                    **asdict(identity),
                    "workspace_id": workspace_id,
                    "created_at": _utc_now(),
                    "expires_at": expires_at,
                    "active_at": None,
                    "disabled_at": None,
                    "consumed_at": None,
                }
            )
        except AlreadyExists:
            # Pub/Sub is at-least-once. A delivery ID deterministically derives
            # the same token, so a retry resumes the existing pending record.
            if delivery_id is None:
                raise MagicLinkError("could not create sign-in link") from None
        except Exception as exc:
            raise MagicLinkError("could not create sign-in link") from exc
        return token

    async def activate(self, token: str) -> None:
        try:
            await self.links.document(_sha256(token)).update(
                {"active_at": _utc_now(), "disabled_at": None}
            )
        except Exception as exc:
            raise MagicLinkError("could not activate sign-in link") from exc

    async def consume(self, token: str, workspace_id: str) -> UserIdentity | None:
        from google.cloud import firestore

        now = _utc_now()
        token_hash = _validated_token_hash(self._secret, token, now)
        if token_hash is None:
            return None
        reference = self.links.document(token_hash)

        @firestore.async_transactional
        async def consume_once(transaction: Any) -> UserIdentity | None:
            snapshot = await reference.get(transaction=transaction)
            if not snapshot.exists:
                return None
            record = snapshot.to_dict() or {}
            if (
                record.get("workspace_id") != workspace_id
                or not isinstance(record.get("active_at"), dt.datetime)
                or record.get("disabled_at") is not None
                or record.get("consumed_at") is not None
                or not isinstance(record.get("expires_at"), dt.datetime)
                or record["expires_at"] <= now
                or not _binding_matches(
                    self._secret, token, str(record.get("email", "")), workspace_id
                )
            ):
                return None
            identity = _identity(record)
            if identity is None:
                return None
            transaction.update(reference, {"consumed_at": now})
            return identity

        try:
            return await consume_once(self.client.transaction())
        except Exception as exc:
            raise MagicLinkError("could not consume sign-in link") from exc

    async def invalidate(self, token: str) -> None:
        try:
            await self.links.document(_sha256(token)).update(
                {"active_at": None, "disabled_at": _utc_now()}
            )
        except GoogleAPICallError as exc:
            raise MagicLinkError("could not disable sign-in link") from exc


class ResendMagicLinkMailer:
    """Transactional delivery with both text and HTML bodies."""

    def __init__(self, api_key: str, sender: str, admin_url: str) -> None:
        if not api_key or any(character.isspace() for character in api_key):
            raise MagicLinkError("Resend is not configured")
        self.api_key = api_key
        self.sender = sender
        self.admin_url = admin_url.rstrip("/") + "/"

    async def send(self, email: str, token: str) -> None:
        link = f"{self.admin_url}#rally-magic-link={token}"
        safe_link = html.escape(link, quote=True)
        payload = {
            "from": self.sender,
            "to": [email],
            "subject": "Your secure Rally sign-in link",
            "text": (
                "Sign in to your Rally workspace:\n\n"
                f"{link}\n\n"
                "This one-time link expires in 10 minutes. If you did not request it, ignore this email."
            ),
            "html": (
                '<div style="font-family:Arial,sans-serif;color:#10233f;line-height:1.55">'
                '<p style="color:#246bfd;font-size:12px;font-weight:700;letter-spacing:.08em">'
                "RALLY SECURE SIGN-IN</p><h1 style=\"font-size:28px\">Your workspace is one click away.</h1>"
                "<p>Use this one-time link to enter Rally. It expires in 10 minutes.</p>"
                f'<p><a href="{safe_link}" style="display:inline-block;padding:12px 20px;'
                'border-radius:999px;background:#246bfd;color:#fff;text-decoration:none;font-weight:700">'
                "Sign in to Rally</a></p>"
                "<p style=\"color:#617188;font-size:13px\">If you did not request this, ignore this email.</p>"
                "</div>"
            ),
        }

        def deliver() -> None:
            request = urllib.request.Request(
                "https://api.resend.com/emails",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Idempotency-Key": f"rally-magic-{_sha256(token)}",
                    "User-Agent": "rally/1.0 (+https://rally.agent9.dev)",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=15) as response:
                    if response.status < 200 or response.status >= 300:
                        raise MagicLinkError("Resend rejected sign-in delivery")
            except (OSError, urllib.error.HTTPError, urllib.error.URLError) as exc:
                raise MagicLinkError("could not deliver sign-in link") from exc

        await asyncio.to_thread(deliver)


def _validated_secret(value: str) -> bytes:
    if not isinstance(value, str) or len(value.encode("utf-8")) < 32:
        raise MagicLinkError("magic-link signing key is not configured")
    return value.encode("utf-8")


def _binding(secret: bytes, email: str, workspace_id: str) -> str:
    return _b64url(_sign(secret, f"bind\0{email}\0{workspace_id}")[:18])


def _new_token(
    secret: bytes,
    email: str,
    workspace_id: str,
    now: dt.datetime,
    *,
    delivery_id: str | None = None,
    expires_at: dt.datetime | None = None,
) -> tuple[str, str, dt.datetime]:
    expires_at = expires_at or now + dt.timedelta(seconds=_LINK_TTL_SECONDS)
    if expires_at <= now or expires_at > now + dt.timedelta(seconds=_LINK_TTL_SECONDS):
        raise MagicLinkError("invalid sign-in delivery expiry")
    nonce = (
        _b64url(_sign(secret, f"delivery\0{delivery_id}")[:32])
        if delivery_id
        else secrets.token_urlsafe(32)
    )
    unsigned = ".".join(
        ("ml1", nonce, str(int(expires_at.timestamp())), _binding(secret, email, workspace_id))
    )
    token = f"{unsigned}.{_b64url(_sign(secret, unsigned))}"
    return token, _sha256(token), expires_at


def _validated_token_hash(secret: bytes, token: str, now: dt.datetime) -> str | None:
    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        return None
    version, nonce, expires, binding, signature = token.split(".")
    unsigned = f"{version}.{nonce}.{expires}.{binding}"
    expected = _b64url(_sign(secret, unsigned))
    if not hmac.compare_digest(signature, expected):
        return None
    if int(expires) <= int(now.timestamp()):
        return None
    return _sha256(token)


def _binding_matches(secret: bytes, token: str, email: str, workspace_id: str) -> bool:
    if not _TOKEN.fullmatch(token):
        return False
    supplied = token.split(".")[3]
    return hmac.compare_digest(supplied, _binding(secret, email, workspace_id))


def make_magic_link_store() -> MagicLinkStore:
    backend = os.getenv("RALLY_MAGIC_LINK_BACKEND", "")
    signing_key = os.getenv("RALLY_MAGIC_LINK_SIGNING_KEY", "")
    if backend == "firestore":
        return FirestoreMagicLinkStore(
            os.getenv("GOOGLE_CLOUD_PROJECT", ""),
            signing_key,
        )
    if backend == "memory" and os.getenv("RALLY_ALLOW_INSECURE_DEV") == "1":
        return MemoryMagicLinkStore(signing_key)
    raise MagicLinkError("magic-link store is not configured")


def make_magic_link_delivery_queue() -> MagicLinkDeliveryQueue:
    backend = os.getenv("RALLY_MAGIC_LINK_QUEUE_BACKEND", "")
    if backend == "pubsub":
        return PubSubMagicLinkDeliveryQueue(
            os.getenv("GOOGLE_CLOUD_PROJECT", ""),
            os.getenv("RALLY_MAGIC_LINK_TOPIC_ID", ""),
        )
    if backend == "memory" and os.getenv("RALLY_ALLOW_INSECURE_DEV") == "1":
        return MemoryMagicLinkDeliveryQueue()
    raise MagicLinkError("magic-link delivery queue is not configured")


def make_magic_link_mailer(admin_url: str) -> ResendMagicLinkMailer:
    return ResendMagicLinkMailer(
        os.getenv("RESEND_API_KEY", ""),
        os.getenv("RALLY_MAGIC_LINK_FROM", "Rally <rally@updates.agent9.dev>"),
        admin_url,
    )


__all__ = [
    "MagicLinkDelivery",
    "MagicLinkDeliveryQueue",
    "MagicLinkError",
    "MagicLinkStore",
    "MemoryMagicLinkDeliveryQueue",
    "MemoryMagicLinkStore",
    "PubSubMagicLinkDeliveryQueue",
    "ResendMagicLinkMailer",
    "decode_magic_link_delivery",
    "make_magic_link_delivery_queue",
    "make_magic_link_mailer",
    "make_magic_link_store",
]
