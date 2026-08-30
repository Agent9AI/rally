"""Public, end-user-authenticated control plane for Rally connections."""

from __future__ import annotations

import os
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, SecretStr
from starlette.requests import Request
from starlette.responses import JSONResponse

from credential_vault import (
    ConnectionRecord,
    ConnectorSecret,
    ConnectorVault,
    CredentialVaultError,
    make_connector_vault,
)
from user_auth import UserIdentity, require_user

SUPPORTED_CONNECTORS = frozenset(
    {
        "atlassian",
        "cloudflare",
        "github",
        "google-workspace",
        "hyperagent",
        "n8n",
        "salesforce",
        "slack",
        "stripe",
    }
)

app = FastAPI(title="Rally Control Plane", version="0.1")
allowed_origins = tuple(
    origin.strip()
    for origin in os.getenv("RALLY_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(allowed_origins),
    allow_credentials=False,
    allow_methods=["GET", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    max_age=600,
)

_vault: ConnectorVault | None = None


@app.exception_handler(RequestValidationError)
async def invalid_request(_: Request, __: RequestValidationError) -> JSONResponse:
    """Never reflect a rejected credential value in FastAPI's validation body."""

    return JSONResponse({"detail": "invalid request"}, status_code=422)


def get_vault() -> ConnectorVault:
    global _vault
    if _vault is None:
        try:
            _vault = make_connector_vault()
        except CredentialVaultError as exc:
            raise HTTPException(status_code=503, detail="credential vault is unavailable") from exc
    return _vault


@app.middleware("http")
async def response_security(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    return response


class CredentialInput(BaseModel):
    credential: SecretStr = Field(min_length=1, max_length=65536)
    kind: Literal["api_key", "bearer_token", "oauth_refresh_token"]


def public_connection(record: ConnectionRecord) -> dict[str, str | bool]:
    return {
        "connector_id": record.connector_id,
        "credential_kind": record.credential_kind,
        "status": record.status,
        "verified": False,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def validated_connector(connector_id: str) -> str:
    if connector_id not in SUPPORTED_CONNECTORS:
        raise HTTPException(status_code=404, detail="connector is not available")
    return connector_id


@app.get("/health")
@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "rally-control-plane"}


@app.get("/v1/me")
def me(user: Annotated[UserIdentity, Depends(require_user)]) -> dict[str, str | None]:
    return {
        "uid": user.uid,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "hosted_domain": user.hosted_domain,
    }


@app.get("/v1/connections")
async def list_connections(
    user: Annotated[UserIdentity, Depends(require_user)],
    vault: Annotated[ConnectorVault, Depends(get_vault)],
) -> dict[str, list[dict[str, str | bool]]]:
    try:
        records = await vault.list(user.uid)
    except CredentialVaultError as exc:
        raise HTTPException(status_code=503, detail="could not read connections") from exc
    return {"connections": [public_connection(record) for record in records]}


@app.put("/v1/connections/{connector_id}")
async def store_connection(
    connector_id: str,
    body: CredentialInput,
    user: Annotated[UserIdentity, Depends(require_user)],
    vault: Annotated[ConnectorVault, Depends(get_vault)],
) -> dict[str, str | bool]:
    connector_id = validated_connector(connector_id)
    try:
        record = await vault.put(
            user.uid,
            connector_id,
            ConnectorSecret(body.credential.get_secret_value(), body.kind),
        )
    except CredentialVaultError as exc:
        raise HTTPException(status_code=503, detail="could not store connection") from exc
    return public_connection(record)


@app.delete("/v1/connections/{connector_id}")
async def disconnect(
    connector_id: str,
    user: Annotated[UserIdentity, Depends(require_user)],
    vault: Annotated[ConnectorVault, Depends(get_vault)],
) -> dict[str, str | bool]:
    connector_id = validated_connector(connector_id)
    try:
        deleted = await vault.delete(user.uid, connector_id)
    except CredentialVaultError as exc:
        raise HTTPException(status_code=503, detail="could not disconnect provider") from exc
    return {
        "connector_id": connector_id,
        "disconnected": deleted,
        "provider_revocation_recommended": deleted,
    }
