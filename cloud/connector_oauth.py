"""Durable OAuth 2.1 handshakes for Rally's hosted MCP connectors.

The browser never stores provider tokens.  Rally persists only a hash of the
one-time state value plus a KMS-encrypted flow record, then consumes that state
atomically at the callback.  Discovery is constrained to each connector's
explicit provider hosts before Rally makes any outbound request.
"""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import hashlib
import json
import os
import re
import secrets
from dataclasses import asdict, dataclass
from typing import Any, Final, Literal, Protocol
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

import httpx
from mcp.client.auth import PKCEParameters
from mcp.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
    build_protected_resource_metadata_discovery_urls,
    extract_resource_metadata_from_www_auth,
    extract_scope_from_www_auth,
    get_client_metadata_scopes,
)
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
    OAuthToken,
    ProtectedResourceMetadata,
)
from mcp.shared.auth_utils import check_resource_allowed, resource_url_from_server_url
from pydantic import ValidationError

from credential_vault import KmsEnvelopeCipher
from hosted_connectors import (
    HostedConnector,
    HostedConnectorError,
    make_oauth_material,
    normalize_workflow_ids,
    resolve_endpoint,
    validate_oauth_url,
)
from user_auth import UserIdentity


class HostedOAuthError(RuntimeError):
    """A provider handshake failed without exposing provider response content."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


TokenAuthMethod = Literal["none", "client_secret_basic", "client_secret_post"]


@dataclass(frozen=True, repr=False)
class OAuthFlow:
    identity: UserIdentity
    connector_id: str
    endpoint: str
    authorization_endpoint: str
    token_endpoint: str
    revocation_endpoint: str | None
    client_id: str
    client_secret: str | None
    token_auth_method: TokenAuthMethod
    code_verifier: str
    scope: str | None
    resource: str | None
    allowed_workflow_ids: tuple[str, ...]
    expires_at: dt.datetime


@dataclass(frozen=True, repr=False)
class OAuthCompletion:
    stored_material: str
    access_material: dict[str, str | None]


class OAuthFlowStore(Protocol):
    async def put(self, state: str, flow: OAuthFlow) -> None: ...

    async def consume(self, state: str) -> OAuthFlow | None: ...


_STATE: Final = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_FLOW_TTL_SECONDS: Final = 10 * 60
_FLOW_SCHEMA: Final = "rally.connector-oauth-flow/v1"
_MAX_METADATA_BYTES: Final = 64 * 1024
_MAX_CHALLENGE_BYTES: Final = 4 * 1024
_MAX_AUTH_URL_BYTES: Final = 12 * 1024
_CALLBACK_URL: Final = "https://rally.agent9.dev/admin/connect/callback"
_CLIENT_METADATA_URL: Final = "https://rally.agent9.dev/oauth/client-metadata.json"


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _state_hash(state: str) -> str | None:
    if not isinstance(state, str) or not _STATE.fullmatch(state):
        return None
    return hashlib.sha256(state.encode("ascii")).hexdigest()


def _flow_associated_data(state_hash: str) -> bytes:
    return f"{_FLOW_SCHEMA}\0{state_hash}".encode("ascii")


def _flow_payload(flow: OAuthFlow) -> bytes:
    record = {
        **asdict(flow),
        "identity": asdict(flow.identity),
        "expires_at": flow.expires_at.isoformat(),
    }
    return json.dumps(record, separators=(",", ":")).encode("utf-8")


def _flow_from_payload(payload: bytes) -> OAuthFlow | None:
    try:
        record = json.loads(payload)
        identity_record = record.pop("identity")
        expires_at = dt.datetime.fromisoformat(record.pop("expires_at"))
        workflow_ids = tuple(record.pop("allowed_workflow_ids", ()))
        if expires_at.tzinfo is None:
            return None
        identity = UserIdentity(**identity_record)
        flow = OAuthFlow(
            identity=identity,
            expires_at=expires_at,
            allowed_workflow_ids=workflow_ids,
            **record,
        )
    except (KeyError, TypeError, ValueError, UnicodeDecodeError):
        return None
    if flow.token_auth_method not in {"none", "client_secret_basic", "client_secret_post"}:
        return None
    return flow


class MemoryOAuthFlowStore:
    """Development store that retains only state hashes, never raw state values."""

    def __init__(self, *, clock: Any = _utc_now) -> None:
        self._clock = clock
        self._flows: dict[str, OAuthFlow] = {}
        self._lock = asyncio.Lock()

    async def put(self, state: str, flow: OAuthFlow) -> None:
        state_hash = _state_hash(state)
        if state_hash is None:
            raise HostedOAuthError("oauth_state_invalid")
        async with self._lock:
            self._flows[state_hash] = flow

    async def consume(self, state: str) -> OAuthFlow | None:
        state_hash = _state_hash(state)
        if state_hash is None:
            return None
        async with self._lock:
            flow = self._flows.pop(state_hash, None)
        if flow is None or flow.expires_at <= self._clock():
            return None
        return flow


class FirestoreOAuthFlowStore:
    """KMS-encrypted, one-use OAuth flow state stored in Firestore."""

    def __init__(
        self,
        project_id: str,
        key_name: str,
        firestore_client: Any | None = None,
        kms_client: Any | None = None,
    ) -> None:
        if not project_id:
            raise HostedOAuthError("oauth_store_unavailable")
        if firestore_client is None:
            from google.cloud import firestore

            firestore_client = firestore.AsyncClient(project=project_id)
        self.client = firestore_client
        self.collection = self.client.collection("rally_connector_oauth_flows")
        self.cipher = KmsEnvelopeCipher(
            key_name,
            client=kms_client,
            envelope_schema=_FLOW_SCHEMA,
        )

    async def put(self, state: str, flow: OAuthFlow) -> None:
        state_hash = _state_hash(state)
        if state_hash is None:
            raise HostedOAuthError("oauth_state_invalid")
        try:
            envelope = await asyncio.to_thread(
                self.cipher.seal,
                _flow_payload(flow),
                _flow_associated_data(state_hash),
            )
            await self.collection.document(state_hash).create(
                {
                    **envelope,
                    "created_at": _utc_now(),
                    "expires_at": flow.expires_at,
                }
            )
        except Exception as exc:
            raise HostedOAuthError("oauth_store_unavailable") from exc

    async def consume(self, state: str) -> OAuthFlow | None:
        from google.cloud import firestore

        state_hash = _state_hash(state)
        if state_hash is None:
            return None
        document = self.collection.document(state_hash)

        @firestore.async_transactional
        async def take(transaction: Any) -> dict[str, Any] | None:
            snapshot = await document.get(transaction=transaction)
            if not snapshot.exists:
                return None
            record = snapshot.to_dict() or {}
            transaction.delete(document)
            return record

        try:
            record = await take(self.client.transaction())
            if record is None:
                return None
            expires_at = record.get("expires_at")
            if not isinstance(expires_at, dt.datetime) or expires_at <= _utc_now():
                return None
            payload = await asyncio.to_thread(
                self.cipher.open,
                record,
                _flow_associated_data(state_hash),
            )
            return _flow_from_payload(payload)
        except Exception as exc:
            raise HostedOAuthError("oauth_store_unavailable") from exc


def make_oauth_flow_store() -> OAuthFlowStore:
    backend = os.getenv("RALLY_OAUTH_BACKEND", os.getenv("RALLY_AUTH_BACKEND", ""))
    if backend == "firestore":
        return FirestoreOAuthFlowStore(
            project_id=os.getenv("GOOGLE_CLOUD_PROJECT", ""),
            key_name=os.getenv("RALLY_KMS_KEY", ""),
        )
    if backend == "memory" and os.getenv("RALLY_ALLOW_INSECURE_DEV") == "1":
        return MemoryOAuthFlowStore()
    raise HostedOAuthError("oauth_store_unavailable")


def _bounded_text(value: str | None, maximum: int, code: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > maximum:
        raise HostedOAuthError(code)
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise HostedOAuthError(code)
    return value


def _auth_base(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def _metadata_json(
    response: httpx.Response,
    model: type[Any],
    error: str,
    *,
    accepted_statuses: frozenset[int] = frozenset({200}),
) -> Any:
    content = response.content
    if response.status_code not in accepted_statuses or len(content) > _MAX_METADATA_BYTES:
        raise HostedOAuthError(error)
    try:
        return model.model_validate_json(content)
    except ValidationError:
        raise HostedOAuthError(error) from None


async def _bounded_response(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    maximum: int,
    error: str,
    **kwargs: Any,
) -> httpx.Response:
    """Read a provider response without allowing an unbounded body allocation."""

    async with client.stream(method, url, **kwargs) as response:
        declared = response.headers.get("content-length")
        if declared:
            try:
                if int(declared) > maximum:
                    raise HostedOAuthError(error)
            except ValueError:
                raise HostedOAuthError(error) from None
        content = bytearray()
        async for chunk in response.aiter_bytes():
            content.extend(chunk)
            if len(content) > maximum:
                raise HostedOAuthError(error)
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            content=bytes(content),
            request=response.request,
        )


class ConnectorOAuthBroker:
    """Discover, register, and finish one browser OAuth authorization."""

    def __init__(
        self,
        store: OAuthFlowStore,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Any = _utc_now,
    ) -> None:
        self.store = store
        self.transport = transport
        self.clock = clock

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, read=15.0),
            follow_redirects=False,
            transport=self.transport,
        )

    async def start(
        self,
        item: HostedConnector,
        identity: UserIdentity,
        supplied_endpoint: str | None,
        allowed_workflow_ids: list[str] | None = None,
    ) -> str:
        if not item.oauth_ready:
            raise HostedOAuthError("oauth_not_available")
        try:
            endpoint = resolve_endpoint(item, supplied_endpoint)
        except HostedConnectorError as exc:
            raise HostedOAuthError(exc.code) from exc
        try:
            workflow_scope = normalize_workflow_ids(item, allowed_workflow_ids)
        except HostedConnectorError as exc:
            raise HostedOAuthError(exc.code) from exc

        initialize = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "Rally", "version": "0.1"},
            },
        }
        try:
            async with asyncio.timeout(40), self._client() as client:
                challenge = await _bounded_response(
                    client,
                    "POST",
                    endpoint,
                    maximum=_MAX_CHALLENGE_BYTES,
                    error="oauth_discovery_failed",
                    json=initialize,
                    headers={
                        "Accept": "application/json, text/event-stream",
                        "MCP-Protocol-Version": "2025-06-18",
                    },
                )
                www_metadata = extract_resource_metadata_from_www_auth(challenge)
                protected: ProtectedResourceMetadata | None = None
                for candidate in build_protected_resource_metadata_discovery_urls(
                    www_metadata,
                    endpoint,
                ):
                    url = validate_oauth_url(item, candidate, endpoint)
                    response = await _bounded_response(
                        client,
                        "GET",
                        url,
                        maximum=_MAX_METADATA_BYTES,
                        error="oauth_discovery_failed",
                        headers={"Accept": "application/json"},
                    )
                    if response.status_code != 200:
                        continue
                    try:
                        protected = _metadata_json(
                            response,
                            ProtectedResourceMetadata,
                            "oauth_discovery_failed",
                        )
                    except HostedOAuthError:
                        continue
                    resource = str(protected.resource)
                    if not check_resource_allowed(
                        requested_resource=resource_url_from_server_url(endpoint),
                        configured_resource=resource,
                    ):
                        raise HostedOAuthError("oauth_resource_mismatch")
                    validate_oauth_url(item, resource, endpoint)
                    break

                auth_server = (
                    str(protected.authorization_servers[0])
                    if protected and protected.authorization_servers
                    else None
                )
                oauth_metadata: OAuthMetadata | None = None
                for candidate in build_oauth_authorization_server_metadata_discovery_urls(
                    auth_server,
                    endpoint,
                ):
                    url = validate_oauth_url(item, candidate, endpoint)
                    response = await _bounded_response(
                        client,
                        "GET",
                        url,
                        maximum=_MAX_METADATA_BYTES,
                        error="oauth_discovery_failed",
                        headers={"Accept": "application/json"},
                    )
                    if response.status_code != 200:
                        continue
                    try:
                        oauth_metadata = _metadata_json(
                            response,
                            OAuthMetadata,
                            "oauth_discovery_failed",
                        )
                    except HostedOAuthError:
                        continue
                    break
                if oauth_metadata is None:
                    raise HostedOAuthError("oauth_discovery_failed")

                authorization_endpoint = validate_oauth_url(
                    item,
                    str(oauth_metadata.authorization_endpoint),
                    endpoint,
                )
                token_endpoint = validate_oauth_url(
                    item,
                    str(oauth_metadata.token_endpoint),
                    endpoint,
                )
                revocation_endpoint = (
                    validate_oauth_url(
                        item,
                        str(oauth_metadata.revocation_endpoint),
                        endpoint,
                    )
                    if oauth_metadata.revocation_endpoint
                    else None
                )
                scope = get_client_metadata_scopes(
                    extract_scope_from_www_auth(challenge),
                    protected,
                    oauth_metadata,
                )
                if item.oauth_scope is not None:
                    requested = set(item.oauth_scope.split())
                    advertised = set(
                        (protected.scopes_supported if protected else None)
                        or oauth_metadata.scopes_supported
                        or ()
                    )
                    if advertised and not requested.issubset(advertised):
                        raise HostedOAuthError("oauth_scope_unavailable")
                    scope = item.oauth_scope
                if scope is not None:
                    scope = _bounded_text(scope, 2048, "oauth_scope_invalid")

                metadata = OAuthClientMetadata(
                    redirect_uris=[_CALLBACK_URL],
                    token_endpoint_auth_method="none",
                    grant_types=["authorization_code", "refresh_token"],
                    response_types=["code"],
                    scope=scope,
                    client_name="Rally",
                    client_uri="https://rally.agent9.dev/",
                    tos_uri="https://rally.agent9.dev/terms/",
                    policy_uri="https://rally.agent9.dev/privacy/",
                )
                if oauth_metadata.client_id_metadata_document_supported is True:
                    client_info = OAuthClientInformationFull(
                        client_id=_CLIENT_METADATA_URL,
                        token_endpoint_auth_method="none",
                        redirect_uris=[_CALLBACK_URL],
                    )
                else:
                    registration_endpoint = oauth_metadata.registration_endpoint
                    if not registration_endpoint:
                        raise HostedOAuthError("oauth_registration_unavailable")
                    registration_url = validate_oauth_url(
                        item,
                        str(registration_endpoint),
                        endpoint,
                    )
                    response = await _bounded_response(
                        client,
                        "POST",
                        registration_url,
                        maximum=_MAX_METADATA_BYTES,
                        error="oauth_registration_failed",
                        json=metadata.model_dump(mode="json", exclude_none=True),
                        headers={"Accept": "application/json"},
                    )
                    if response.status_code not in {200, 201}:
                        raise HostedOAuthError("oauth_registration_failed")
                    client_info = _metadata_json(
                        response,
                        OAuthClientInformationFull,
                        "oauth_registration_failed",
                        accepted_statuses=frozenset({200, 201}),
                    )
        except HostedOAuthError:
            raise
        except HostedConnectorError as exc:
            raise HostedOAuthError(exc.code) from exc
        except (TimeoutError, httpx.HTTPError, ValidationError, ValueError) as exc:
            raise HostedOAuthError("oauth_provider_unavailable") from exc

        client_id = _bounded_text(client_info.client_id, 4096, "oauth_registration_failed")
        if client_id is None:  # pragma: no cover - bounded_text rejects None
            raise HostedOAuthError("oauth_registration_failed")
        client_secret = (
            _bounded_text(client_info.client_secret, 8192, "oauth_registration_failed")
            if client_info.client_secret
            else None
        )
        auth_method = client_info.token_endpoint_auth_method or "none"
        if auth_method not in {"none", "client_secret_basic", "client_secret_post"}:
            raise HostedOAuthError("oauth_auth_method_unsupported")
        if auth_method != "none" and not client_secret:
            raise HostedOAuthError("oauth_registration_failed")

        pkce = PKCEParameters.generate()
        state = secrets.token_urlsafe(32)
        resource = str(protected.resource) if protected else None
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": _CALLBACK_URL,
            "state": state,
            "code_challenge": pkce.code_challenge,
            "code_challenge_method": "S256",
        }
        if resource:
            params["resource"] = resource
        if scope:
            params["scope"] = scope
        separator = "&" if urlsplit(authorization_endpoint).query else "?"
        authorization_url = f"{authorization_endpoint}{separator}{urlencode(params)}"
        if len(authorization_url.encode("utf-8")) > _MAX_AUTH_URL_BYTES:
            raise HostedOAuthError("oauth_authorization_url_invalid")

        await self.store.put(
            state,
            OAuthFlow(
                identity=identity,
                connector_id=item.id,
                endpoint=endpoint,
                authorization_endpoint=authorization_endpoint,
                token_endpoint=token_endpoint,
                revocation_endpoint=revocation_endpoint,
                client_id=client_id,
                client_secret=client_secret,
                token_auth_method=auth_method,
                code_verifier=pkce.code_verifier,
                scope=scope,
                resource=resource,
                allowed_workflow_ids=workflow_scope,
                expires_at=self.clock() + dt.timedelta(seconds=_FLOW_TTL_SECONDS),
            ),
        )
        return authorization_url

    async def consume(self, state: str) -> OAuthFlow | None:
        return await self.store.consume(state)

    async def exchange(self, flow: OAuthFlow, code: str) -> OAuthCompletion:
        code = _bounded_text(code, 8192, "oauth_code_invalid") or ""
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _CALLBACK_URL,
            "client_id": flow.client_id,
            "code_verifier": flow.code_verifier,
        }
        if flow.resource:
            data["resource"] = flow.resource
        headers = {"Accept": "application/json"}
        if flow.token_auth_method == "client_secret_basic" and flow.client_secret:
            credentials = f"{quote(flow.client_id, safe='')}:{quote(flow.client_secret, safe='')}"
            encoded = base64.b64encode(credentials.encode()).decode("ascii")
            headers["Authorization"] = f"Basic {encoded}"
        elif flow.token_auth_method == "client_secret_post" and flow.client_secret:
            data["client_secret"] = flow.client_secret

        try:
            async with self._client() as client:
                response = await _bounded_response(
                    client,
                    "POST",
                    flow.token_endpoint,
                    maximum=_MAX_METADATA_BYTES,
                    error="oauth_token_exchange_failed",
                    data=data,
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            raise HostedOAuthError("oauth_token_exchange_failed") from exc
        if response.status_code != 200 or len(response.content) > _MAX_METADATA_BYTES:
            raise HostedOAuthError("oauth_token_exchange_failed")
        try:
            token = OAuthToken.model_validate_json(response.content)
        except ValidationError:
            raise HostedOAuthError("oauth_token_exchange_failed") from None

        access_token = _bounded_text(
            token.access_token,
            24 * 1024,
            "oauth_token_exchange_failed",
        )
        refresh_token = (
            _bounded_text(token.refresh_token, 24 * 1024, "oauth_token_exchange_failed")
            if token.refresh_token
            else None
        )
        if access_token is None:  # pragma: no cover - bounded_text rejects None
            raise HostedOAuthError("oauth_token_exchange_failed")
        stored = make_oauth_material(
            endpoint=flow.endpoint,
            access_token=access_token,
            refresh_token=refresh_token,
            token_type=token.token_type,
            expires_in=token.expires_in,
            scope=token.scope,
            client_id=flow.client_id,
            client_secret=flow.client_secret,
            token_endpoint=flow.token_endpoint,
            revocation_endpoint=flow.revocation_endpoint,
            allowed_workflow_ids=flow.allowed_workflow_ids,
        )
        return OAuthCompletion(
            stored_material=stored,
            access_material={
                "credential": access_token,
                "endpoint": flow.endpoint,
                "scheme": "bearer",
                "account": None,
            },
        )
