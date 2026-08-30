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
from dataclasses import dataclass
from typing import Any, Final, Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CredentialVaultError(RuntimeError):
    """Credential storage failed without disclosing secret material."""


_CONNECTOR_ID: Final = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_MAX_SECRET_BYTES: Final = 64 * 1024
_ENVELOPE_SCHEMA: Final = "rally.connector-secret/v1"


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


@dataclass(frozen=True)
class ConnectionRecord:
    connector_id: str
    credential_kind: str
    status: str
    created_at: str
    updated_at: str


class ConnectorVault(Protocol):
    async def put(self, uid: str, connector_id: str, secret: ConnectorSecret) -> ConnectionRecord: ...

    async def list(self, uid: str) -> list[ConnectionRecord]: ...

    async def get_secret(self, uid: str, connector_id: str) -> ConnectorSecret | None: ...

    async def delete(self, uid: str, connector_id: str) -> bool: ...


class KmsEnvelopeCipher:
    """One random AES-GCM DEK per credential, wrapped by a Cloud KMS KEK."""

    def __init__(self, key_name: str, client: Any | None = None):
        if not key_name.startswith("projects/") or "/cryptoKeys/" not in key_name:
            raise CredentialVaultError("invalid Cloud KMS key name")
        if client is None:
            from google.cloud import kms

            client = kms.KeyManagementServiceClient()
        self.key_name = key_name
        self.client = client

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
            "schema": _ENVELOPE_SCHEMA,
            "nonce": _encode(nonce),
            "ciphertext": _encode(ciphertext),
            "wrapped_dek": _encode(wrapped),
            "kms_key": self.key_name,
        }

    def open(self, envelope: dict[str, Any], associated_data: bytes) -> bytes:
        if envelope.get("schema") != _ENVELOPE_SCHEMA:
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

    async def put(
        self, uid: str, connector_id: str, secret: ConnectorSecret
    ) -> ConnectionRecord:
        connector_id = _validate_connector_id(connector_id)
        key = (uid, connector_id)
        now = _utc_now()
        created_at = self._items[key][1].created_at if key in self._items else now
        record = ConnectionRecord(
            connector_id=connector_id,
            credential_kind=secret.kind,
            status="stored_unverified",
            created_at=created_at,
            updated_at=now,
        )
        self._items[key] = (secret, record)
        return record

    async def list(self, uid: str) -> list[ConnectionRecord]:
        return sorted(
            (record for (owner, _), (_, record) in self._items.items() if owner == uid),
            key=lambda item: item.connector_id,
        )

    async def get_secret(self, uid: str, connector_id: str) -> ConnectorSecret | None:
        item = self._items.get((uid, _validate_connector_id(connector_id)))
        return item[0] if item else None

    async def delete(self, uid: str, connector_id: str) -> bool:
        return self._items.pop((uid, _validate_connector_id(connector_id)), None) is not None


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
        self.collection = firestore_client.collection("connector_credentials")
        self.cipher = KmsEnvelopeCipher(key_name, client=kms_client)

    async def put(
        self, uid: str, connector_id: str, secret: ConnectorSecret
    ) -> ConnectionRecord:
        connector_id = _validate_connector_id(connector_id)
        document = self.collection.document(_document_id(uid, connector_id))
        previous = await document.get()
        now = _utc_now()
        created_at = (
            str((previous.to_dict() or {}).get("created_at"))
            if previous.exists
            else now
        )
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
            "status": "stored_unverified",
            "created_at": created_at,
            "updated_at": now,
        }
        await document.set(record)
        return _public_record(record)

    async def list(self, uid: str) -> list[ConnectionRecord]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = self.collection.where(filter=FieldFilter("owner_hash", "==", _owner_hash(uid)))
        records = [_public_record(snapshot.to_dict()) async for snapshot in query.stream()]
        return sorted(records, key=lambda item: item.connector_id)

    async def get_secret(self, uid: str, connector_id: str) -> ConnectorSecret | None:
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
            return ConnectorSecret(value=payload["value"], kind=payload["kind"])
        except (KeyError, TypeError, ValueError, UnicodeDecodeError):
            raise CredentialVaultError("stored connector credential is invalid") from None

    async def delete(self, uid: str, connector_id: str) -> bool:
        connector_id = _validate_connector_id(connector_id)
        document = self.collection.document(_document_id(uid, connector_id))
        snapshot = await document.get()
        if not snapshot.exists:
            return False
        record = snapshot.to_dict() or {}
        if not hmac.compare_digest(str(record.get("owner_hash", "")), _owner_hash(uid)):
            return False
        await document.delete()
        return True


def _public_record(record: dict[str, Any]) -> ConnectionRecord:
    try:
        return ConnectionRecord(
            connector_id=_validate_connector_id(record["connector_id"]),
            credential_kind=str(record["credential_kind"]),
            status=str(record["status"]),
            created_at=str(record["created_at"]),
            updated_at=str(record["updated_at"]),
        )
    except (KeyError, TypeError, CredentialVaultError):
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
