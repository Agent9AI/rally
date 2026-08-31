"""A2A task persistence with Firestore production and memory test backends."""

from __future__ import annotations

import hashlib
import os

from a2a.server.context import ServerCallContext
from a2a.server.owner_resolver import OwnerResolver, resolve_user_scope
from a2a.server.tasks import InMemoryTaskStore, TaskStore
from a2a.types import ListTasksRequest, ListTasksResponse, Task
from a2a.utils.constants import DEFAULT_LIST_TASKS_PAGE_SIZE
from a2a.utils.errors import InvalidParamsError
from a2a.utils.task import decode_page_token, encode_page_token


class FirestoreA2ATaskStore(TaskStore):
    """Persist protocol-native task protobufs in a tenant-scoped collection."""

    def __init__(self, owner_resolver: OwnerResolver = resolve_user_scope) -> None:
        from google.cloud import firestore

        self.client = firestore.AsyncClient(project=os.getenv("GOOGLE_CLOUD_PROJECT"))
        self.tasks = self.client.collection("rally_a2a_tasks")
        self.owner_resolver = owner_resolver

    @staticmethod
    def _document_id(owner: str, task_id: str) -> str:
        return hashlib.sha256(f"{owner}\0{task_id}".encode()).hexdigest()

    async def save(self, task: Task, context: ServerCallContext) -> None:
        owner = self.owner_resolver(context)
        timestamp = (
            task.status.timestamp.ToJsonString()
            if task.HasField("status") and task.status.HasField("timestamp")
            else ""
        )
        await self.tasks.document(self._document_id(owner, task.id)).set(
            {
                "owner": owner,
                "task_id": task.id,
                "context_id": task.context_id,
                "state": int(task.status.state),
                "status_timestamp": timestamp,
                "task_proto": task.SerializeToString(deterministic=True),
            }
        )

    async def get(self, task_id: str, context: ServerCallContext) -> Task | None:
        owner = self.owner_resolver(context)
        snapshot = await self.tasks.document(self._document_id(owner, task_id)).get()
        if not snapshot.exists:
            return None
        record = snapshot.to_dict() or {}
        payload = record.get("task_proto")
        return Task.FromString(bytes(payload)) if payload else None

    async def list(
        self,
        params: ListTasksRequest,
        context: ServerCallContext,
    ) -> ListTasksResponse:
        from google.cloud.firestore_v1.base_query import FieldFilter

        owner = self.owner_resolver(context)
        query = self.tasks.where(filter=FieldFilter("owner", "==", owner))
        records = [snapshot.to_dict() async for snapshot in query.stream()]
        tasks = [
            Task.FromString(bytes(record["task_proto"]))
            for record in records
            if record and record.get("task_proto")
        ]

        if params.context_id:
            tasks = [task for task in tasks if task.context_id == params.context_id]
        if params.status:
            tasks = [task for task in tasks if task.status.state == params.status]
        if params.HasField("status_timestamp_after"):
            threshold = params.status_timestamp_after.ToJsonString()
            tasks = [
                task
                for task in tasks
                if task.HasField("status")
                and task.status.HasField("timestamp")
                and task.status.timestamp.ToJsonString() >= threshold
            ]

        tasks.sort(
            key=lambda task: (
                task.status.timestamp.ToJsonString()
                if task.HasField("status") and task.status.HasField("timestamp")
                else "",
                task.id,
            ),
            reverse=True,
        )

        total_size = len(tasks)
        start = 0
        if params.page_token:
            start_task_id = decode_page_token(params.page_token)
            try:
                start = next(i for i, task in enumerate(tasks) if task.id == start_task_id)
            except StopIteration as exc:
                raise InvalidParamsError(f"Invalid page token: {params.page_token}") from exc
        page_size = params.page_size or DEFAULT_LIST_TASKS_PAGE_SIZE
        end = start + page_size
        next_page_token = encode_page_token(tasks[end].id) if end < total_size else None
        return ListTasksResponse(
            tasks=tasks[start:end],
            next_page_token=next_page_token,
            page_size=page_size,
            total_size=total_size,
        )

    async def delete(self, task_id: str, context: ServerCallContext) -> None:
        owner = self.owner_resolver(context)
        await self.tasks.document(self._document_id(owner, task_id)).delete()


def make_a2a_task_store() -> TaskStore:
    """Select the same durable boundary as Rally's run ledger."""
    if os.getenv("RALLY_STATE_BACKEND", "memory") == "firestore":
        return FirestoreA2ATaskStore()
    return InMemoryTaskStore()
