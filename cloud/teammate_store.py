"""Workspace-scoped teammate and email-identity persistence for Rally onboarding."""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import os
import secrets
from dataclasses import asdict, dataclass
from typing import Any, Protocol


class TeammateStoreError(RuntimeError):
    """A teammate record could not be persisted safely."""


class TeammateConflict(TeammateStoreError):
    """The requested teammate address already belongs to a workspace."""


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _document_id(*values: str) -> str:
    material = "\x1f".join(values).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _new_teammate_id() -> str:
    return "tm-" + secrets.token_hex(8)


@dataclass(frozen=True)
class TeammateRecord:
    teammate_id: str
    workspace_id: str
    name: str
    role: str
    custom_role: str | None
    human_owner_email: str
    email_address: str
    email_local_part: str
    email_domain: str
    email_provider: str
    connection_method: str
    email_status: str
    reachability: str
    allowed_senders: tuple[str, ...]
    created_by_uid: str
    created_at: dt.datetime
    updated_at: dt.datetime


def public_teammate(record: TeammateRecord) -> dict[str, object]:
    """Return the browser-safe teammate shape without durable identity internals."""

    return {
        "teammate_id": record.teammate_id,
        "name": record.name,
        "role": record.role,
        "custom_role": record.custom_role,
        "human_owner_email": record.human_owner_email,
        "email": {
            "address": record.email_address,
            "local_part": record.email_local_part,
            "domain": record.email_domain,
            "provider": record.email_provider,
            "connection_method": record.connection_method,
            "status": record.email_status,
        },
        "reachability": record.reachability,
        "allowed_senders": list(record.allowed_senders),
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


class TeammateStore(Protocol):
    async def create(
        self,
        *,
        workspace_id: str,
        created_by_uid: str,
        name: str,
        role: str,
        custom_role: str | None,
        human_owner_email: str,
        email_local_part: str,
        email_domain: str,
        email_provider: str,
        connection_method: str,
        email_status: str,
        reachability: str,
        allowed_senders: tuple[str, ...],
    ) -> TeammateRecord: ...

    async def list(self, workspace_id: str) -> list[TeammateRecord]: ...


class MemoryTeammateStore:
    """Deterministic test store with tenant-safe pending address claims."""

    def __init__(self, *, clock: Any = _utc_now) -> None:
        self._clock = clock
        self._records: dict[tuple[str, str], TeammateRecord] = {}
        self._addresses: dict[tuple[str, str], tuple[str, str]] = {}
        self._lock = asyncio.Lock()

    async def create(self, **values: Any) -> TeammateRecord:
        address = f"{values['email_local_part']}@{values['email_domain']}".casefold()
        # A Rally-domain trial identity is globally scarce. Customer-domain
        # identities remain workspace-scoped until domain ownership is proved;
        # otherwise an unverified tenant could squat another company's address.
        address_scope = (
            "global" if values["email_provider"] == "rally_trial" else values["workspace_id"]
        )
        address_key = (address_scope, address)
        async with self._lock:
            if address_key in self._addresses:
                raise TeammateConflict("email address is already assigned")
            teammate_id = _new_teammate_id()
            now = self._clock()
            record = TeammateRecord(
                teammate_id=teammate_id,
                email_address=address,
                created_at=now,
                updated_at=now,
                **values,
            )
            key = (record.workspace_id, teammate_id)
            self._records[key] = record
            self._addresses[address_key] = key
            return record

    async def list(self, workspace_id: str) -> list[TeammateRecord]:
        async with self._lock:
            records = [
                record
                for (record_workspace, _), record in self._records.items()
                if record_workspace == workspace_id
            ]
        return sorted(records, key=lambda record: (record.created_at, record.teammate_id))


class FirestoreTeammateStore:
    """Firestore-backed workspace store with an atomic global address claim."""

    def __init__(self, project_id: str, firestore_client: Any | None = None) -> None:
        if not project_id:
            raise TeammateStoreError("Google Cloud project is not configured")
        if firestore_client is None:
            from google.cloud import firestore

            firestore_client = firestore.AsyncClient(project=project_id)
        self.client = firestore_client
        self.teammates = self.client.collection("rally_teammates")
        self.addresses = self.client.collection("rally_teammate_addresses")

    async def create(self, **values: Any) -> TeammateRecord:
        from google.cloud import firestore

        teammate_id = _new_teammate_id()
        address = f"{values['email_local_part']}@{values['email_domain']}".casefold()
        address_scope = (
            "global" if values["email_provider"] == "rally_trial" else values["workspace_id"]
        )
        now = _utc_now()
        record = TeammateRecord(
            teammate_id=teammate_id,
            email_address=address,
            created_at=now,
            updated_at=now,
            **values,
        )
        teammate_ref = self.teammates.document(
            _document_id(record.workspace_id, teammate_id)
        )
        address_ref = self.addresses.document(_document_id(address_scope, address))

        @firestore.async_transactional
        async def reserve(transaction: Any) -> None:
            existing = await address_ref.get(transaction=transaction)
            if existing.exists:
                raise TeammateConflict("email address is already assigned")
            transaction.create(
                address_ref,
                {
                    "email_address": address,
                    "claim_scope": address_scope,
                    "workspace_id": record.workspace_id,
                    "teammate_id": teammate_id,
                    "created_at": now,
                },
            )
            transaction.create(teammate_ref, asdict(record))

        try:
            await reserve(self.client.transaction())
        except TeammateConflict:
            raise
        except Exception as exc:
            raise TeammateStoreError("could not create teammate") from exc
        return record

    async def list(self, workspace_id: str) -> list[TeammateRecord]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        records: list[TeammateRecord] = []
        try:
            query = self.teammates.where(filter=FieldFilter("workspace_id", "==", workspace_id))
            async for snapshot in query.stream():
                raw = snapshot.to_dict() or {}
                records.append(_record_from_mapping(raw))
        except TeammateStoreError:
            raise
        except Exception as exc:
            raise TeammateStoreError("could not list teammates") from exc
        return sorted(records, key=lambda record: (record.created_at, record.teammate_id))


def _record_from_mapping(raw: dict[str, Any]) -> TeammateRecord:
    try:
        allowed = raw.get("allowed_senders") or ()
        created_at = raw["created_at"]
        updated_at = raw["updated_at"]
        if not isinstance(allowed, (list, tuple)):
            raise TeammateStoreError("stored teammate record is invalid")
        if not isinstance(created_at, dt.datetime) or not isinstance(
            updated_at, dt.datetime
        ):
            raise TeammateStoreError("stored teammate record is invalid")
        return TeammateRecord(
            teammate_id=str(raw["teammate_id"]),
            workspace_id=str(raw["workspace_id"]),
            name=str(raw["name"]),
            role=str(raw["role"]),
            custom_role=(str(raw["custom_role"]) if raw.get("custom_role") else None),
            human_owner_email=str(raw["human_owner_email"]),
            email_address=str(raw["email_address"]),
            email_local_part=str(raw["email_local_part"]),
            email_domain=str(raw["email_domain"]),
            email_provider=str(raw["email_provider"]),
            connection_method=str(raw["connection_method"]),
            email_status=str(raw["email_status"]),
            reachability=str(raw["reachability"]),
            allowed_senders=tuple(str(value) for value in allowed),
            created_by_uid=str(raw["created_by_uid"]),
            created_at=created_at,
            updated_at=updated_at,
        )
    except (KeyError, TypeError, ValueError):
        raise TeammateStoreError("stored teammate record is invalid") from None


def make_teammate_store() -> TeammateStore:
    backend = os.getenv("RALLY_TEAMMATE_BACKEND", os.getenv("RALLY_AUTH_BACKEND", ""))
    if backend == "firestore":
        return FirestoreTeammateStore(os.getenv("GOOGLE_CLOUD_PROJECT", ""))
    if backend == "memory" and os.getenv("RALLY_ALLOW_INSECURE_DEV") == "1":
        return MemoryTeammateStore()
    raise TeammateStoreError("teammate store is not configured")
