"""Short-lived, one-time browser authentication records for Rally."""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import os
import re
import secrets
from dataclasses import asdict
from typing import Any, Final, Protocol

from user_auth import UserIdentity


class AuthSessionError(RuntimeError):
    """Authentication state could not be persisted safely."""


_TOKEN: Final = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_CODE_TTL_SECONDS: Final = 120
_SESSION_TTL_SECONDS: Final = 30 * 60


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def _token_hash(token: str) -> str | None:
    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        return None
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _identity_record(identity: UserIdentity) -> dict[str, str | None]:
    return asdict(identity)


def _identity_from_record(record: dict[str, Any]) -> UserIdentity | None:
    uid = record.get("uid")
    email = record.get("email")
    if not isinstance(uid, str) or not uid or not isinstance(email, str) or not email:
        return None
    optional = {}
    for field in ("name", "picture", "hosted_domain"):
        value = record.get(field)
        optional[field] = value if isinstance(value, str) else None
    return UserIdentity(uid=uid, email=email, **optional)


def _not_expired(record: dict[str, Any], now: dt.datetime) -> bool:
    expires_at = record.get("expires_at")
    return isinstance(expires_at, dt.datetime) and expires_at > now


class AuthSessionStore(Protocol):
    async def issue_code(self, identity: UserIdentity) -> str: ...

    async def exchange_code(self, code: str) -> tuple[str, UserIdentity] | None: ...

    async def get_identity(self, session_token: str) -> UserIdentity | None: ...


class MemoryAuthSessionStore:
    """Deterministic development store; raw codes and tokens are never retained."""

    def __init__(
        self,
        *,
        clock: Any = _utc_now,
        code_ttl_seconds: int = _CODE_TTL_SECONDS,
        session_ttl_seconds: int = _SESSION_TTL_SECONDS,
    ) -> None:
        self._clock = clock
        self._code_ttl = dt.timedelta(seconds=code_ttl_seconds)
        self._session_ttl = dt.timedelta(seconds=session_ttl_seconds)
        self._codes: dict[str, dict[str, Any]] = {}
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def issue_code(self, identity: UserIdentity) -> str:
        code = _new_token()
        code_hash = _token_hash(code)
        if code_hash is None:  # pragma: no cover - generated tokens always satisfy the contract
            raise AuthSessionError("could not create login code")
        async with self._lock:
            self._codes[code_hash] = {
                **_identity_record(identity),
                "expires_at": self._clock() + self._code_ttl,
            }
        return code

    async def exchange_code(self, code: str) -> tuple[str, UserIdentity] | None:
        code_hash = _token_hash(code)
        if code_hash is None:
            return None
        async with self._lock:
            record = self._codes.pop(code_hash, None)
            if not record or not _not_expired(record, self._clock()):
                return None
            identity = _identity_from_record(record)
            if identity is None:
                return None
            session_token = _new_token()
            session_hash = _token_hash(session_token)
            if session_hash is None:  # pragma: no cover - generated tokens satisfy the contract
                raise AuthSessionError("could not create login session")
            self._sessions[session_hash] = {
                **_identity_record(identity),
                "expires_at": self._clock() + self._session_ttl,
            }
        return session_token, identity

    async def get_identity(self, session_token: str) -> UserIdentity | None:
        session_hash = _token_hash(session_token)
        if session_hash is None:
            return None
        async with self._lock:
            record = self._sessions.get(session_hash)
            if not record or not _not_expired(record, self._clock()):
                self._sessions.pop(session_hash, None)
                return None
            return _identity_from_record(record)


class FirestoreAuthSessionStore:
    """Firestore-backed exchange codes and sessions indexed only by token hashes."""

    def __init__(self, project_id: str, firestore_client: Any | None = None) -> None:
        if not project_id:
            raise AuthSessionError("Google Cloud project is not configured")
        if firestore_client is None:
            from google.cloud import firestore

            firestore_client = firestore.AsyncClient(project=project_id)
        self.client = firestore_client
        self.codes = self.client.collection("rally_auth_codes")
        self.sessions = self.client.collection("rally_auth_sessions")

    async def issue_code(self, identity: UserIdentity) -> str:
        code = _new_token()
        code_hash = _token_hash(code)
        if code_hash is None:  # pragma: no cover - generated tokens satisfy the contract
            raise AuthSessionError("could not create login code")
        record = {
            **_identity_record(identity),
            "created_at": _utc_now(),
            "expires_at": _utc_now() + dt.timedelta(seconds=_CODE_TTL_SECONDS),
        }
        try:
            await self.codes.document(code_hash).create(record)
        except Exception as exc:
            raise AuthSessionError("could not create login code") from exc
        return code

    async def exchange_code(self, code: str) -> tuple[str, UserIdentity] | None:
        from google.cloud import firestore

        code_hash = _token_hash(code)
        if code_hash is None:
            return None
        session_token = _new_token()
        session_hash = _token_hash(session_token)
        if session_hash is None:  # pragma: no cover - generated tokens satisfy the contract
            raise AuthSessionError("could not create login session")
        code_ref = self.codes.document(code_hash)
        session_ref = self.sessions.document(session_hash)
        now = _utc_now()

        @firestore.async_transactional
        async def consume(transaction: Any) -> UserIdentity | None:
            snapshot = await code_ref.get(transaction=transaction)
            if not snapshot.exists:
                return None
            record = snapshot.to_dict() or {}
            transaction.delete(code_ref)
            if not _not_expired(record, now):
                return None
            identity = _identity_from_record(record)
            if identity is None:
                return None
            transaction.set(
                session_ref,
                {
                    **_identity_record(identity),
                    "created_at": now,
                    "expires_at": now + dt.timedelta(seconds=_SESSION_TTL_SECONDS),
                },
            )
            return identity

        try:
            identity = await consume(self.client.transaction())
        except Exception as exc:
            raise AuthSessionError("could not exchange login code") from exc
        return (session_token, identity) if identity is not None else None

    async def get_identity(self, session_token: str) -> UserIdentity | None:
        session_hash = _token_hash(session_token)
        if session_hash is None:
            return None
        document = self.sessions.document(session_hash)
        try:
            snapshot = await document.get()
            if not snapshot.exists:
                return None
            record = snapshot.to_dict() or {}
            if not _not_expired(record, _utc_now()):
                await document.delete()
                return None
            return _identity_from_record(record)
        except Exception as exc:
            raise AuthSessionError("could not verify login session") from exc


def make_auth_session_store() -> AuthSessionStore:
    backend = os.getenv("RALLY_AUTH_BACKEND", "")
    if backend == "firestore":
        return FirestoreAuthSessionStore(os.getenv("GOOGLE_CLOUD_PROJECT", ""))
    if backend == "memory" and os.getenv("RALLY_ALLOW_INSECURE_DEV") == "1":
        return MemoryAuthSessionStore()
    raise AuthSessionError("browser authentication store is not configured")
