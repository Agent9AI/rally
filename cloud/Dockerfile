FROM python:3.12-slim

RUN pip install --no-cache-dir uv==0.8.13
WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY rally_adk ./rally_adk
COPY agent_catalog.json a2a_adapter.py a2a_store.py catalog.py service.py store.py telemetry.py ./
COPY control_plane.py credential_vault.py user_auth.py ./
RUN uv sync --frozen --no-dev

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    GOOGLE_CLOUD_LOCATION=global \
    GOOGLE_GENAI_USE_VERTEXAI=True \
    GEMINI_MODEL=gemini-3.7-flash \
    RALLY_STATE_BACKEND=firestore \
    RALLY_ENABLE_CLOUD_TRACE=0 \
    ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false \
    OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=NO_CONTENT

EXPOSE 8080
CMD ["uv", "run", "--no-sync", "uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8080"]
