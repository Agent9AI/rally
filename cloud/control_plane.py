"""Public, end-user-authenticated control plane for Rally connections."""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
from typing import Annotated, Any, Literal
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, model_validator
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
    OAuthCompletion,
    make_oauth_flow_store,
    oauth_verification_material,
)
from credential_vault import (
    ConnectionRecord,
    ConnectorSecret,
    ConnectorVault,
    CredentialVaultBusy,
    CredentialVaultConflict,
    CredentialVaultError,
    certified_manifest_sha256,
    make_connector_vault,
)
from hosted_connector_execution import (
    ExecutionReceiptStore,
    ExecutionReceiptStoreError,
    HostedConnectorExecutor,
    HostedExecutionError,
    HostedMcpCaller,
    make_execution_receipt_store,
)
from hosted_connectors import (
    HostedConnectorError,
    McpConnectionVerifier,
    normalize_workflow_ids,
    pack_secret,
    public_catalog,
    resolve_token_endpoint,
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
_execution_receipt_store: ExecutionReceiptStore | None = None
_hosted_tool_caller: HostedMcpCaller | None = None
_MAX_BROWSER_FORM_BYTES = 32 * 1024
_MAX_CALLBACK_BODY_BYTES = 16 * 1024
_MAX_INVOCATION_BODY_BYTES = 72 * 1024


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


def get_execution_receipt_store() -> ExecutionReceiptStore:
    global _execution_receipt_store
    if _execution_receipt_store is None:
        try:
            _execution_receipt_store = make_execution_receipt_store()
        except ExecutionReceiptStoreError as exc:
            raise HTTPException(status_code=503, detail="execution audit is unavailable") from exc
    return _execution_receipt_store


def get_hosted_tool_caller() -> HostedMcpCaller:
    global _hosted_tool_caller
    if _hosted_tool_caller is None:
        _hosted_tool_caller = HostedMcpCaller()
    return _hosted_tool_caller


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
    model_config = ConfigDict(extra="forbid")

    credential: SecretStr = Field(min_length=1, max_length=65536)
    kind: Literal["api_key", "bearer_token", "oauth_refresh_token"]
    endpoint: str | None = Field(default=None, max_length=2048)
    scheme: Literal["bearer", "basic"] = "bearer"
    account: str | None = Field(default=None, max_length=320)
    workflow_ids: list[str] = Field(default_factory=list, max_length=64)


class OAuthStartInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: str | None = Field(default=None, max_length=2048)
    workflow_ids: list[str] = Field(default_factory=list, max_length=64)


class OAuthCallbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: SecretStr = Field(min_length=32, max_length=128)
    code: SecretStr | None = Field(default=None, min_length=1, max_length=8192)
    error: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$"
    )
    issuer: str | None = Field(default=None, min_length=8, max_length=2048)

    @model_validator(mode="after")
    def exactly_one_result(self) -> OAuthCallbackInput:
        if (self.code is None) == (self.error is None):
            raise ValueError("authorization response requires exactly one result")
        return self


class LoginCodeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: SecretStr = Field(min_length=32, max_length=128)


class HostedToolCallInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:/-]+$")
    arguments: dict[str, Any] = Field(default_factory=dict)


def public_user(user: UserIdentity) -> dict[str, str | None]:
    configured_workspace = os.getenv("RALLY_WORKSPACE_ID", "").strip()
    if configured_workspace and not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._:-]{0,95}", configured_workspace
    ):
        raise HTTPException(status_code=503, detail="workspace identity is not configured")
    return {
        "uid": user.uid,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "hosted_domain": user.hosted_domain,
        # The initial release is one explicitly configured workspace. Keeping
        # this identifier separate from the Google subject lets the same
        # company authorize multiple administrators without merging vaults.
        # The subject-scoped fallback is safe for local tests and fails closed
        # against production projections when the deployment variable is absent.
        "workspace_id": configured_workspace or f"user:{user.uid}",
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


async def bounded_browser_form(request: Request) -> dict[str, str]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/x-www-form-urlencoded":
        raise HTTPException(status_code=415, detail="unsupported sign-in response")
    declared = request.headers.get("content-length")
    if declared:
        try:
            if int(declared) > _MAX_BROWSER_FORM_BYTES:
                raise HTTPException(status_code=413, detail="sign-in response is too large")
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid sign-in response") from None
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > _MAX_BROWSER_FORM_BYTES:
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


async def bounded_invocation_json(request: Request) -> HostedToolCallInput:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise HTTPException(status_code=415, detail="unsupported invocation request")
    declared = request.headers.get("content-length")
    if declared:
        try:
            declared_bytes = int(declared)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid invocation request") from None
        if declared_bytes < 0:
            raise HTTPException(status_code=400, detail="invalid invocation request")
        if declared_bytes > _MAX_INVOCATION_BODY_BYTES:
            raise HTTPException(status_code=413, detail="invocation request is too large")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > _MAX_INVOCATION_BODY_BYTES:
            raise HTTPException(status_code=413, detail="invocation request is too large")
    try:
        payload = json.loads(body)
        return HostedToolCallInput.model_validate(payload)
    except (UnicodeDecodeError, ValueError, ValidationError):
        raise HTTPException(status_code=422, detail="invalid invocation request") from None


async def bounded_callback_json(request: Request) -> OAuthCallbackInput:
    """Parse a public OAuth callback without letting the framework buffer it unbounded."""

    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise HTTPException(status_code=415, detail="unsupported authorization response")
    declared = request.headers.get("content-length")
    if declared:
        try:
            declared_bytes = int(declared)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid authorization response") from None
        if declared_bytes < 0:
            raise HTTPException(status_code=400, detail="invalid authorization response")
        if declared_bytes > _MAX_CALLBACK_BODY_BYTES:
            raise HTTPException(status_code=413, detail="authorization response is too large")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > _MAX_CALLBACK_BODY_BYTES:
            raise HTTPException(status_code=413, detail="authorization response is too large")
    try:
        payload = json.loads(body)
        return OAuthCallbackInput.model_validate(payload)
    except (UnicodeDecodeError, ValueError, ValidationError):
        raise HTTPException(status_code=400, detail="invalid authorization response") from None


def public_connection(record: ConnectionRecord) -> dict[str, object]:
    certified = (
        record.status == "ready"
        and record.proof_version == "rally.connection-certification/v1"
        and bool(record.canary_tool)
        and bool(record.tool_schema_sha256)
        and bool(record.credential_generation)
        and record.tool_count == len(record.certified_tools)
        and record.certified_manifest_sha256 == certified_manifest_sha256(record.certified_tools)
        and dict(record.certified_tools).get(record.canary_tool) == record.tool_schema_sha256
    )
    effective_status = record.status if certified or record.status != "ready" else "needs_attention"
    return {
        "connector_id": record.connector_id,
        "credential_kind": record.credential_kind,
        "status": effective_status,
        "verified": certified,
        "tool_count": record.tool_count,
        "verified_at": record.verified_at,
        "error_code": (
            record.error_code if effective_status == record.status else "recertification_required"
        ),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "certification": (
            {
                "schema": record.proof_version,
                "live_read": True,
                "canary_tool": record.canary_tool,
                "tool_schema_sha256": record.tool_schema_sha256,
                "tool_manifest_sha256": record.certified_manifest_sha256,
                "certified_at": record.verified_at,
            }
            if certified
            else None
        ),
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

    form = await bounded_browser_form(request)
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


@app.post("/v1/auth/logout")
async def logout_browser_session(
    auth_store: Annotated[AuthSessionStore, Depends(get_auth_store)],
    session_token: str | None = Header(default=None, alias="X-Rally-Session"),
) -> dict[str, bool]:
    """Revoke a page-memory session without revealing whether it was current."""

    if not session_token:
        raise _unauthorized()
    try:
        await auth_store.revoke_session(session_token)
    except AuthSessionError as exc:
        raise HTTPException(
            status_code=503, detail="browser authentication is unavailable"
        ) from exc
    return {"signed_out": True}


@app.post("/v1/connections/{connector_id}/oauth/start")
async def start_connector_oauth(
    connector_id: str,
    body: OAuthStartInput,
    user: Annotated[UserIdentity, Depends(require_user)],
    broker: Annotated[ConnectorOAuthBroker, Depends(get_oauth_broker)],
    vault: Annotated[ConnectorVault, Depends(get_vault)],
) -> dict[str, str]:
    connector_id = validated_connector(connector_id)
    item = hosted_connector(connector_id)
    try:
        if await vault.get_secret(user.uid, connector_id) is not None:
            raise HTTPException(
                status_code=409,
                detail="disconnect_existing_connection",
            )
        authorization = await broker.start(
            item,
            user,
            body.endpoint,
            body.workflow_ids,
        )
    except CredentialVaultError as exc:
        raise HTTPException(status_code=503, detail="could not read connection") from exc
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
        if exc.code == "oauth_in_progress":
            raise HTTPException(status_code=409, detail="oauth_in_progress") from exc
        raise HTTPException(
            status_code=503, detail="provider authorization is unavailable"
        ) from exc
    return {
        "connector_id": connector_id,
        "authorization_url": authorization.authorization_url,
        "browser_binding": authorization.browser_binding,
        "return_to": admin_return_url(),
    }


@app.delete("/v1/connections/{connector_id}/oauth/pending")
async def cancel_pending_connector_oauth(
    connector_id: str,
    user: Annotated[UserIdentity, Depends(require_user)],
    broker: Annotated[ConnectorOAuthBroker, Depends(get_oauth_broker)],
) -> dict[str, object]:
    """Cancel one tenant-bound, unconsumed OAuth flow without touching a grant."""

    connector_id = validated_connector(connector_id)
    item = hosted_connector(connector_id)
    if not item.oauth_ready:
        raise HTTPException(status_code=409, detail="OAuth is not available")
    try:
        cancelled = await broker.cancel_pending(user, connector_id)
    except HostedOAuthError as exc:
        raise HTTPException(
            status_code=503,
            detail="pending authorization is unavailable",
        ) from exc
    return {
        "connector_id": connector_id,
        "cancelled": cancelled,
    }


async def _complete_connector_callback(
    body: OAuthCallbackInput,
    broker: ConnectorOAuthBroker,
    vault: ConnectorVault,
    auth_store: AuthSessionStore,
    browser_binding: str | None,
) -> RedirectResponse:
    """Consume one OAuth return after either JSON or browser-form transport."""
    try:
        flow = await broker.consume(
            body.state.get_secret_value(),
            browser_binding or "",
            body.issuer,
        )
    except HostedOAuthError as exc:
        raise HTTPException(status_code=503, detail="connector OAuth is unavailable") from exc
    if flow is None:
        return RedirectResponse(
            connector_return_url(status="invalid-or-expired"),
            status_code=303,
        )

    status = "cancelled" if body.error == "access_denied" else "needs-attention"
    if body.error is None and body.code is not None:
        completion = None
        persisted = False
        try:
            if await vault.get_secret(flow.identity.uid, flow.connector_id) is not None:
                status = "disconnect-first"
            else:
                completion = await broker.exchange(flow, body.code.get_secret_value())
                await vault.put(
                    flow.identity.uid,
                    flow.connector_id,
                    ConnectorSecret(completion.stored_material, "oauth_refresh_token"),
                )
                persisted = True
                status = "verifying"
        except CredentialVaultConflict:
            if completion is None:
                status = "disconnect-first"
            else:
                revoked = await _revoke_callback_completion(
                    broker,
                    flow.connector_id,
                    completion,
                )
                status = "disconnect-first" if revoked else "provider-cleanup-required"
        except HostedOAuthError as exc:
            status = (
                "provider-cleanup-required"
                if exc.code == "oauth_provider_cleanup_required"
                else "needs-attention"
            )
        except CredentialVaultError:
            if completion is None:
                status = "needs-attention"
            elif persisted:
                # Rally retains the sealed grant so the administrator can retry
                # verification or revoke it through the normal disconnect path.
                status = "needs-attention"
            else:
                revoked = await _revoke_callback_completion(
                    broker,
                    flow.connector_id,
                    completion,
                )
                status = "needs-attention" if revoked else "provider-cleanup-required"

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


async def _revoke_callback_completion(
    broker: ConnectorOAuthBroker,
    connector_id: str,
    completion: OAuthCompletion,
) -> bool:
    """Best-effort cleanup for a provider grant Rally could not safely persist."""

    try:
        return await broker.revoke(
            hosted_connector(connector_id),
            completion.stored_material,
        )
    except HostedOAuthError:
        return False


@app.post("/auth/connector/callback", include_in_schema=False)
async def connector_callback(
    request: Request,
    broker: Annotated[ConnectorOAuthBroker, Depends(get_oauth_broker)],
    vault: Annotated[ConnectorVault, Depends(get_vault)],
    auth_store: Annotated[AuthSessionStore, Depends(get_auth_store)],
    browser_binding: str | None = Header(default=None, alias="X-Rally-OAuth-Binding"),
) -> RedirectResponse:
    """Accept the API callback used by controlled clients and tests."""

    body = await bounded_callback_json(request)
    return await _complete_connector_callback(
        body,
        broker,
        vault,
        auth_store,
        browser_binding,
    )


@app.post("/auth/connector/callback/form", include_in_schema=False)
async def connector_callback_form(
    request: Request,
    broker: Annotated[ConnectorOAuthBroker, Depends(get_oauth_broker)],
    vault: Annotated[ConnectorVault, Depends(get_vault)],
    auth_store: Annotated[AuthSessionStore, Depends(get_auth_store)],
    browser_binding: str | None = Header(default=None, alias="X-Rally-OAuth-Binding"),
) -> RedirectResponse:
    """Finish a bounded browser relay; access and refresh tokens remain server-side."""

    form = await bounded_browser_form(request)
    try:
        body = OAuthCallbackInput.model_validate(form)
    except ValidationError:
        raise HTTPException(status_code=400, detail="invalid authorization response") from None
    return await _complete_connector_callback(
        body,
        broker,
        vault,
        auth_store,
        browser_binding,
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


@app.post("/v1/connections/{connector_id}/verify")
async def verify_connector(
    connector_id: str,
    user: Annotated[UserIdentity, Depends(require_user)],
    vault: Annotated[ConnectorVault, Depends(get_vault)],
    verifier: Annotated[McpConnectionVerifier, Depends(get_connection_verifier)],
) -> dict[str, object]:
    """Certify a sealed OAuth grant after the browser has returned to its card."""

    connector_id = validated_connector(connector_id)
    try:
        stored = await vault.get_connection(user.uid, connector_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="connection not found")
        record = stored.record
        if record.status == "ready":
            return public_connection(record)
        if record.error_code == "disconnect_pending":
            raise HTTPException(status_code=409, detail="disconnect_pending")
        secret = stored.secret
        if secret.kind != "oauth_refresh_token":
            raise HTTPException(status_code=409, detail="oauth_verification_required")
        item = hosted_connector(connector_id)
        try:
            material, workflow_ids = oauth_verification_material(item, secret.value)
        except HostedOAuthError as exc:
            failed = await vault.begin_verification(
                user.uid,
                connector_id,
                expected_generation=record.credential_generation,
            )
            if failed is None:
                raise HTTPException(status_code=409, detail="connection_changed")
            finished = await vault.finish_verification(
                user.uid,
                connector_id,
                expected_generation=record.credential_generation,
                expected_lease=failed.execution_lease or "",
                status="needs_attention",
                error_code=exc.code,
            )
            if finished is None:
                raise HTTPException(status_code=409, detail="connection_changed")
            return public_connection(finished)
        begun = await vault.begin_verification(
            user.uid,
            connector_id,
            expected_generation=record.credential_generation,
        )
        if begun is None:
            latest = await vault.get_connection(user.uid, connector_id)
            if latest is not None and latest.record.error_code == "disconnect_pending":
                raise HTTPException(status_code=409, detail="disconnect_pending")
            if latest is not None and latest.record.status == "verifying":
                raise HTTPException(status_code=409, detail="verification_in_progress")
            raise HTTPException(status_code=409, detail="connection_changed")
        verification_lease = begun.execution_lease or ""
        try:
            async with asyncio.timeout(45):
                certification = await verifier.verify(
                    item,
                    material,
                    allowed_workflow_ids=workflow_ids,
                )
        except TimeoutError:
            record = await vault.finish_verification(
                user.uid,
                connector_id,
                expected_generation=record.credential_generation,
                expected_lease=verification_lease,
                status="needs_attention",
                error_code="verification_timeout",
            )
        except HostedConnectorError as exc:
            record = await vault.finish_verification(
                user.uid,
                connector_id,
                expected_generation=record.credential_generation,
                expected_lease=verification_lease,
                status="needs_attention",
                error_code=exc.code,
            )
        else:
            record = await vault.finish_verification(
                user.uid,
                connector_id,
                expected_generation=record.credential_generation,
                expected_lease=verification_lease,
                status="ready",
                tool_count=certification.tool_count,
                canary_tool=certification.canary_tool,
                tool_schema_sha256=certification.tool_schema_sha256,
                proof_version=certification.proof_version,
                certified_tools=certification.certified_tools,
                certified_manifest_sha256=certification.certified_manifest_sha256,
            )
        if record is None:
            latest = await vault.get_connection(user.uid, connector_id)
            if latest is not None and latest.record.error_code == "disconnect_pending":
                raise HTTPException(status_code=409, detail="disconnect_pending")
            raise HTTPException(status_code=409, detail="connection_changed")
    except CredentialVaultError as exc:
        raise HTTPException(status_code=503, detail="could not verify connection") from exc
    return public_connection(record)


@app.post("/v1/connections/{connector_id}/invoke")
async def invoke_connector_tool(
    connector_id: str,
    request: Request,
    user: Annotated[UserIdentity, Depends(require_user)],
    vault: Annotated[ConnectorVault, Depends(get_vault)],
    receipt_store: Annotated[ExecutionReceiptStore, Depends(get_execution_receipt_store)],
    caller: Annotated[HostedMcpCaller, Depends(get_hosted_tool_caller)],
) -> dict[str, object]:
    """Invoke one certified, preset-allowlisted read tool for the signed-in tenant."""

    connector_id = validated_connector(connector_id)
    body = await bounded_invocation_json(request)
    executor = HostedConnectorExecutor(vault, receipt_store, caller)
    try:
        result = await executor.execute(
            uid=user.uid,
            connector_id=connector_id,
            tool_name=body.tool_name,
            arguments=body.arguments,
        )
    except HostedExecutionError as exc:
        if exc.code == "connection_not_found":
            status_code = 404
        elif exc.code in {
            "connection_busy",
            "connection_not_ready",
            "credential_expired",
            "reconnect_required",
            "tool_schema_changed",
        }:
            status_code = 409
        elif exc.code in {
            "argument_invalid",
            "argument_not_allowed",
            "argument_required",
            "arguments_invalid",
            "arguments_too_large",
            "human_approval_required",
            "policy_configuration_required",
            "safe_preset_unavailable",
            "tool_invalid",
            "tool_not_allowed",
            "tool_not_certified",
        }:
            status_code = 422
        elif exc.code in {"receipt_unavailable", "vault_unavailable"}:
            status_code = 503
        elif exc.code == "execution_timeout":
            status_code = 504
        else:
            status_code = 502
        detail: dict[str, object] = {"code": exc.code}
        if exc.receipt is not None:
            detail["receipt"] = exc.receipt.public()
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return {
        "connector_id": connector_id,
        "tool_name": body.tool_name,
        "result": result.payload,
        "receipt": result.receipt.public(),
    }


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
        if await vault.get_secret(user.uid, connector_id) is not None:
            raise HTTPException(
                status_code=409,
                detail="disconnect_existing_connection",
            )
        if body.scheme != item.token_scheme:
            raise HostedConnectorError("credential_scheme_not_allowed")
        endpoint = resolve_token_endpoint(item, body.endpoint)
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
        generation = record.credential_generation
        begun = await vault.begin_verification(
            user.uid,
            connector_id,
            expected_generation=generation,
        )
        if begun is None:
            raise HTTPException(status_code=409, detail="connection_changed")
        verification_lease = begun.execution_lease or ""
        try:
            certification = await verifier.verify(
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
            record = await vault.finish_verification(
                user.uid,
                connector_id,
                expected_generation=generation,
                expected_lease=verification_lease,
                status="needs_attention",
                error_code=exc.code,
            )
        else:
            record = await vault.finish_verification(
                user.uid,
                connector_id,
                expected_generation=generation,
                expected_lease=verification_lease,
                status="ready",
                tool_count=certification.tool_count,
                canary_tool=certification.canary_tool,
                tool_schema_sha256=certification.tool_schema_sha256,
                proof_version=certification.proof_version,
                certified_tools=certification.certified_tools,
                certified_manifest_sha256=certification.certified_manifest_sha256,
            )
        if record is None:
            raise HTTPException(status_code=409, detail="connection_changed")
    except HTTPException:
        raise
    except HostedConnectorError as exc:
        raise HTTPException(status_code=422, detail=exc.code) from exc
    except CredentialVaultConflict as exc:
        raise HTTPException(status_code=409, detail="disconnect_existing_connection") from exc
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
        disconnecting = await vault.begin_disconnect(user.uid, connector_id)
        stored = disconnecting.secret if disconnecting is not None else None
        provider_revoked = False
        if stored and stored.kind == "oauth_refresh_token":
            try:
                provider_revoked = await get_oauth_broker().revoke(
                    hosted_connector(connector_id),
                    stored.value,
                )
            except HostedOAuthError as exc:
                raise HTTPException(
                    status_code=502,
                    detail="provider revocation did not complete; the connection remains sealed",
                ) from exc
        deleted = (
            await vault.delete(
                user.uid,
                connector_id,
                expected_generation=disconnecting.record.credential_generation,
                require_disconnect=True,
            )
            if disconnecting is not None
            else False
        )
        if disconnecting is not None and not deleted:
            raise HTTPException(status_code=409, detail="connection_changed")
    except CredentialVaultBusy as exc:
        raise HTTPException(status_code=409, detail="connection_busy") from exc
    except CredentialVaultError as exc:
        raise HTTPException(status_code=503, detail="could not disconnect provider") from exc
    return {
        "connector_id": connector_id,
        "disconnected": deleted,
        "provider_revoked": provider_revoked,
        "provider_action_required": deleted and not provider_revoked,
    }
