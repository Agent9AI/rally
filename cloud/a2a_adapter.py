"""A2A Protocol v1.0 adapter for Rally's governed commission boundary."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Awaitable, Callable
from typing import Any

from a2a.helpers import (
    get_message_text,
    new_text_message,
    new_text_part,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_jsonrpc_routes,
    create_rest_routes,
)
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentProvider,
    AgentSkill,
    APIKeySecurityScheme,
    HTTPAuthSecurityScheme,
    Part,
    SecurityRequirement,
    SecurityScheme,
    StringList,
    Task,
    TaskState,
    TaskStatus,
)
from a2a.utils.errors import A2AError
from fastapi import FastAPI
from google.protobuf import json_format
from google.protobuf.struct_pb2 import Value

from a2a_store import make_a2a_task_store

SubmitCommission = Callable[..., Awaitable[dict[str, Any]]]
MAX_TASK_CHARS = 12_000
DEFAULT_A2A_BASE_URL = "https://rally-google-coordinator-u5xngrbzna-ue.a.run.app"


def build_agent_card(base_url: str | None = None) -> AgentCard:
    """Build the public, least-claim Agent Card for the deployed coordinator."""
    base = (base_url or os.getenv("RALLY_A2A_BASE_URL") or DEFAULT_A2A_BASE_URL).rstrip("/")
    auth_requirement = SecurityRequirement(
        schemes={
            "google_cloud_identity": StringList(),
            "rally_service_token": StringList(),
        }
    )
    return AgentCard(
        name="Rally Accountable AI Team",
        description=(
            "Commissions a governed Rally run: Gemini coordinates the bounded handoff, "
            "specialist agents perform the work, and a different agent must verify it."
        ),
        supported_interfaces=[
            AgentInterface(
                url=base,
                protocol_binding="JSONRPC",
                protocol_version="1.0",
            ),
            AgentInterface(
                url=f"{base}/a2a/rest",
                protocol_binding="HTTP+JSON",
                protocol_version="1.0",
            ),
        ],
        provider=AgentProvider(organization="Agent9 AI", url="https://agent9.dev"),
        version="1.0.0",
        documentation_url="https://github.com/Agent9AI/rally/blob/main/docs/A2A.md",
        icon_url="https://agent9-rally.pages.dev/rally-mark.svg",
        capabilities=AgentCapabilities(
            streaming=True,
            push_notifications=False,
            extended_agent_card=False,
        ),
        security_schemes={
            "google_cloud_identity": SecurityScheme(
                http_auth_security_scheme=HTTPAuthSecurityScheme(
                    description="Google Cloud Run identity token for the Rally service audience.",
                    scheme="bearer",
                    bearer_format="Google OIDC ID token",
                )
            ),
            "rally_service_token": SecurityScheme(
                api_key_security_scheme=APIKeySecurityScheme(
                    description="Rally tenant service credential.",
                    location="header",
                    name="X-Rally-Service-Token",
                )
            ),
        },
        security_requirements=[auth_requirement],
        default_input_modes=["text/plain"],
        default_output_modes=["application/json", "text/plain"],
        skills=[
            AgentSkill(
                id="commission_governed_run",
                name="Commission an accountable AI team",
                description=(
                    "Accepts one bounded objective and returns a safe receipt for the durable "
                    "Rally run created through Gemini, Google ADK, Cloud Run, and Firestore."
                ),
                tags=["governance", "verification", "asynchronous-workflows", "google-adk"],
                examples=[
                    "Review this webhook change, repair any replay risk, and return evidence.",
                    "Prepare this repository for launch and independently verify every claim.",
                ],
                input_modes=["text/plain"],
                output_modes=["application/json", "text/plain"],
                security_requirements=[auth_requirement],
            )
        ],
    )


class RallyA2AExecutor(AgentExecutor):
    """Translate A2A messages into the same governed commission used by Rally's API."""

    def __init__(self, submit_commission: SubmitCommission, base_url: str) -> None:
        self.submit_commission = submit_commission
        self.base_url = base_url.rstrip("/")

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        message = context.message
        if message is None:
            return
        if os.getenv("RALLY_A2A_TCK_MODE") == "1":
            await self._execute_tck(context, event_queue)
            return
        task = context.current_task or Task(
            id=context.task_id,
            context_id=context.context_id,
            status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
            history=[message],
        )
        if context.current_task is None:
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        objective = get_message_text(message).strip()
        if not objective:
            await updater.reject(new_text_message("Rally requires one text objective."))
            return
        if len(objective) > MAX_TASK_CHARS:
            await updater.reject(
                new_text_message(
                    f"The objective exceeds Rally's {MAX_TASK_CHARS:,}-character limit."
                )
            )
            return

        await updater.start_work(new_text_message("Rally is governing the commission."))
        message_id = message.message_id
        digest = hashlib.sha256(message_id.encode()).hexdigest()[:16]
        run_id = f"r-a2a-{digest}"
        try:
            record = await self.submit_commission(
                objective,
                run_id=run_id,
                request_key=f"a2a:{message_id}",
            )
        except Exception:  # noqa: BLE001 - protocol boundary must not expose backend failures
            await updater.failed(
                new_text_message(
                    "Rally could not commission the run. The failure was recorded safely."
                )
            )
            return

        receipt = {
            "accepted": bool(record.get("accepted")),
            "duplicate": bool(record.get("duplicate")),
            "rally_run_id": record["run_id"],
            "status": record["status"],
            "verification_invariant": "owner != verified_by",
            "poll_url": f"{self.base_url}/v1/runs/{record['run_id']}",
        }
        await updater.add_artifact(
            name="rally-commission-receipt.json",
            parts=[
                new_text_part(
                    text=json.dumps(receipt, separators=(",", ":"), sort_keys=True),
                    media_type="application/json",
                )
            ],
        )
        await updater.complete(
            new_text_message("Commission accepted into Rally's governed run ledger.")
        )

    async def _execute_tck(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Serve the official TCK fixtures only when explicitly enabled for local testing."""
        message = context.message
        if message is None or context.task_id is None or context.context_id is None:
            return
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        message_id = message.message_id

        if message_id.startswith("tck-message-response"):
            await event_queue.enqueue_event(
                updater.new_agent_message([Part(text="Direct message response")])
            )
            return
        if message_id.startswith("tck-reject-task"):
            raise A2AError("rejected")

        if context.current_task is None:
            await event_queue.enqueue_event(
                Task(
                    id=context.task_id,
                    context_id=context.context_id,
                    status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
                    history=[message],
                )
            )

        if message_id.startswith("tck-stream-artifact-chunked"):
            await updater.start_work()
            await updater.add_artifact(parts=[Part(text="chunk-1 ")], append=True)
            await updater.add_artifact(parts=[Part(text="chunk-2")], append=True, last_chunk=True)
            await updater.complete()
        elif message_id.startswith("test-resubscribe-message-id"):
            await updater.start_work()
            await asyncio.sleep(4)
            await updater.complete()
        elif message_id.startswith("tck-stream-artifact-text"):
            await updater.start_work()
            await updater.add_artifact(parts=[Part(text="Streamed text content")])
            await updater.complete()
        elif message_id.startswith("tck-stream-artifact-file"):
            await updater.start_work()
            await updater.add_artifact(
                parts=[Part(raw=b"tck", media_type="text/plain", filename="output.txt")]
            )
            await updater.complete()
        elif message_id.startswith("tck-stream-ordering-001"):
            await updater.start_work()
            await updater.add_artifact(parts=[Part(text="Ordered output")])
            await updater.complete()
        elif message_id.startswith("tck-artifact-file-url"):
            await updater.add_artifact(
                parts=[
                    Part(
                        url="https://example.com/output.txt",
                        media_type="text/plain",
                        filename="output.txt",
                    )
                ]
            )
            await updater.complete()
        elif message_id.startswith("tck-input-required"):
            await updater.requires_input()
        elif message_id.startswith("tck-complete-task"):
            await updater.complete(updater.new_agent_message([Part(text="Hello from TCK")]))
        elif message_id.startswith("tck-artifact-text"):
            await updater.add_artifact(parts=[Part(text="Generated text content")])
            await updater.complete()
        elif message_id.startswith("tck-artifact-file"):
            await updater.add_artifact(
                parts=[Part(raw=b"tck", media_type="text/plain", filename="output.txt")]
            )
            await updater.complete()
        elif message_id.startswith("tck-artifact-data"):
            await updater.add_artifact(
                parts=[Part(data=json_format.Parse('{"key":"value","count":42}', Value()))]
            )
            await updater.complete()
        elif message_id.startswith("tck-stream-001"):
            await updater.start_work()
            await updater.add_artifact(parts=[Part(text="Stream hello from TCK")])
            await updater.complete()
        elif message_id.startswith("tck-stream-002"):
            await updater.complete()
        elif message_id.startswith("tck-stream-003"):
            await updater.start_work()
            await updater.add_artifact(parts=[Part(text="Stream task lifecycle")])
            await updater.complete()
        else:
            await updater.complete(
                updater.new_agent_message([Part(text="Unhandled messageId prefix: " + message_id)])
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        if os.getenv("RALLY_A2A_TCK_MODE") == "1":
            if context.task_id is not None and context.context_id is not None:
                await TaskUpdater(event_queue, context.task_id, context.context_id).cancel()
            return
        raise NotImplementedError(
            "Rally commissions cannot be canceled through A2A in this release."
        )


def install_a2a_routes(
    app: FastAPI,
    submit_commission: SubmitCommission,
    base_url: str | None = None,
) -> AgentCard:
    """Attach discoverable JSON-RPC and HTTP+JSON v1.0 routes to FastAPI."""
    card = build_agent_card(base_url)
    interface_base = card.supported_interfaces[0].url.rstrip("/")
    task_store = make_a2a_task_store()
    handler = DefaultRequestHandler(
        agent_executor=RallyA2AExecutor(submit_commission, interface_base),
        task_store=task_store,
        agent_card=card,
    )
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(card),
        jsonrpc_routes=[
            *create_jsonrpc_routes(handler, "/"),
            *create_jsonrpc_routes(handler, "/a2a"),
        ],
        rest_routes=create_rest_routes(handler, path_prefix="/a2a/rest"),
    )
    return card
