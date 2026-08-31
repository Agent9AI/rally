import os

import telemetry


def test_configure_tracing_disables_content_for_adk_and_genai(monkeypatch):
    monkeypatch.setenv("RALLY_ENABLE_CLOUD_TRACE", "0")
    monkeypatch.delenv("ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS", raising=False)
    monkeypatch.delenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", raising=False)

    telemetry.configure_tracing()

    assert os.environ["ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS"] == "false"
    assert os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] == "NO_CONTENT"
