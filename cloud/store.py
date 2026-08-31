"""Durable commission records with a deterministic in-memory test backend."""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from abc import ABC, abstractmethod
from typing import Any


class RunStore(ABC):
    @abstractmethod
    async def create(self, record: dict[str, Any]) -> bool:
        """Atomically claim a request key. Return False when it already exists."""
        ...

    @abstractmethod
    async def update(
        self,
        run_id: str,
        record: dict[str, Any],
        expected_attempt: int | None = None,
    ) -> bool:
        """Persist a record unless a newer coordination attempt owns it."""
        ...

    @abstractmethod
    async def get(self, run_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    async def get_by_request_key(self, request_key: str) -> dict[str, Any] | None: ...

    @abstractmethod
    async def reclaim(
        self,
        request_key: str,
        lease_expires_at: float,
        updated_at: str,
    ) -> dict[str, Any] | None:
        """Atomically resume a failed or expired coordination attempt."""
        ...


class MemoryRunStore(RunStore):
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.request_keys: dict[str, str] = {}
        self.lock = asyncio.Lock()

    async def create(self, record: dict[str, Any]) -> bool:
        async with self.lock:
            request_key = record["request_key"]
            if request_key in self.request_keys:
                return False
            self.records[record["run_id"]] = dict(record)
            self.request_keys[request_key] = record["run_id"]
            return True

    async def update(
        self,
        run_id: str,
        record: dict[str, Any],
        expected_attempt: int | None = None,
    ) -> bool:
        async with self.lock:
            current = self.records.get(run_id)
            if (
                expected_attempt is not None
                and current
                and current.get("attempts") != expected_attempt
            ):
                return False
            self.records[run_id] = dict(record)
            self.request_keys[record["request_key"]] = run_id
            return True

    async def get(self, run_id: str) -> dict[str, Any] | None:
        record = self.records.get(run_id)
        return dict(record) if record else None

    async def get_by_request_key(self, request_key: str) -> dict[str, Any] | None:
        run_id = self.request_keys.get(request_key)
        return await self.get(run_id) if run_id else None

    async def reclaim(
        self,
        request_key: str,
        lease_expires_at: float,
        updated_at: str,
    ) -> dict[str, Any] | None:
        async with self.lock:
            run_id = self.request_keys.get(request_key)
            current = self.records.get(run_id) if run_id else None
            if not current:
                return None
            expired = float(current.get("lease_expires_at") or 0) <= time.time()
            if current.get("status") != "coordinator_failed" and not (
                current.get("status") == "coordinating" and expired
            ):
                return None
            resumed = dict(current)
            resumed["status"] = "coordinating"
            resumed["attempts"] = int(current.get("attempts") or 1) + 1
            resumed["lease_expires_at"] = lease_expires_at
            resumed["updated_at"] = updated_at
            resumed.pop("error", None)
            self.records[run_id] = resumed
            self.request_keys[request_key] = run_id
            return dict(resumed)


class FirestoreRunStore(RunStore):
    def __init__(self) -> None:
        from google.cloud import firestore

        self.client = firestore.AsyncClient(project=os.getenv("GOOGLE_CLOUD_PROJECT"))
        self.runs = self.client.collection("rally_runs")
        self.requests = self.client.collection("rally_request_keys")

    @staticmethod
    def _request_id(request_key: str) -> str:
        # Firestore document IDs cannot contain '/', and webhook IDs are untrusted.
        return hashlib.sha256(request_key.encode()).hexdigest()

    async def create(self, record: dict[str, Any]) -> bool:
        from google.cloud import firestore

        request_ref = self.requests.document(self._request_id(record["request_key"]))
        run_ref = self.runs.document(record["run_id"])

        @firestore.async_transactional
        async def claim(transaction: Any) -> bool:
            snapshot = await request_ref.get(transaction=transaction)
            if snapshot.exists:
                return False
            transaction.set(request_ref, record)
            transaction.set(run_ref, record)
            return True

        return await claim(self.client.transaction())

    async def update(
        self,
        run_id: str,
        record: dict[str, Any],
        expected_attempt: int | None = None,
    ) -> bool:
        from google.cloud import firestore

        run_ref = self.runs.document(run_id)
        request_ref = self.requests.document(self._request_id(record["request_key"]))

        @firestore.async_transactional
        async def persist(transaction: Any) -> bool:
            snapshot = await run_ref.get(transaction=transaction)
            current = snapshot.to_dict() if snapshot.exists else None
            if (
                expected_attempt is not None
                and current
                and current.get("attempts") != expected_attempt
            ):
                return False
            transaction.set(run_ref, record)
            transaction.set(request_ref, record)
            return True

        return await persist(self.client.transaction())

    async def get(self, run_id: str) -> dict[str, Any] | None:
        snapshot = await self.runs.document(run_id).get()
        return snapshot.to_dict() if snapshot.exists else None

    async def get_by_request_key(self, request_key: str) -> dict[str, Any] | None:
        snapshot = await self.requests.document(self._request_id(request_key)).get()
        return snapshot.to_dict() if snapshot.exists else None

    async def reclaim(
        self,
        request_key: str,
        lease_expires_at: float,
        updated_at: str,
    ) -> dict[str, Any] | None:
        from google.cloud import firestore

        request_ref = self.requests.document(self._request_id(request_key))

        @firestore.async_transactional
        async def claim(transaction: Any) -> dict[str, Any] | None:
            snapshot = await request_ref.get(transaction=transaction)
            if not snapshot.exists:
                return None
            current = snapshot.to_dict()
            expired = float(current.get("lease_expires_at") or 0) <= time.time()
            if current.get("status") != "coordinator_failed" and not (
                current.get("status") == "coordinating" and expired
            ):
                return None
            resumed = dict(current)
            resumed["status"] = "coordinating"
            resumed["attempts"] = int(current.get("attempts") or 1) + 1
            resumed["lease_expires_at"] = lease_expires_at
            resumed["updated_at"] = updated_at
            resumed.pop("error", None)
            run_ref = self.runs.document(resumed["run_id"])
            transaction.set(run_ref, resumed)
            transaction.set(request_ref, resumed)
            return resumed

        return await claim(self.client.transaction())


def make_store() -> RunStore:
    if os.getenv("RALLY_STATE_BACKEND", "memory") == "firestore":
        return FirestoreRunStore()
    return MemoryRunStore()
