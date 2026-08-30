"""Public, end-user-authenticated control plane for Rally connections."""

from __future__ import annotations

import hmac
import os
from typing import Annotated, Literal
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, SecretStr
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from auth_sessions import (
    AuthSessionError,
    AuthSessionStore,
    make_auth_session_store,
)
from connector_oauth import (
    ConnectorOAuthBroker,
    HostedOAuthError,
    make_oauth_flow_store,
)
from credential_vault import (
    ConnectionRecord,
    ConnectorSecret,
    ConnectorVault,
    CredentialVaultError,
    make_connector_vault,
)
from hosted_connectors import (
    HostedConnectorError,
    McpConnectionVerifier,
    normalize_workflow_ids,
    pack_secret,
    public_catalog,
    resolve_endpoint,
)
from hosted_connectors import (
    connector as hosted_connector,
)
from user_auth import UserIdentity, verify_google_id_token

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
    origin.strip() for origin in os.getenv("RALLY_ALLOWED_ORIGINS", "").split(",") if origin.strip()
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(allowed_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "X-Rally-ID-Token",
        "X-Rally-Session",
        "X-Request-ID",
    ],
    max_age=600,
)

_vault: ConnectorVault | None = None
_auth_store: AuthSessionStore | None = None
_oauth_broker: ConnectorOAuthBroker | None = None
_connection_verifier: McpConnectionVerifier | None = None
_MAX_GOOGLE_FORM_BYTES = 32 * 1024


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


def get_auth_store() -> AuthSessionStore:
    global _auth_store
    if _auth_store is None:
        try:
            _auth_store = make_auth_session_store()
        except AuthSessionError as exc:
            raise HTTPException(
                status_code=503, detail="browser authentication is unavailable"
            ) from exc
    return _auth_store


def get_oauth_broker() -> ConnectorOAuthBroker:
    global _oauth_broker
    if _oauth_broker is None:
        try:
            _oauth_broker = ConnectorOAuthBroker(make_oauth_flow_store())
        except Exception as exc:
            raise HTTPException(status_code=503, detail="connector OAuth is unavailable") from exc
    return _oauth_broker


def get_connection_verifier() -> McpConnectionVerifier:
    global _connection_verifier
    if _connection_verifier is None:
        _connection_verifier = McpConnectionVerifier()
    return _connection_verifier


def _unauthorized(detail: str = "authentication required") -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_user(
    identity_token: str | None = Header(default=None, alias="X-Rally-ID-Token"),
    session_token: str | None = Header(default=None, alias="X-Rally-Session"),
) -> UserIdentity:
    """Accept one browser auth mechanism and reject ambiguous credentials."""

    if bool(identity_token) == bool(session_token):
        raise _unauthorized()
    if identity_token:
        return verify_google_id_token(identity_token)
    try:
        identity = await get_auth_store().get_identity(session_token or "")
    except AuthSessionError as exc:
        raise HTTPException(
            status_code=503, detail="browser authentication is unavailable"
        ) from exc
    if identity is None:
        raise _unauthorized("login session is invalid or expired")
    return identity


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
    endpoint: str | None = Field(default=None, max_length=2048)
    scheme: Literal["bearer", "basic"] = "bearer"
    account: str | None = Field(default=None, max_length=320)
    workflow_ids: list[str] = Field(default_factory=list, max_length=64)


class OAuthStartInput(BaseModel):
    endpoint: str | None = Field(default=None, max_length=2048)
    workflow_ids: list[str] = Field(default_factory=list, max_length=64)


class OAuthCallbackInput(BaseModel):
    state: SecretStr = Field(min_length=32, max_length=128)
    code: SecretStr | None = Field(default=None, min_length=1, max_length=8192)
    error: str | None = Field(default=None, max_length=128)


class LoginCodeInput(BaseModel):
    code: SecretStr = Field(min_length=32, max_length=128)


def public_user(user: UserIdentity) -> dict[str, str | None]:
    return {
        "uid": user.uid,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "hosted_domain": user.hosted_domain,
    }


def admin_return_url() -> str:
    configured = os.getenv("RALLY_ADMIN_RETURN_URL", "https://rally.agent9.dev/admin/")
    parsed = urlsplit(configured)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise HTTPException(status_code=503, detail="browser authentication is unavailable")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", "", ""))


async def bounded_google_form(request: Request) -> dict[str, str]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/x-www-form-urlencoded":
        raise HTTPException(status_code=415, detail="unsupported sign-in response")
    declared = request.headers.get("content-length")
    if declared:
        try:
            if int(declared) > _MAX_GOOGLE_FORM_BYTES:
                raise HTTPException(status_code=413, detail="sign-in response is too large")
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid sign-in response") from None
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > _MAX_GOOGLE_FORM_BYTES:
            raise HTTPException(status_code=413, detail="sign-in response is too large")
    try:
        parsed = parse_qs(
            body.decode("ascii"),
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=8,
        )
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid sign-in response") from None
    if any(len(values) != 1 for values in parsed.values()):
        raise HTTPException(status_code=400, detail="invalid sign-in response")
    return {key: values[0] for key, values in parsed.items()}


def public_connection(record: ConnectionRecord) -> dict[str, object]:
    return {
        "connector_id": record.connector_id,
        "credential_kind": record.credential_kind,
        "status": record.status,
        "verified": record.status == "ready",
        "tool_count": record.tool_count,
        "verified_at": record.verified_at,
        "error_code": record.error_code,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def validated_connector(connector_id: str) -> str:
    if connector_id not in SUPPORTED_CONNECTORS:
        raise HTTPException(status_code=404, detail="connector is not available")
    return connector_id


def connector_return_url(
    *,
    login_code: str | None = None,
    connector_id: str | None = None,
    status: str,
) -> str:
    fragment: dict[str, str] = {"rally-connection-status": status}
    if login_code:
        fragment["rally-login-code"] = login_code
    if connector_id:
        fragment["rally-connection"] = connector_id
    return f"{admin_return_url()}#{urlencode(fragment)}"


@app.get("/health")
@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "rally-control-plane"}


@app.get("/v1/me")
def me(user: Annotated[UserIdentity, Depends(require_user)]) -> dict[str, str | None]:
    return public_user(user)


@app.get("/v1/connectors")
def connector_catalog(
    _: Annotated[UserIdentity, Depends(require_user)],
) -> dict[str, object]:
    return {
        "connectors": public_catalog(),
        "activation": ["authorize", "verify", "ready"],
    }


@app.post("/auth/google/callback", include_in_schema=False)
async def google_callback(
    request: Request,
    auth_store: Annotated[AuthSessionStore, Depends(get_auth_store)],
) -> RedirectResponse:
    """Verify Google's double-submit CSRF token, then mint a one-use login code."""

    form = await bounded_google_form(request)
    csrf_body = form.get("g_csrf_token", "")
    csrf_cookie = request.cookies.get("g_csrf_token", "")
    if not csrf_body or not csrf_cookie or not hmac.compare_digest(csrf_body, csrf_cookie):
        raise HTTPException(status_code=400, detail="invalid sign-in response")
    credential = form.get("credential", "")
    identity = verify_google_id_token(credential)
    try:
        code = await auth_store.issue_code(identity)
    except AuthSessionError as exc:
        raise HTTPException(
            status_code=503, detail="browser authentication is unavailable"
        ) from exc
    fragment = urlencode({"rally-login-code": code})
    return RedirectResponse(f"{admin_return_url()}#{fragment}", status_code=303)


@app.post("/v1/auth/exchange")
async def exchange_login_code(
    body: LoginCodeInput,
    auth_store: Annotated[AuthSessionStore, Depends(get_auth_store)],
) -> dict[str, object]:
    """Atomically consume a redirect code and return an in-memory browser session."""

    try:
        exchanged = await auth_store.exchange_code(body.code.get_secret_value())
    except AuthSessionError as exc:
        raise HTTPException(
            status_code=503, detail="browser authentication is unavailable"
        ) from exc
    if exchanged is None:
        raise _unauthorized("login code is invalid or expired")
    session_token, user = exchanged
    return {
        "session_token": session_token,
        "expires_in": 1800,
        "account": public_user(user),
    }


@app.post("/v1/connections/{connector_id}/oauth/start")
async def start_connector_oauth(
    connector_id: str,
    body: OAuthStartInput,
    user: Annotated[UserIdentity, Depends(require_user)],
    broker: Annotated[ConnectorOAuthBroker, Depends(get_oauth_broker)],
) -> dict[str, str]:
    connector_id = validated_connector(connector_id)
    item = hosted_connector(connector_id)
    try:
        authorization_url = await broker.start(
            item,
            user,
            body.endpoint,
            body.workflow_ids,
        )
    except HostedOAuthError as exc:
        if exc.code in {
            "endpoint_required",
            "endpoint_invalid",
            "endpoint_not_allowed",
            "policy_configuration_required",
            "policy_scope_invalid",
        }:
            raise HTTPException(status_code=422, detail=exc.code) from exc
        if exc.code == "oauth_not_available":
            raise HTTPException(status_code=409, detail="OAuth is not available") from exc
        raise HTTPException(
            status_code=503, detail="provider authorization is unavailable"
        ) from exc
    return {
        "connector_id": connector_id,
        "authorization_url": authorization_url,
        "return_to": admin_return_url(),
    }


@app.post("/auth/connector/callback", include_in_schema=False)
async def connector_callback(
    body: OAuthCallbackInput,
    broker: Annotated[ConnectorOAuthBroker, Depends(get_oauth_broker)],
    vault: Annotated[ConnectorVault, Depends(get_vault)],
    auth_store: Annotated[AuthSessionStore, Depends(get_auth_store)],
    verifier: Annotated[McpConnectionVerifier, Depends(get_connection_verifier)],
) -> RedirectResponse:
    """Consume OAuth state, verify live MCP capabilities, and restore login."""

    try:
        flow = await broker.consume(body.state.get_secret_value())
    except HostedOAuthError as exc:
        raise HTTPException(status_code=503, detail="connector OAuth is unavailable") from exc
    if flow is None:
        return RedirectResponse(
            connector_return_url(status="invalid-or-expired"),
            status_code=303,
        )

    status = "cancelled"
    if not body.error and body.code is not None:
        item = hosted_connector(flow.connector_id)
        try:
            completion = await broker.exchange(flow, body.code.get_secret_value())
            await vault.put(
                flow.identity.uid,
                flow.connector_id,
                ConnectorSecret(completion.stored_material, "oauth_refresh_token"),
            )
            await vault.mark(
                flow.identity.uid,
                flow.connector_id,
                status="verifying",
            )
            try:
                tool_count = await verifier.verify(
                    item,
                    completion.access_material,
                    allowed_workflow_ids=flow.allowed_workflow_ids,
                )
            except HostedConnectorError as exc:
                await vault.mark(
                    flow.identity.uid,
                    flow.connector_id,
                    status="needs_attention",
                    error_code=exc.code,
                )
                status = "needs-attention"
            else:
                await vault.mark(
                    flow.identity.uid,
                    flow.connector_id,
                    status="ready",
                    tool_count=tool_count,
                )
                status = "ready"
        except (HostedOAuthError, CredentialVaultError):
            status = "needs-attention"
    elif not body.error:
        status = "needs-attention"

    try:
        login_code = await auth_store.issue_code(flow.identity)
    except AuthSessionError as exc:
        raise HTTPException(
            status_code=503, detail="browser authentication is unavailable"
        ) from exc
    return RedirectResponse(
        connector_return_url(
            login_code=login_code,
            connector_id=flow.connector_id,
            status=status,
        ),
        status_code=303,
    )


@app.get("/v1/connections")
async def list_connections(
    user: Annotated[UserIdentity, Depends(require_user)],
    vault: Annotated[ConnectorVault, Depends(get_vault)],
) -> dict[str, list[dict[str, object]]]:
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
    verifier: Annotated[McpConnectionVerifier, Depends(get_connection_verifier)],
) -> dict[str, object]:
    connector_id = validated_connector(connector_id)
    item = hosted_connector(connector_id)
    if not item.token_ready:
        raise HTTPException(status_code=409, detail="this connector requires OAuth")
    try:
        endpoint = resolve_endpoint(item, body.endpoint)
        workflow_ids = normalize_workflow_ids(item, body.workflow_ids)
        material = pack_secret(
            credential=body.credential.get_secret_value(),
            endpoint=endpoint,
            scheme=body.scheme,
            account=body.account,
            allowed_workflow_ids=workflow_ids,
        )
        record = await vault.put(
            user.uid,
            connector_id,
            ConnectorSecret(material, body.kind),
        )
        await vault.mark(user.uid, connector_id, status="verifying")
        try:
            tool_count = await verifier.verify(
                item,
                {
                    "credential": body.credential.get_secret_value(),
                    "endpoint": endpoint,
                    "scheme": body.scheme,
                    "account": body.account,
                },
                allowed_workflow_ids=workflow_ids,
            )
        except HostedConnectorError as exc:
            record = await vault.mark(
                user.uid,
                connector_id,
                status="needs_attention",
                error_code=exc.code,
            )
        else:
            record = await vault.mark(
                user.uid,
                connector_id,
                status="ready",
                tool_count=tool_count,
            )
    except HostedConnectorError as exc:
        raise HTTPException(status_code=422, detail=exc.code) from exc
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
