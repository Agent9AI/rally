"""Metadata-only OpenTelemetry setup for Cloud Run and Gemini."""
from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

from opentelemetry import trace


class JsonFormatter(logging.Formatter):
    """Emit Cloud Logging-compatible JSON without prompt or response content."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "service": "rally-google-coordinator",
        }
        for key in (
            "event",
            "request_id",
            "run_id",
            "status",
            "http_method",
            "http_path",
            "http_status",
            "latency_ms",
            "duplicate",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        span = trace.get_current_span()
        context = span.get_span_context()
        if context.is_valid:
            project = os.getenv("GOOGLE_CLOUD_PROJECT", "")
            if project:
                payload["logging.googleapis.com/trace"] = (
                    f"projects/{project}/traces/{context.trace_id:032x}"
                )
            payload["logging.googleapis.com/spanId"] = f"{context.span_id:016x}"
        return json.dumps(payload, separators=(",", ":"), default=str)


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("rally.cloud")
    logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    return logger


def configure_tracing() -> None:
    """Export request and Gemini spans to Cloud Trace when explicitly enabled."""
    # ADK and the GenAI SDK use separate content-capture controls. Set both
    # before either instrumentor is configured so spans retain execution proof
    # (model, token counts, tools, timing) without prompt, response, or tool
    # payloads.
    os.environ.setdefault("ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS", "false")
    os.environ.setdefault(
        "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "NO_CONTENT"
    )
    os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "gen_ai_latest_experimental")
    if os.getenv("RALLY_ENABLE_CLOUD_TRACE", "0") != "1":
        return

    from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
    from opentelemetry.instrumentation.google_genai import GoogleGenAiSdkInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(
        resource=Resource.create({
            "service.name": "rally-google-coordinator",
            "service.version": os.getenv("K_REVISION", "local"),
        })
    )
    provider.add_span_processor(
        BatchSpanProcessor(
            CloudTraceSpanExporter(project_id=os.getenv("GOOGLE_CLOUD_PROJECT"))
        )
    )
    trace.set_tracer_provider(provider)
    GoogleGenAiSdkInstrumentor().instrument(tracer_provider=provider)
