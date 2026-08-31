"""Tenant-isolated connector credential storage with Google KMS envelope encryption."""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
from dataclasses import dataclass, replace
from typing import Any, Final, Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CredentialVaultError(RuntimeError):
    """Credential storage failed without disclosing secret material."""


class CredentialVaultConflict(CredentialVaultError):
    """A generation/status precondition failed without changing the credential."""


class CredentialVaultBusy(CredentialVaultError):
    """A live connector invocation currently owns the connection lease."""


_CONNECTOR_ID: Final = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_MAX_SECRET_BYTES: Final = 64 * 1024
_ENVELOPE_SCHEMA: Final = "rally.connector-secret/v1"
_CONNECTION_STATUSES: Final = {
    "stored_unverified",
    "verifying",
    "ready",
    "needs_attention",
}
_CERTIFICATION_SCHEMA: Final = "rally.connection-certification/v1"
_TOOL_NAME: Final = re.compile(r"^[A-Za-z0-9_.:/-]{1,160}$")
_SHA256: Final = re.compile(r"^[a-f0-9]{64}$")
_GENERATION: Final = re.compile(r"^[a-f0-9]{32}$")
_LEASE: Final = re.compile(r"^[a-f0-9]{32}$")
_EXECUTION_LEASE_SECONDS: Final = 90


def _validate_connector_id(connector_id: str) -> str:
    if not isinstance(connector_id, str) or not _CONNECTOR_ID.fullmatch(connector_id):
        raise CredentialVaultError("invalid connector identifier")
    return connector_id


def _owner_hash(uid: str) -> str:
    return hashlib.sha256(uid.encode("utf-8")).hexdigest()


def _document_id(uid: str, connector_id: str) -> str:
    return hashlib.sha256(f"{uid}\0{connector_id}".encode()).hexdigest()


def _associated_data(uid: str, connector_id: str) -> bytes:
    return f"{_ENVELOPE_SCHEMA}\0{uid}\0{connector_id}".encode()


def _encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _decode(value: Any) -> bytes:
    if not isinstance(value, str):
        raise CredentialVaultError("stored connector credential is invalid")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        raise CredentialVaultError("stored connector credential is invalid") from None


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _utc_datetime() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _new_generation() -> str:
    return secrets.token_hex(16)


def _normalize_certified_tools(value: Any) -> tuple[tuple[str, str], ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or len(value) > 128:
        raise CredentialVaultError("invalid certified tool manifest")
    normalized: list[tuple[str, str]] = []
    for entry in value:
        if isinstance(entry, dict):
            name = entry.get("name")
            schema_sha256 = entry.get("schema_sha256")
        elif isinstance(entry, (list, tuple)) and len(entry) == 2:
            name, schema_sha256 = entry
        else:
            raise CredentialVaultError("invalid certified tool manifest")
        if (
            not isinstance(name, str)
            or not _TOOL_NAME.fullmatch(name)
            or not isinstance(schema_sha256, str)
            or not _SHA256.fullmatch(schema_sha256)
        ):
            raise CredentialVaultError("invalid certified tool manifest")
        normalized.append((name, schema_sha256))
    normalized.sort()
    if len({name for name, _ in normalized}) != len(normalized):
        raise CredentialVaultError("invalid certified tool manifest")
    return tuple(normalized)


def certified_manifest_sha256(value: Any) -> str:
    normalized = _normalize_certified_tools(value)
    encoded = json.dumps(normalized, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_certification(
    *,
    status: str,
    tool_count: int,
    canary_tool: str | None,
    tool_schema_sha256: str | None,
    proof_version: str | None,
    certified_tools: Any,
    certified_manifest_sha256_value: str | None,
) -> tuple[tuple[str, str], ...]:
    tools = _normalize_certified_tools(certified_tools)
    if status != "ready":
        return ()
    tool_map = dict(tools)
    if (
        tool_count < 1
        or tool_count != len(tools)
        or not isinstance(canary_tool, str)
        or not _TOOL_NAME.fullmatch(canary_tool)
        or not isinstance(tool_schema_sha256, str)
        or not _SHA256.fullmatch(tool_schema_sha256)
        or tool_map.get(canary_tool) != tool_schema_sha256
        or proof_version != _CERTIFICATION_SCHEMA
        or not isinstance(certified_manifest_sha256_value, str)
        or not _SHA256.fullmatch(certified_manifest_sha256_value)
        or not hmac.compare_digest(
            certified_manifest_sha256_value,
            certified_manifest_sha256(tools),
        )
    ):
        raise CredentialVaultError("ready connection requires live certification")
    return tools


def _lease_is_active(record: dict[str, Any], now: dt.datetime | None = None) -> bool:
    lease = record.get("execution_lease")
    expiry = record.get("execution_lease_expires_at")
    if not isinstance(lease, str) or not _LEASE.fullmatch(lease):
        return False
    now = now or _utc_datetime()
    if isinstance(expiry, str):
        try:
            expiry = dt.datetime.fromisoformat(expiry)
        except ValueError:
            return False
    return isinstance(expiry, dt.datetime) and expiry.astimezone(dt.UTC) > now


@dataclass(frozen=True, repr=False)
class ConnectorSecret:
    value: str
    kind: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.value, str)
            or not self.value
            or len(self.value.encode("utf-8")) > _MAX_SECRET_BYTES
            or any(ord(character) < 32 or ord(character) == 127 for character in self.value)
        ):
            raise CredentialVaultError("invalid connector credential")
        if self.kind not in {"api_key", "bearer_token", "oauth_refresh_token"}:
            raise CredentialVaultError("unsupported connector credential kind")


def _same_secret(left: ConnectorSecret, right: ConnectorSecret) -> bool:
    return hmac.compare_digest(left.kind, right.kind) and hmac.compare_digest(
        left.value, right.value
    )


@dataclass(frozen=True)
class ConnectionRecord:
    connector_id: str
    credential_kind: str
    status: str
    created_at: str
    updated_at: str
    tool_count: int = 0
    verified_at: str | None = None
    error_code: str | None = None
    canary_tool: str | None = None
    tool_schema_sha256: str | None = None
    proof_version: str | None = None
    credential_generation: str = ""
    certified_tools: tuple[tuple[str, str], ...] = ()
    certified_manifest_sha256: str | None = None
    execution_lease: str | None = None
    execution_lease_expires_at: dt.datetime | None = None


@dataclass(frozen=True, repr=False)
class StoredConnection:
    record: ConnectionRecord
    secret: ConnectorSecret


class ConnectorVault(Protocol):
    async def put(
        self, uid: str, connector_id: str, secret: ConnectorSecret
    ) -> ConnectionRecord: ...

    async def list(self, uid: str) -> list[ConnectionRecord]: ...

    async def get_secret(self, uid: str, connector_id: str) -> ConnectorSecret | None: ...

    async def get_connection(self, uid: str, connector_id: str) -> StoredConnection | None: ...

    async def rotate(
        self,
        uid: str,
        connector_id: str,
        *,
        expected_generation: str,
        expected_lease: str,
        expected: ConnectorSecret,
        secret: ConnectorSecret,
    ) -> ConnectionRecord | None: ...

    async def quarantine(
        self,
        uid: str,
        connector_id: str,
        *,
        expected_generation: str,
        expected_lease: str,
        expected: ConnectorSecret,
        error_code: str,
    ) -> bool: ...

    async def begin_verification(
        self, uid: str, connector_id: str, *, expected_generation: str
    ) -> ConnectionRecord | None: ...

    async def finish_verification(
        self,
        uid: str,
        connector_id: str,
        *,
        expected_generation: str,
        expected_lease: str,
        status: str,
        tool_count: int = 0,
        error_code: str | None = None,
        canary_tool: str | None = None,
        tool_schema_sha256: str | None = None,
        proof_version: str | None = None,
        certified_tools: tuple[tuple[str, str], ...] = (),
        certified_manifest_sha256: str | None = None,
    ) -> ConnectionRecord | None: ...

    async def claim_execution(self, uid: str, connector_id: str) -> StoredConnection | None: ...

    async def release_execution(
        self, uid: str, connector_id: str, *, expected_lease: str
    ) -> bool: ...

    async def begin_disconnect(self, uid: str, connector_id: str) -> StoredConnection | None: ...

    async def mark(
        self,
        uid: str,
        connector_id: str,
        *,
        status: str,
        tool_count: int = 0,
        error_code: str | None = None,
        canary_tool: str | None = None,
        tool_schema_sha256: str | None = None,
        proof_version: str | None = None,
        certified_tools: tuple[tuple[str, str], ...] = (),
        certified_manifest_sha256: str | None = None,
    ) -> ConnectionRecord: ...

    async def delete(
        self,
        uid: str,
        connector_id: str,
        *,
        expected_generation: str | None = None,
        require_disconnect: bool = False,
    ) -> bool: ...


class KmsEnvelopeCipher:
    """One random AES-GCM DEK per credential, wrapped by a Cloud KMS KEK."""

    def __init__(
        self,
        key_name: str,
        client: Any | None = None,
        *,
        envelope_schema: str = _ENVELOPE_SCHEMA,
    ):
        if not key_name.startswith("projects/") or "/cryptoKeys/" not in key_name:
            raise CredentialVaultError("invalid Cloud KMS key name")
        if not envelope_schema.startswith("rally.") or not envelope_schema.endswith("/v1"):
            raise CredentialVaultError("invalid envelope schema")
        if client is None:
            from google.cloud import kms

            client = kms.KeyManagementServiceClient()
        self.key_name = key_name
        self.client = client
        self.envelope_schema = envelope_schema

    def seal(self, plaintext: bytes, associated_data: bytes) -> dict[str, str]:
        if not plaintext or len(plaintext) > _MAX_SECRET_BYTES:
            raise CredentialVaultError("invalid connector credential payload")
        dek = os.urandom(32)
        nonce = os.urandom(12)
        ciphertext = AESGCM(dek).encrypt(nonce, plaintext, associated_data)
        try:
            wrapped = self.client.encrypt(
                request={"name": self.key_name, "plaintext": dek}
            ).ciphertext
        except Exception as exc:
            raise CredentialVaultError("could not protect connector credential") from exc
        return {
            "schema": self.envelope_schema,
            "nonce": _encode(nonce),
            "ciphertext": _encode(ciphertext),
            "wrapped_dek": _encode(wrapped),
            "kms_key": self.key_name,
        }

    def open(self, envelope: dict[str, Any], associated_data: bytes) -> bytes:
        if envelope.get("schema") != self.envelope_schema:
            raise CredentialVaultError("stored connector credential is invalid")
        if envelope.get("kms_key") != self.key_name:
            raise CredentialVaultError("stored connector credential uses an unexpected key")
        try:
            dek = self.client.decrypt(
                request={"name": self.key_name, "ciphertext": _decode(envelope.get("wrapped_dek"))}
            ).plaintext
            return AESGCM(dek).decrypt(
                _decode(envelope.get("nonce")),
                _decode(envelope.get("ciphertext")),
                associated_data,
            )
        except CredentialVaultError:
            raise
        except Exception as exc:
            raise CredentialVaultError("could not open connector credential") from exc


class MemoryConnectorVault:
    """Explicit development-only vault used by tests and local demos."""

    def __init__(self):
        self._items: dict[tuple[str, str], tuple[ConnectorSecret, ConnectionRecord]] = {}
        self._lock = asyncio.Lock()

    async def put(self, uid: str, connector_id: str, secret: ConnectorSecret) -> ConnectionRecord:
        connector_id = _validate_connector_id(connector_id)
        key = (uid, connector_id)
        async with self._lock:
            if key in self._items:
                raise CredentialVaultConflict("connector credential already exists")
            now = _utc_now()
            record = ConnectionRecord(
                connector_id=connector_id,
                credential_kind=secret.kind,
                status="stored_unverified",
                created_at=now,
                updated_at=now,
                credential_generation=_new_generation(),
            )
            self._items[key] = (secret, record)
            return record

    async def list(self, uid: str) -> list[ConnectionRecord]:
        return sorted(
            (record for (owner, _), (_, record) in self._items.items() if owner == uid),
            key=lambda item: item.connector_id,
        )

    async def get_secret(self, uid: str, connector_id: str) -> ConnectorSecret | None:
        stored = await self.get_connection(uid, connector_id)
        return stored.secret if stored else None

    async def get_connection(self, uid: str, connector_id: str) -> StoredConnection | None:
        key = (uid, _validate_connector_id(connector_id))
        async with self._lock:
            item = self._items.get(key)
            return StoredConnection(item[1], item[0]) if item else None

    async def rotate(
        self,
        uid: str,
        connector_id: str,
        *,
        expected_generation: str,
        expected_lease: str,
        expected: ConnectorSecret,
        secret: ConnectorSecret,
    ) -> ConnectionRecord | None:
        key = (uid, _validate_connector_id(connector_id))
        async with self._lock:
            current = self._items.get(key)
            if (
                secret.kind != expected.kind
                or current is None
                or current[1].status != "ready"
                or current[1].credential_generation != expected_generation
                or current[1].execution_lease != expected_lease
                or not _same_secret(current[0], expected)
            ):
                return None
            record = replace(
                current[1],
                credential_kind=secret.kind,
                credential_generation=_new_generation(),
                updated_at=_utc_now(),
            )
            self._items[key] = (secret, record)
            return record

    async def quarantine(
        self,
        uid: str,
        connector_id: str,
        *,
        expected_generation: str,
        expected_lease: str,
        expected: ConnectorSecret,
        error_code: str,
    ) -> bool:
        key = (uid, _validate_connector_id(connector_id))
        async with self._lock:
            current = self._items.get(key)
            if (
                current is None
                or current[1].status != "ready"
                or current[1].credential_generation != expected_generation
                or current[1].execution_lease != expected_lease
                or not _same_secret(current[0], expected)
            ):
                return False
            self._items[key] = (
                current[0],
                replace(
                    current[1],
                    status="needs_attention",
                    updated_at=_utc_now(),
                    tool_count=0,
                    verified_at=None,
                    error_code=error_code,
                    canary_tool=None,
                    tool_schema_sha256=None,
                    proof_version=None,
                    certified_tools=(),
                    certified_manifest_sha256=None,
                    execution_lease=None,
                    execution_lease_expires_at=None,
                ),
            )
            return True

    async def begin_verification(
        self, uid: str, connector_id: str, *, expected_generation: str
    ) -> ConnectionRecord | None:
        key = (uid, _validate_connector_id(connector_id))
        async with self._lock:
            current = self._items.get(key)
            if (
                current is None
                or current[1].credential_generation != expected_generation
                or current[1].status == "ready"
                or current[1].error_code == "disconnect_pending"
                or _lease_is_active(
                    {
                        "execution_lease": current[1].execution_lease,
                        "execution_lease_expires_at": current[1].execution_lease_expires_at,
                    }
                )
            ):
                return None
            lease = _new_generation()
            expiry = _utc_datetime() + dt.timedelta(seconds=_EXECUTION_LEASE_SECONDS)
            record = replace(
                current[1],
                status="verifying",
                updated_at=_utc_now(),
                tool_count=0,
                verified_at=None,
                error_code=None,
                canary_tool=None,
                tool_schema_sha256=None,
                proof_version=None,
                certified_tools=(),
                certified_manifest_sha256=None,
                execution_lease=lease,
                execution_lease_expires_at=expiry,
            )
            self._items[key] = (current[0], record)
            return record

    async def finish_verification(
        self,
        uid: str,
        connector_id: str,
        *,
        expected_generation: str,
        expected_lease: str,
        status: str,
        tool_count: int = 0,
        error_code: str | None = None,
        canary_tool: str | None = None,
        tool_schema_sha256: str | None = None,
        proof_version: str | None = None,
        certified_tools: tuple[tuple[str, str], ...] = (),
        certified_manifest_sha256: str | None = None,
    ) -> ConnectionRecord | None:
        tools = _validate_certification(
            status=status,
            tool_count=tool_count,
            canary_tool=canary_tool,
            tool_schema_sha256=tool_schema_sha256,
            proof_version=proof_version,
            certified_tools=certified_tools,
            certified_manifest_sha256_value=certified_manifest_sha256,
        )
        if status not in {"ready", "needs_attention"}:
            raise CredentialVaultError("invalid connector status")
        key = (uid, _validate_connector_id(connector_id))
        async with self._lock:
            current = self._items.get(key)
            if (
                current is None
                or current[1].credential_generation != expected_generation
                or current[1].status != "verifying"
                or current[1].execution_lease != expected_lease
            ):
                return None
            now = _utc_now()
            record = replace(
                current[1],
                status=status,
                updated_at=now,
                tool_count=tool_count if status == "ready" else 0,
                verified_at=now if status == "ready" else None,
                error_code=error_code,
                canary_tool=canary_tool if status == "ready" else None,
                tool_schema_sha256=tool_schema_sha256 if status == "ready" else None,
                proof_version=proof_version if status == "ready" else None,
                certified_tools=tools if status == "ready" else (),
                certified_manifest_sha256=(
                    certified_manifest_sha256 if status == "ready" else None
                ),
                execution_lease=None,
                execution_lease_expires_at=None,
            )
            self._items[key] = (current[0], record)
            return record

    async def claim_execution(self, uid: str, connector_id: str) -> StoredConnection | None:
        key = (uid, _validate_connector_id(connector_id))
        async with self._lock:
            current = self._items.get(key)
            if current is None or current[1].status != "ready":
                return None
            if _lease_is_active(
                {
                    "execution_lease": current[1].execution_lease,
                    "execution_lease_expires_at": current[1].execution_lease_expires_at,
                }
            ):
                raise CredentialVaultBusy("connector execution already in progress")
            lease = _new_generation()
            expiry = _utc_datetime() + dt.timedelta(seconds=_EXECUTION_LEASE_SECONDS)
            record = replace(
                current[1],
                execution_lease=lease,
                execution_lease_expires_at=expiry,
                updated_at=_utc_now(),
            )
            self._items[key] = (current[0], record)
            return StoredConnection(record, current[0])

    async def release_execution(self, uid: str, connector_id: str, *, expected_lease: str) -> bool:
        key = (uid, _validate_connector_id(connector_id))
        async with self._lock:
            current = self._items.get(key)
            if current is None or current[1].execution_lease != expected_lease:
                return False
            record = replace(
                current[1],
                execution_lease=None,
                execution_lease_expires_at=None,
                updated_at=_utc_now(),
            )
            self._items[key] = (current[0], record)
            return True

    async def begin_disconnect(self, uid: str, connector_id: str) -> StoredConnection | None:
        key = (uid, _validate_connector_id(connector_id))
        async with self._lock:
            current = self._items.get(key)
            if current is None:
                return None
            if current[1].status != "verifying" and _lease_is_active(
                {
                    "execution_lease": current[1].execution_lease,
                    "execution_lease_expires_at": current[1].execution_lease_expires_at,
                }
            ):
                raise CredentialVaultBusy("connector execution is in progress")
            generation = current[1].credential_generation
            if not _GENERATION.fullmatch(generation):
                generation = _new_generation()
            record = replace(
                current[1],
                credential_generation=generation,
                status="needs_attention",
                updated_at=_utc_now(),
                tool_count=0,
                verified_at=None,
                error_code="disconnect_pending",
                canary_tool=None,
                tool_schema_sha256=None,
                proof_version=None,
                certified_tools=(),
                certified_manifest_sha256=None,
                execution_lease=None,
                execution_lease_expires_at=None,
            )
            self._items[key] = (current[0], record)
            return StoredConnection(record, current[0])

    async def mark(
        self,
        uid: str,
        connector_id: str,
        *,
        status: str,
        tool_count: int = 0,
        error_code: str | None = None,
        canary_tool: str | None = None,
        tool_schema_sha256: str | None = None,
        proof_version: str | None = None,
        certified_tools: tuple[tuple[str, str], ...] = (),
        certified_manifest_sha256: str | None = None,
    ) -> ConnectionRecord:
        connector_id = _validate_connector_id(connector_id)
        if status not in _CONNECTION_STATUSES or not 0 <= tool_count <= 128:
            raise CredentialVaultError("invalid connector status")
        tools = _validate_certification(
            status=status,
            tool_count=tool_count,
            canary_tool=canary_tool,
            tool_schema_sha256=tool_schema_sha256,
            proof_version=proof_version,
            certified_tools=certified_tools,
            certified_manifest_sha256_value=certified_manifest_sha256,
        )
        key = (uid, connector_id)
        async with self._lock:
            item = self._items.get(key)
            if item is None:
                raise CredentialVaultError("connector credential does not exist")
            now = _utc_now()
            record = replace(
                item[1],
                status=status,
                updated_at=now,
                tool_count=tool_count if status == "ready" else 0,
                verified_at=now if status == "ready" else None,
                error_code=error_code,
                canary_tool=canary_tool if status == "ready" else None,
                tool_schema_sha256=tool_schema_sha256 if status == "ready" else None,
                proof_version=proof_version if status == "ready" else None,
                certified_tools=tools if status == "ready" else (),
                certified_manifest_sha256=(
                    certified_manifest_sha256 if status == "ready" else None
                ),
                execution_lease=None,
                execution_lease_expires_at=None,
            )
            self._items[key] = (item[0], record)
            return record

    async def delete(
        self,
        uid: str,
        connector_id: str,
        *,
        expected_generation: str | None = None,
        require_disconnect: bool = False,
    ) -> bool:
        key = (uid, _validate_connector_id(connector_id))
        async with self._lock:
            current = self._items.get(key)
            if current is None:
                return False
            if expected_generation is not None and (
                current[1].credential_generation != expected_generation
            ):
                return False
            if require_disconnect and current[1].error_code != "disconnect_pending":
                return False
            self._items.pop(key)
            return True


class GoogleKmsConnectorVault:
    """Firestore metadata plus KMS-wrapped, application-layer ciphertext."""

    def __init__(
        self,
        project_id: str,
        key_name: str,
        firestore_client: Any | None = None,
        kms_client: Any | None = None,
    ):
        if not project_id:
            raise CredentialVaultError("Google Cloud project is not configured")
        if firestore_client is None:
            from google.cloud import firestore

            firestore_client = firestore.AsyncClient(project=project_id)
        self.client = firestore_client
        self.collection = firestore_client.collection("connector_credentials")
        self.cipher = KmsEnvelopeCipher(key_name, client=kms_client)

    async def put(self, uid: str, connector_id: str, secret: ConnectorSecret) -> ConnectionRecord:
        from google.api_core.exceptions import AlreadyExists

        connector_id = _validate_connector_id(connector_id)
        document = self.collection.document(_document_id(uid, connector_id))
        now = _utc_now()
        plaintext = json.dumps(
            {"kind": secret.kind, "value": secret.value},
            separators=(",", ":"),
        ).encode("utf-8")
        envelope = await asyncio.to_thread(
            self.cipher.seal,
            plaintext,
            _associated_data(uid, connector_id),
        )
        record = {
            **envelope,
            "owner_hash": _owner_hash(uid),
            "connector_id": connector_id,
            "credential_kind": secret.kind,
            "credential_generation": _new_generation(),
            "status": "stored_unverified",
            "created_at": now,
            "updated_at": now,
        }
        try:
            await document.create(record)
        except AlreadyExists:
            raise CredentialVaultConflict("connector credential already exists") from None
        except Exception as exc:
            raise CredentialVaultError("could not store connector credential") from exc
        return _public_record(record)

    async def list(self, uid: str) -> list[ConnectionRecord]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = self.collection.where(filter=FieldFilter("owner_hash", "==", _owner_hash(uid)))
        records = [_public_record(snapshot.to_dict()) async for snapshot in query.stream()]
        return sorted(records, key=lambda item: item.connector_id)

    async def get_secret(self, uid: str, connector_id: str) -> ConnectorSecret | None:
        stored = await self.get_connection(uid, connector_id)
        return stored.secret if stored else None

    async def get_connection(self, uid: str, connector_id: str) -> StoredConnection | None:
        connector_id = _validate_connector_id(connector_id)
        snapshot = await self.collection.document(_document_id(uid, connector_id)).get()
        if not snapshot.exists:
            return None
        record = snapshot.to_dict() or {}
        if not hmac.compare_digest(str(record.get("owner_hash", "")), _owner_hash(uid)):
            return None
        plaintext = await asyncio.to_thread(
            self.cipher.open,
            record,
            _associated_data(uid, connector_id),
        )
        try:
            payload = json.loads(plaintext)
            return StoredConnection(
                _public_record(record),
                ConnectorSecret(value=payload["value"], kind=payload["kind"]),
            )
        except (KeyError, TypeError, ValueError, UnicodeDecodeError):
            raise CredentialVaultError("stored connector credential is invalid") from None

    async def rotate(
        self,
        uid: str,
        connector_id: str,
        *,
        expected_generation: str,
        expected_lease: str,
        expected: ConnectorSecret,
        secret: ConnectorSecret,
    ) -> ConnectionRecord | None:
        """Compare-and-swap one sealed secret while preserving certification metadata."""

        from google.cloud import firestore

        connector_id = _validate_connector_id(connector_id)
        document = self.collection.document(_document_id(uid, connector_id))
        plaintext = json.dumps(
            {"kind": secret.kind, "value": secret.value},
            separators=(",", ":"),
        ).encode("utf-8")
        envelope = await asyncio.to_thread(
            self.cipher.seal,
            plaintext,
            _associated_data(uid, connector_id),
        )

        @firestore.async_transactional
        async def replace_secret(transaction: Any) -> dict[str, Any] | None:
            snapshot = await document.get(transaction=transaction)
            if not snapshot.exists:
                return None
            record = snapshot.to_dict() or {}
            if not hmac.compare_digest(str(record.get("owner_hash", "")), _owner_hash(uid)):
                return None
            if (
                record.get("status") != "ready"
                or record.get("credential_generation") != expected_generation
                or record.get("execution_lease") != expected_lease
            ):
                return None
            current_plaintext = await asyncio.to_thread(
                self.cipher.open,
                record,
                _associated_data(uid, connector_id),
            )
            try:
                payload = json.loads(current_plaintext)
                current = ConnectorSecret(value=payload["value"], kind=payload["kind"])
            except (KeyError, TypeError, ValueError, UnicodeDecodeError):
                raise CredentialVaultError("stored connector credential is invalid") from None
            if secret.kind != expected.kind or not _same_secret(current, expected):
                return None
            generation = _new_generation()
            now = _utc_now()
            updates = {
                **envelope,
                "credential_kind": secret.kind,
                "credential_generation": generation,
                "updated_at": now,
            }
            transaction.update(
                document,
                updates,
            )
            return {**record, **updates}

        try:
            result = await replace_secret(self.client.transaction())
            return _public_record(result) if result is not None else None
        except CredentialVaultError:
            raise
        except Exception as exc:
            raise CredentialVaultError("could not rotate connector credential") from exc

    async def quarantine(
        self,
        uid: str,
        connector_id: str,
        *,
        expected_generation: str,
        expected_lease: str,
        expected: ConnectorSecret,
        error_code: str,
    ) -> bool:
        """Clear certification only if the failing sealed credential is still current."""

        from google.cloud import firestore

        connector_id = _validate_connector_id(connector_id)
        document = self.collection.document(_document_id(uid, connector_id))

        @firestore.async_transactional
        async def demote(transaction: Any) -> bool:
            snapshot = await document.get(transaction=transaction)
            if not snapshot.exists:
                return False
            record = snapshot.to_dict() or {}
            if not hmac.compare_digest(str(record.get("owner_hash", "")), _owner_hash(uid)):
                return False
            if (
                record.get("status") != "ready"
                or record.get("credential_generation") != expected_generation
                or record.get("execution_lease") != expected_lease
            ):
                return False
            current_plaintext = await asyncio.to_thread(
                self.cipher.open,
                record,
                _associated_data(uid, connector_id),
            )
            try:
                payload = json.loads(current_plaintext)
                current = ConnectorSecret(value=payload["value"], kind=payload["kind"])
            except (KeyError, TypeError, ValueError, UnicodeDecodeError):
                raise CredentialVaultError("stored connector credential is invalid") from None
            if not _same_secret(current, expected):
                return False
            transaction.update(
                document,
                {
                    "status": "needs_attention",
                    "tool_count": 0,
                    "verified_at": None,
                    "error_code": error_code,
                    "canary_tool": None,
                    "tool_schema_sha256": None,
                    "proof_version": None,
                    "certified_tools": [],
                    "certified_manifest_sha256": None,
                    "execution_lease": None,
                    "execution_lease_expires_at": None,
                    "updated_at": _utc_now(),
                },
            )
            return True

        try:
            return await demote(self.client.transaction())
        except CredentialVaultError:
            raise
        except Exception as exc:
            raise CredentialVaultError("could not quarantine connector credential") from exc

    async def begin_verification(
        self, uid: str, connector_id: str, *, expected_generation: str
    ) -> ConnectionRecord | None:
        from google.cloud import firestore

        connector_id = _validate_connector_id(connector_id)
        document = self.collection.document(_document_id(uid, connector_id))

        @firestore.async_transactional
        async def begin(transaction: Any) -> dict[str, Any] | None:
            snapshot = await document.get(transaction=transaction)
            if not snapshot.exists:
                return None
            record = snapshot.to_dict() or {}
            if not hmac.compare_digest(str(record.get("owner_hash", "")), _owner_hash(uid)):
                return None
            if (
                record.get("credential_generation") != expected_generation
                or record.get("status") == "ready"
                or record.get("error_code") == "disconnect_pending"
                or _lease_is_active(record)
            ):
                return None
            lease = _new_generation()
            expires_at = _utc_datetime() + dt.timedelta(seconds=_EXECUTION_LEASE_SECONDS)
            updates = {
                "status": "verifying",
                "tool_count": 0,
                "verified_at": None,
                "error_code": None,
                "canary_tool": None,
                "tool_schema_sha256": None,
                "proof_version": None,
                "certified_tools": [],
                "certified_manifest_sha256": None,
                "execution_lease": lease,
                "execution_lease_expires_at": expires_at,
                "updated_at": _utc_now(),
            }
            transaction.update(document, updates)
            return {**record, **updates}

        try:
            result = await begin(self.client.transaction())
            return _public_record(result) if result is not None else None
        except Exception as exc:
            raise CredentialVaultError("could not begin connector verification") from exc

    async def finish_verification(
        self,
        uid: str,
        connector_id: str,
        *,
        expected_generation: str,
        expected_lease: str,
        status: str,
        tool_count: int = 0,
        error_code: str | None = None,
        canary_tool: str | None = None,
        tool_schema_sha256: str | None = None,
        proof_version: str | None = None,
        certified_tools: tuple[tuple[str, str], ...] = (),
        certified_manifest_sha256: str | None = None,
    ) -> ConnectionRecord | None:
        from google.cloud import firestore

        if status not in {"ready", "needs_attention"}:
            raise CredentialVaultError("invalid connector status")
        tools = _validate_certification(
            status=status,
            tool_count=tool_count,
            canary_tool=canary_tool,
            tool_schema_sha256=tool_schema_sha256,
            proof_version=proof_version,
            certified_tools=certified_tools,
            certified_manifest_sha256_value=certified_manifest_sha256,
        )
        connector_id = _validate_connector_id(connector_id)
        document = self.collection.document(_document_id(uid, connector_id))

        @firestore.async_transactional
        async def finish(transaction: Any) -> dict[str, Any] | None:
            snapshot = await document.get(transaction=transaction)
            if not snapshot.exists:
                return None
            record = snapshot.to_dict() or {}
            if not hmac.compare_digest(str(record.get("owner_hash", "")), _owner_hash(uid)):
                return None
            if (
                record.get("credential_generation") != expected_generation
                or record.get("status") != "verifying"
                or record.get("execution_lease") != expected_lease
            ):
                return None
            now = _utc_now()
            updates = {
                "status": status,
                "tool_count": tool_count if status == "ready" else 0,
                "verified_at": now if status == "ready" else None,
                "error_code": error_code,
                "canary_tool": canary_tool if status == "ready" else None,
                "tool_schema_sha256": tool_schema_sha256 if status == "ready" else None,
                "proof_version": proof_version if status == "ready" else None,
                "certified_tools": (
                    [{"name": name, "schema_sha256": digest} for name, digest in tools]
                    if status == "ready"
                    else []
                ),
                "certified_manifest_sha256": (
                    certified_manifest_sha256 if status == "ready" else None
                ),
                "execution_lease": None,
                "execution_lease_expires_at": None,
                "updated_at": now,
            }
            transaction.update(document, updates)
            return {**record, **updates}

        try:
            result = await finish(self.client.transaction())
            return _public_record(result) if result is not None else None
        except CredentialVaultError:
            raise
        except Exception as exc:
            raise CredentialVaultError("could not finish connector verification") from exc

    async def claim_execution(self, uid: str, connector_id: str) -> StoredConnection | None:
        from google.cloud import firestore

        connector_id = _validate_connector_id(connector_id)
        document = self.collection.document(_document_id(uid, connector_id))
        lease = _new_generation()
        expires_at = _utc_datetime() + dt.timedelta(seconds=_EXECUTION_LEASE_SECONDS)

        @firestore.async_transactional
        async def claim(transaction: Any) -> dict[str, Any] | None:
            snapshot = await document.get(transaction=transaction)
            if not snapshot.exists:
                return None
            record = snapshot.to_dict() or {}
            if not hmac.compare_digest(str(record.get("owner_hash", "")), _owner_hash(uid)):
                return None
            if record.get("status") != "ready":
                return None
            if _lease_is_active(record):
                raise CredentialVaultBusy("connector execution already in progress")
            updates = {
                "execution_lease": lease,
                "execution_lease_expires_at": expires_at,
                "updated_at": _utc_now(),
            }
            transaction.update(document, updates)
            return {**record, **updates}

        try:
            record = await claim(self.client.transaction())
            if record is None:
                return None
            plaintext = await asyncio.to_thread(
                self.cipher.open,
                record,
                _associated_data(uid, connector_id),
            )
            payload = json.loads(plaintext)
            return StoredConnection(
                _public_record(record),
                ConnectorSecret(value=payload["value"], kind=payload["kind"]),
            )
        except CredentialVaultBusy:
            raise
        except (KeyError, TypeError, ValueError, UnicodeDecodeError):
            raise CredentialVaultError("stored connector credential is invalid") from None
        except Exception as exc:
            raise CredentialVaultError("could not claim connector execution") from exc

    async def release_execution(self, uid: str, connector_id: str, *, expected_lease: str) -> bool:
        from google.cloud import firestore

        connector_id = _validate_connector_id(connector_id)
        document = self.collection.document(_document_id(uid, connector_id))

        @firestore.async_transactional
        async def release(transaction: Any) -> bool:
            snapshot = await document.get(transaction=transaction)
            if not snapshot.exists:
                return False
            record = snapshot.to_dict() or {}
            if (
                not hmac.compare_digest(str(record.get("owner_hash", "")), _owner_hash(uid))
                or record.get("execution_lease") != expected_lease
            ):
                return False
            transaction.update(
                document,
                {
                    "execution_lease": None,
                    "execution_lease_expires_at": None,
                    "updated_at": _utc_now(),
                },
            )
            return True

        try:
            return await release(self.client.transaction())
        except Exception as exc:
            raise CredentialVaultError("could not release connector execution") from exc

    async def begin_disconnect(self, uid: str, connector_id: str) -> StoredConnection | None:
        from google.cloud import firestore

        connector_id = _validate_connector_id(connector_id)
        document = self.collection.document(_document_id(uid, connector_id))

        @firestore.async_transactional
        async def begin(transaction: Any) -> dict[str, Any] | None:
            snapshot = await document.get(transaction=transaction)
            if not snapshot.exists:
                return None
            record = snapshot.to_dict() or {}
            if not hmac.compare_digest(str(record.get("owner_hash", "")), _owner_hash(uid)):
                return None
            if record.get("status") != "verifying" and _lease_is_active(record):
                raise CredentialVaultBusy("connector execution is in progress")
            generation = record.get("credential_generation")
            if not isinstance(generation, str) or not _GENERATION.fullmatch(generation):
                generation = _new_generation()
            updates = {
                "credential_generation": generation,
                "status": "needs_attention",
                "tool_count": 0,
                "verified_at": None,
                "error_code": "disconnect_pending",
                "canary_tool": None,
                "tool_schema_sha256": None,
                "proof_version": None,
                "certified_tools": [],
                "certified_manifest_sha256": None,
                "execution_lease": None,
                "execution_lease_expires_at": None,
                "updated_at": _utc_now(),
            }
            transaction.update(document, updates)
            return {**record, **updates}

        try:
            record = await begin(self.client.transaction())
            if record is None:
                return None
            plaintext = await asyncio.to_thread(
                self.cipher.open,
                record,
                _associated_data(uid, connector_id),
            )
            payload = json.loads(plaintext)
            return StoredConnection(
                _public_record(record),
                ConnectorSecret(value=payload["value"], kind=payload["kind"]),
            )
        except CredentialVaultBusy:
            raise
        except (KeyError, TypeError, ValueError, UnicodeDecodeError):
            raise CredentialVaultError("stored connector credential is invalid") from None
        except Exception as exc:
            raise CredentialVaultError("could not begin connector disconnect") from exc

    async def mark(
        self,
        uid: str,
        connector_id: str,
        *,
        status: str,
        tool_count: int = 0,
        error_code: str | None = None,
        canary_tool: str | None = None,
        tool_schema_sha256: str | None = None,
        proof_version: str | None = None,
        certified_tools: tuple[tuple[str, str], ...] = (),
        certified_manifest_sha256: str | None = None,
    ) -> ConnectionRecord:
        connector_id = _validate_connector_id(connector_id)
        if status not in _CONNECTION_STATUSES or not 0 <= tool_count <= 128:
            raise CredentialVaultError("invalid connector status")
        tools = _validate_certification(
            status=status,
            tool_count=tool_count,
            canary_tool=canary_tool,
            tool_schema_sha256=tool_schema_sha256,
            proof_version=proof_version,
            certified_tools=certified_tools,
            certified_manifest_sha256_value=certified_manifest_sha256,
        )
        document = self.collection.document(_document_id(uid, connector_id))
        snapshot = await document.get()
        if not snapshot.exists:
            raise CredentialVaultError("connector credential does not exist")
        record = snapshot.to_dict() or {}
        if not hmac.compare_digest(str(record.get("owner_hash", "")), _owner_hash(uid)):
            raise CredentialVaultError("connector credential does not exist")
        now = _utc_now()
        updates: dict[str, Any] = {
            "status": status,
            "tool_count": tool_count,
            "verified_at": now if status == "ready" else None,
            "error_code": error_code,
            "canary_tool": canary_tool if status == "ready" else None,
            "tool_schema_sha256": (tool_schema_sha256 if status == "ready" else None),
            "proof_version": proof_version if status == "ready" else None,
            "certified_tools": (
                [{"name": name, "schema_sha256": digest} for name, digest in tools]
                if status == "ready"
                else []
            ),
            "certified_manifest_sha256": (certified_manifest_sha256 if status == "ready" else None),
            "execution_lease": None,
            "execution_lease_expires_at": None,
            "updated_at": now,
        }
        await document.update(updates)
        return _public_record({**record, **updates})

    async def delete(
        self,
        uid: str,
        connector_id: str,
        *,
        expected_generation: str | None = None,
        require_disconnect: bool = False,
    ) -> bool:
        from google.cloud import firestore

        connector_id = _validate_connector_id(connector_id)
        document = self.collection.document(_document_id(uid, connector_id))

        @firestore.async_transactional
        async def remove(transaction: Any) -> bool:
            snapshot = await document.get(transaction=transaction)
            if not snapshot.exists:
                return False
            record = snapshot.to_dict() or {}
            if not hmac.compare_digest(str(record.get("owner_hash", "")), _owner_hash(uid)):
                return False
            if (
                expected_generation is not None
                and record.get("credential_generation") != expected_generation
            ):
                return False
            if require_disconnect and record.get("error_code") != "disconnect_pending":
                return False
            transaction.delete(document)
            return True

        try:
            return await remove(self.client.transaction())
        except Exception as exc:
            raise CredentialVaultError("could not delete connector credential") from exc


def _public_record(record: dict[str, Any]) -> ConnectionRecord:
    try:
        lease_expiry = record.get("execution_lease_expires_at")
        if isinstance(lease_expiry, str):
            lease_expiry = dt.datetime.fromisoformat(lease_expiry)
        if lease_expiry is not None and not isinstance(lease_expiry, dt.datetime):
            raise CredentialVaultError("stored connector metadata is invalid")
        return ConnectionRecord(
            connector_id=_validate_connector_id(record["connector_id"]),
            credential_kind=str(record["credential_kind"]),
            status=str(record["status"]),
            created_at=str(record["created_at"]),
            updated_at=str(record["updated_at"]),
            tool_count=int(record.get("tool_count", 0)),
            verified_at=(
                str(record["verified_at"]) if record.get("verified_at") is not None else None
            ),
            error_code=(
                str(record["error_code"]) if record.get("error_code") is not None else None
            ),
            canary_tool=(
                str(record["canary_tool"]) if record.get("canary_tool") is not None else None
            ),
            tool_schema_sha256=(
                str(record["tool_schema_sha256"])
                if record.get("tool_schema_sha256") is not None
                else None
            ),
            proof_version=(
                str(record["proof_version"]) if record.get("proof_version") is not None else None
            ),
            credential_generation=str(record.get("credential_generation", "")),
            certified_tools=_normalize_certified_tools(record.get("certified_tools", ())),
            certified_manifest_sha256=(
                str(record["certified_manifest_sha256"])
                if record.get("certified_manifest_sha256") is not None
                else None
            ),
            execution_lease=(
                str(record["execution_lease"])
                if record.get("execution_lease") is not None
                else None
            ),
            execution_lease_expires_at=lease_expiry,
        )
    except (KeyError, TypeError, ValueError, CredentialVaultError):
        raise CredentialVaultError("stored connector metadata is invalid") from None


def make_connector_vault() -> ConnectorVault:
    backend = os.getenv("RALLY_VAULT_BACKEND", "")
    if backend == "google_kms":
        return GoogleKmsConnectorVault(
            project_id=os.getenv("GOOGLE_CLOUD_PROJECT", ""),
            key_name=os.getenv("RALLY_KMS_KEY", ""),
        )
    if backend == "memory" and os.getenv("RALLY_ALLOW_INSECURE_DEV") == "1":
        return MemoryConnectorVault()
    raise CredentialVaultError("connector credential vault is not configured")
