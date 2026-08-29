"""Cloud Run HTTP surface for Rally's Google ADK coordinator."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os
import time
import uuid
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from opentelemetry import trace
from pydantic import BaseModel, Field
from starlette.requests import Request

from catalog import load_catalog
from rally_adk.agent import app as adk_app
from rally_adk.handoff import build_handoff
from store import RunStore, make_store
from telemetry import configure_logging, configure_tracing

configure_tracing()
logger = configure_logging()
app = FastAPI(title="Rally Google Cloud Coordinator", version="1.0")
session_service = InMemorySessionService()
runner = Runner(app=adk_app, session_service=session_service)
store: RunStore = make_store()
tracer = trace.get_tracer("rally.cloud")
COORDINATION_LEASE_SECONDS = 330
RETENTION_DAYS = 30


@app.middleware("http")
async def request_observability(request: Request, call_next: Any) -> Any:
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Rally-Request-ID"] = request_id
        return response
    finally:
        logger.info(
            "request complete",
            extra={
                "event": "http_request",
                "request_id": request_id,
                "http_method": request.method,
                "http_path": request.url.path,
                "http_status": status,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )


class Commission(BaseModel):
    task: str = Field(min_length=1, max_length=12000)
    run_id: str | None = Field(default=None, pattern=r"^r-[A-Za-z0-9-]{3,80}$")


def require_service_token(token: str | None) -> None:
    expected = os.getenv("RALLY_SERVICE_TOKEN")
    if not expected:
        if os.getenv("RALLY_ALLOW_INSECURE_DEV") == "1":
            return
        raise HTTPException(status_code=503, detail="service authentication is not configured")
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="invalid service token")


async def coordinate(task: str, run_id: str, attempt: int = 1) -> str:
    """Run the request through Gemini via Google ADK and return its final record."""
    session_id = f"{run_id}-a{attempt}"
    await session_service.create_session(
        app_name=adk_app.name,
        user_id="rally-control-plane",
        session_id=session_id,
        state={"run_id": run_id, "attempt": attempt},
    )
    message = types.Content(role="user", parts=[types.Part(text=task)])
    final_text = ""
    async for event in runner.run_async(
        user_id="rally-control-plane",
        session_id=session_id,
        new_message=message,
    ):
        if event.is_final_response() and event.content:
            final_text = "".join(
                part.text or "" for part in (event.content.parts or []) if part.text
            ).strip()
    if not final_text:
        raise RuntimeError("ADK coordinator returned no final response")
    return final_text


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def isoformat(value: dt.datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def task_digest(task: str) -> str:
    return hashlib.sha256(task.encode()).hexdigest()


async def finish_coordination(record: dict[str, Any], task: str) -> dict[str, Any]:
    """Complete one fenced coordination attempt and persist its terminal state."""
    run_id = record["run_id"]
    attempt = int(record.get("attempts") or 1)
    with tracer.start_as_current_span("rally.coordinate") as span:
        span.set_attribute("rally.run_id", run_id)
        span.set_attribute("rally.attempt", attempt)
        try:
            record["coordinator_record"] = await coordinate(task, run_id, attempt)
            record["status"] = "ready_for_rally"
        except Exception as exc:
            record["status"] = "coordinator_failed"
            record["error"] = type(exc).__name__
            record["updated_at"] = isoformat(utc_now())
            record["lease_expires_at"] = None
            await store.update(run_id, record, expected_attempt=attempt)
            logger.exception(
                "commission coordination failed",
                extra={
                    "event": "commission_failed",
                    "run_id": run_id,
                    "status": record["status"],
                },
            )
            raise HTTPException(status_code=502, detail="ADK coordinator failed") from exc

    record["updated_at"] = isoformat(utc_now())
    record["lease_expires_at"] = None
    if not await store.update(run_id, record, expected_attempt=attempt):
        current = await store.get(run_id)
        if current:
            return {**current, "duplicate": True}
        raise HTTPException(status_code=409, detail="coordination ownership changed")
    logger.info(
        "commission ready for Rally",
        extra={
            "event": "commission_ready",
            "run_id": run_id,
            "status": record["status"],
        },
    )
    return record


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "rally-google-coordinator",
        "model": os.getenv("GEMINI_MODEL", "gemini-3.7-flash"),
        "state_backend": os.getenv("RALLY_STATE_BACKEND", "memory"),
    }


@app.get("/v1/agents")
async def agent_catalog(
    x_rally_service_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """Return the governed fleet catalog to authenticated operators."""
    require_service_token(x_rally_service_token)
    return load_catalog()


@app.post("/v1/commissions", status_code=202)
async def commission(
    body: Commission,
    x_rally_service_token: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    require_service_token(x_rally_service_token)
    run_id = body.run_id or "r-" + uuid.uuid4().hex[:10]
    request_key = idempotency_key or run_id
    existing = await store.get_by_request_key(request_key)
    if existing:
        if existing.get("task_digest") != task_digest(body.task):
            raise HTTPException(
                status_code=409,
                detail="idempotency key is already bound to another commission",
            )
        if existing.get("status") in {"coordinator_failed", "coordinating"}:
            resumed = await store.reclaim(
                request_key,
                time.time() + COORDINATION_LEASE_SECONDS,
                isoformat(utc_now()),
            )
            if resumed:
                logger.info(
                    "commission coordination resumed",
                    extra={
                        "event": "commission_resumed",
                        "run_id": resumed.get("run_id"),
                        "status": resumed.get("status"),
                    },
                )
                return await finish_coordination(resumed, body.task)
        logger.info(
            "duplicate commission returned",
            extra={
                "event": "commission_duplicate",
                "run_id": existing.get("run_id"),
                "status": existing.get("status"),
                "duplicate": True,
            },
        )
        return {**existing, "duplicate": True}

    now = utc_now()
    handoff = build_handoff(body.task)
    record: dict[str, Any] = {
        "accepted": True,
        "duplicate": False,
        "run_id": run_id,
        "request_key": request_key,
        "status": "coordinating",
        "handoff": handoff,
        "task_digest": task_digest(body.task),
        "attempts": 1,
        "created_at": isoformat(now),
        "updated_at": isoformat(now),
        "retention_until": isoformat(now + dt.timedelta(days=RETENTION_DAYS)),
        "lease_expires_at": time.time() + COORDINATION_LEASE_SECONDS,
    }
    created = await store.create(record)
    if not created:
        existing = await store.get_by_request_key(request_key)
        if not existing:
            raise HTTPException(status_code=409, detail="idempotent request is still committing")
        return {**existing, "duplicate": True}
    logger.info(
        "commission accepted",
        extra={
            "event": "commission_accepted",
            "run_id": run_id,
            "status": record["status"],
            "duplicate": False,
        },
    )
    return await finish_coordination(record, body.task)


@app.get("/v1/runs/{run_id}")
async def run_status(
    run_id: str,
    x_rally_service_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_service_token(x_rally_service_token)
    record = await store.get(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="run not found")
    return record
