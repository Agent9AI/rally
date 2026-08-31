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
from typing import Any, Final, Literal, NoReturn, Protocol
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
from hosted_connectors import (
    connector as hosted_connector,
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
    issuer: str
    browser_binding_hash: str
    expires_at: dt.datetime


@dataclass(frozen=True, repr=False)
class OAuthAuthorization:
    authorization_url: str
    browser_binding: str


@dataclass(frozen=True, repr=False)
class OAuthCompletion:
    stored_material: str
    access_material: dict[str, str | None]


class OAuthFlowStore(Protocol):
    async def put(self, state: str, flow: OAuthFlow) -> None: ...

    async def consume(
        self,
        state: str,
        browser_binding: str,
        issuer: str | None = None,
    ) -> OAuthFlow | None: ...

    async def cancel(self, uid: str, connector_id: str) -> bool: ...


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


def _browser_binding_hash(browser_binding: str) -> str | None:
    if not isinstance(browser_binding, str) or not _STATE.fullmatch(browser_binding):
        return None
    return hashlib.sha256(browser_binding.encode("ascii")).hexdigest()


def _issuer_hash(issuer: str) -> str:
    return hashlib.sha256(issuer.encode("utf-8")).hexdigest()


def _flow_associated_data(state_hash: str) -> bytes:
    return f"{_FLOW_SCHEMA}\0{state_hash}".encode("ascii")


def _flow_active_key_for(uid: str, connector_id: str) -> str:
    material = f"{uid}\0{connector_id}".encode()
    return "active-" + hashlib.sha256(material).hexdigest()


def _flow_active_key(flow: OAuthFlow) -> str:
    return _flow_active_key_for(flow.identity.uid, flow.connector_id)


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
        self._active: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def put(self, state: str, flow: OAuthFlow) -> None:
        state_hash = _state_hash(state)
        if state_hash is None:
            raise HostedOAuthError("oauth_state_invalid")
        async with self._lock:
            active_key = _flow_active_key(flow)
            previous_hash = self._active.get(active_key)
            previous = self._flows.get(previous_hash or "")
            if previous is not None and previous.expires_at > self._clock():
                raise HostedOAuthError("oauth_in_progress")
            if previous_hash:
                self._flows.pop(previous_hash, None)
            self._flows[state_hash] = flow
            self._active[active_key] = state_hash

    async def consume(
        self,
        state: str,
        browser_binding: str,
        issuer: str | None = None,
    ) -> OAuthFlow | None:
        state_hash = _state_hash(state)
        binding_hash = _browser_binding_hash(browser_binding)
        if state_hash is None or binding_hash is None:
            return None
        async with self._lock:
            flow = self._flows.get(state_hash)
            if flow is None or not secrets.compare_digest(
                flow.browser_binding_hash,
                binding_hash,
            ):
                return None
            if issuer is not None and not secrets.compare_digest(flow.issuer, issuer):
                return None
            self._flows.pop(state_hash, None)
            self._active.pop(_flow_active_key(flow), None)
        if flow is None or flow.expires_at <= self._clock():
            return None
        return flow

    async def cancel(self, uid: str, connector_id: str) -> bool:
        """Remove only this tenant's unfinished connector handshake."""

        active_key = _flow_active_key_for(uid, connector_id)
        async with self._lock:
            state_hash = self._active.pop(active_key, None)
            if state_hash is None:
                return False
            flow = self._flows.get(state_hash)
            if flow is not None and _flow_active_key(flow) != active_key:
                self._active[active_key] = state_hash
                raise HostedOAuthError("oauth_store_unavailable")
            self._flows.pop(state_hash, None)
            return True


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
        from google.cloud import firestore

        state_hash = _state_hash(state)
        if state_hash is None:
            raise HostedOAuthError("oauth_state_invalid")
        document = self.collection.document(state_hash)
        active_key = _flow_active_key(flow)
        active = self.collection.document(active_key)
        try:
            envelope = await asyncio.to_thread(
                self.cipher.seal,
                _flow_payload(flow),
                _flow_associated_data(state_hash),
            )
            now = _utc_now()

            @firestore.async_transactional
            async def reserve(transaction: Any) -> None:
                previous = await active.get(transaction=transaction)
                if previous.exists:
                    previous_expiry = (previous.to_dict() or {}).get("expires_at")
                    if isinstance(previous_expiry, dt.datetime) and previous_expiry > now:
                        raise HostedOAuthError("oauth_in_progress")
                    transaction.delete(active)
                transaction.create(
                    document,
                    {
                        **envelope,
                        "active_key": active_key,
                        "browser_binding_hash": flow.browser_binding_hash,
                        "issuer_hash": _issuer_hash(flow.issuer),
                        "created_at": now,
                        "expires_at": flow.expires_at,
                    },
                )
                transaction.set(
                    active,
                    {
                        "state_hash": state_hash,
                        "created_at": now,
                        "expires_at": flow.expires_at,
                    },
                )

            await reserve(self.client.transaction())
        except HostedOAuthError:
            raise
        except Exception as exc:
            raise HostedOAuthError("oauth_store_unavailable") from exc

    async def consume(
        self,
        state: str,
        browser_binding: str,
        issuer: str | None = None,
    ) -> OAuthFlow | None:
        from google.cloud import firestore

        state_hash = _state_hash(state)
        binding_hash = _browser_binding_hash(browser_binding)
        if state_hash is None or binding_hash is None:
            return None
        document = self.collection.document(state_hash)

        @firestore.async_transactional
        async def take(transaction: Any) -> dict[str, Any] | None:
            snapshot = await document.get(transaction=transaction)
            if not snapshot.exists:
                return None
            record = snapshot.to_dict() or {}
            stored_binding_hash = record.get("browser_binding_hash")
            if not isinstance(stored_binding_hash, str) or not secrets.compare_digest(
                stored_binding_hash,
                binding_hash,
            ):
                return None
            if issuer is not None:
                stored_issuer_hash = record.get("issuer_hash")
                if not isinstance(stored_issuer_hash, str) or not secrets.compare_digest(
                    stored_issuer_hash,
                    _issuer_hash(issuer),
                ):
                    return None
            active_key = record.get("active_key")
            active_matches = False
            if isinstance(active_key, str) and active_key.startswith("active-"):
                active = self.collection.document(active_key)
                active_snapshot = await active.get(transaction=transaction)
                active_record = active_snapshot.to_dict() or {}
                active_matches = active_record.get("state_hash") == state_hash
            transaction.delete(document)
            if active_matches:
                transaction.delete(active)
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

    async def cancel(self, uid: str, connector_id: str) -> bool:
        """Transactionally cancel one exact tenant+connector active reservation."""

        from google.cloud import firestore

        active_key = _flow_active_key_for(uid, connector_id)
        active = self.collection.document(active_key)

        @firestore.async_transactional
        async def remove(transaction: Any) -> bool:
            active_snapshot = await active.get(transaction=transaction)
            if not active_snapshot.exists:
                return False
            state_hash = (active_snapshot.to_dict() or {}).get("state_hash")
            if not isinstance(state_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", state_hash):
                raise HostedOAuthError("oauth_store_unavailable")
            document = self.collection.document(state_hash)
            snapshot = await document.get(transaction=transaction)
            if snapshot.exists:
                record = snapshot.to_dict() or {}
                if record.get("active_key") != active_key:
                    raise HostedOAuthError("oauth_store_unavailable")
                transaction.delete(document)
            transaction.delete(active)
            return True

        try:
            return await remove(self.client.transaction())
        except HostedOAuthError:
            raise
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


def _stored_oauth_material(value: str) -> dict[str, str | None]:
    try:
        material = json.loads(value)
    except (TypeError, ValueError):
        raise HostedOAuthError("oauth_material_invalid") from None
    if not isinstance(material, dict) or material.get("schema") != "rally.oauth-material/v1":
        raise HostedOAuthError("oauth_material_invalid")
    bounded: dict[str, str | None] = {}
    for key, maximum, required in (
        ("endpoint", 2048, True),
        ("access_token", 24 * 1024, True),
        ("refresh_token", 24 * 1024, False),
        ("token_type", 64, True),
        ("client_id", 4096, True),
        ("client_secret", 8192, False),
        ("token_endpoint", 2048, True),
        ("revocation_endpoint", 2048, False),
        ("token_auth_method", 64, True),
    ):
        raw = material.get(key)
        if raw is None and not required:
            bounded[key] = None
            continue
        bounded[key] = _bounded_text(raw, maximum, "oauth_material_invalid")
    if bounded["token_auth_method"] not in {
        "none",
        "client_secret_basic",
        "client_secret_post",
    }:
        raise HostedOAuthError("oauth_material_invalid")
    if (bounded["token_type"] or "").casefold() != "bearer":
        raise HostedOAuthError("oauth_material_invalid")
    return bounded


def oauth_verification_material(
    item: HostedConnector,
    value: str,
) -> tuple[dict[str, str | None], tuple[str, ...]]:
    """Reopen only the access fields needed for a post-return live certification."""

    bounded = _stored_oauth_material(value)
    try:
        raw = json.loads(value)
        endpoint = resolve_endpoint(item, bounded["endpoint"])
        workflow_ids = normalize_workflow_ids(item, raw.get("allowed_workflow_ids"))
    except (TypeError, ValueError, HostedConnectorError) as exc:
        raise HostedOAuthError("oauth_material_invalid") from exc
    return (
        {
            "credential": bounded["access_token"],
            "endpoint": endpoint,
            "scheme": "bearer",
            "account": None,
        },
        workflow_ids,
    )


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
    ) -> OAuthAuthorization:
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
        if item.oauth_client_env:
            return await self._start_registered(
                item,
                identity,
                endpoint,
                workflow_scope,
            )

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
                issuer: str | None = None
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
                        raw_metadata = json.loads(response.content)
                        issuer = _bounded_text(
                            raw_metadata.get("issuer"),
                            2048,
                            "oauth_discovery_failed",
                        )
                    except HostedOAuthError:
                        continue
                    except (TypeError, ValueError):
                        continue
                    break
                if oauth_metadata is None or issuer is None:
                    raise HostedOAuthError("oauth_discovery_failed")

                authorization_endpoint = validate_oauth_url(
                    item,
                    str(oauth_metadata.authorization_endpoint),
                    endpoint,
                )
                validate_oauth_url(item, issuer, endpoint)
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
        browser_binding = secrets.token_urlsafe(32)
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
                issuer=issuer,
                browser_binding_hash=_browser_binding_hash(browser_binding) or "",
                expires_at=self.clock() + dt.timedelta(seconds=_FLOW_TTL_SECONDS),
            ),
        )
        return OAuthAuthorization(
            authorization_url=authorization_url,
            browser_binding=browser_binding,
        )

    async def _start_registered(
        self,
        item: HostedConnector,
        identity: UserIdentity,
        endpoint: str,
        workflow_scope: tuple[str, ...],
    ) -> OAuthAuthorization:
        """Start a provider-owned confidential app without customer setup detours."""

        if item.id != "google-workspace" or not item.oauth_client_env:
            raise HostedOAuthError("oauth_registration_unavailable")
        client_id = _bounded_text(
            os.getenv(f"{item.oauth_client_env}_CLIENT_ID", "").strip() or None,
            4096,
            "oauth_registration_unavailable",
        )
        client_secret = _bounded_text(
            os.getenv(f"{item.oauth_client_env}_CLIENT_SECRET", "").strip() or None,
            8192,
            "oauth_registration_unavailable",
        )
        if not client_id or not client_secret:
            raise HostedOAuthError("oauth_not_available")
        authorization_endpoint = validate_oauth_url(
            item,
            "https://accounts.google.com/o/oauth2/v2/auth",
            endpoint,
        )
        token_endpoint = validate_oauth_url(
            item,
            "https://oauth2.googleapis.com/token",
            endpoint,
        )
        revocation_endpoint = validate_oauth_url(
            item,
            "https://oauth2.googleapis.com/revoke",
            endpoint,
        )
        pkce = PKCEParameters.generate()
        state = secrets.token_urlsafe(32)
        browser_binding = secrets.token_urlsafe(32)
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": _CALLBACK_URL,
            "state": state,
            "code_challenge": pkce.code_challenge,
            "code_challenge_method": "S256",
            "scope": item.oauth_scope or "",
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
        }
        authorization_url = f"{authorization_endpoint}?{urlencode(params)}"
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
                token_auth_method="client_secret_post",
                code_verifier=pkce.code_verifier,
                scope=item.oauth_scope,
                resource=None,
                allowed_workflow_ids=workflow_scope,
                issuer="https://accounts.google.com",
                browser_binding_hash=_browser_binding_hash(browser_binding) or "",
                expires_at=self.clock() + dt.timedelta(seconds=_FLOW_TTL_SECONDS),
            ),
        )
        return OAuthAuthorization(
            authorization_url=authorization_url,
            browser_binding=browser_binding,
        )

    async def consume(
        self,
        state: str,
        browser_binding: str,
        issuer: str | None = None,
    ) -> OAuthFlow | None:
        return await self.store.consume(state, browser_binding, issuer)

    async def cancel_pending(self, identity: UserIdentity, connector_id: str) -> bool:
        """Cancel only the signed-in tenant's unfinished connector handshake."""

        return await self.store.cancel(identity.uid, connector_id)

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
        raw_access_token: str | None = None
        raw_refresh_token: str | None = None
        try:
            raw_token = json.loads(response.content)
            if isinstance(raw_token, dict):
                candidate = raw_token.get("access_token")
                raw_access_token = candidate if isinstance(candidate, str) and candidate else None
                candidate = raw_token.get("refresh_token")
                raw_refresh_token = candidate if isinstance(candidate, str) and candidate else None
            token = OAuthToken.model_validate_json(response.content)
        except (TypeError, ValueError, ValidationError):
            await self._reject_unaccepted_grant(
                flow,
                code="oauth_token_exchange_failed",
                access_token=raw_access_token,
                refresh_token=raw_refresh_token,
            )

        try:
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
            expires_in = token.expires_in
            if expires_in is not None and (
                isinstance(expires_in, bool) or not isinstance(expires_in, int) or expires_in < 300
            ):
                raise HostedOAuthError("oauth_token_exchange_failed")
            if expires_in is not None and refresh_token is None:
                raise HostedOAuthError("oauth_refresh_required")
            returned_scope = (
                _bounded_text(token.scope, 2048, "oauth_token_exchange_failed")
                if token.scope
                else flow.scope
            )
            requested_scopes = set((flow.scope or "").split())
            returned_scopes = set((returned_scope or "").split())
            if returned_scopes and (
                not requested_scopes or not returned_scopes.issubset(requested_scopes)
            ):
                raise HostedOAuthError("oauth_scope_widened")
            if flow.connector_id == "google-workspace" and returned_scopes != requested_scopes:
                raise HostedOAuthError("oauth_scope_incomplete")
            stored = make_oauth_material(
                endpoint=flow.endpoint,
                access_token=access_token,
                refresh_token=refresh_token,
                token_type=token.token_type,
                expires_in=expires_in,
                scope=returned_scope,
                client_id=flow.client_id,
                client_secret=flow.client_secret,
                token_endpoint=flow.token_endpoint,
                revocation_endpoint=flow.revocation_endpoint,
                token_auth_method=flow.token_auth_method,
                resource=flow.resource,
                allowed_workflow_ids=flow.allowed_workflow_ids,
            )
        except HostedOAuthError as exc:
            await self._reject_unaccepted_grant(
                flow,
                code=exc.code,
                access_token=raw_access_token,
                refresh_token=raw_refresh_token,
            )
        except HostedConnectorError:
            await self._reject_unaccepted_grant(
                flow,
                code="oauth_token_exchange_failed",
                access_token=raw_access_token,
                refresh_token=raw_refresh_token,
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

    async def _reject_unaccepted_grant(
        self,
        flow: OAuthFlow,
        *,
        code: str,
        access_token: str | None,
        refresh_token: str | None,
    ) -> NoReturn:
        """Revoke any token minted by a response Rally refuses to retain."""

        token = refresh_token or access_token
        if token is None:
            raise HostedOAuthError(code)
        try:
            item = hosted_connector(flow.connector_id)
            revoked = await self._revoke_token(
                item,
                endpoint=flow.endpoint,
                revocation_endpoint=flow.revocation_endpoint,
                token=token,
                token_type_hint=("refresh_token" if refresh_token else "access_token"),
                client_id=flow.client_id,
                client_secret=flow.client_secret,
                token_auth_method=flow.token_auth_method,
            )
        except (HostedConnectorError, HostedOAuthError):
            revoked = False
        if not revoked:
            raise HostedOAuthError("oauth_provider_cleanup_required")
        raise HostedOAuthError(code)

    async def _revoke_token(
        self,
        item: HostedConnector,
        *,
        endpoint: str,
        revocation_endpoint: str | None,
        token: str,
        token_type_hint: Literal["access_token", "refresh_token"],
        client_id: str,
        client_secret: str | None,
        token_auth_method: TokenAuthMethod,
    ) -> bool:
        if not revocation_endpoint:
            return False
        revocation_endpoint = validate_oauth_url(item, revocation_endpoint, endpoint)
        try:
            token_size = len(token.encode("utf-8"))
        except UnicodeEncodeError:
            raise HostedOAuthError("oauth_revocation_failed") from None
        if not token or token_size > _MAX_METADATA_BYTES:
            raise HostedOAuthError("oauth_revocation_failed")
        data = {
            "token": token,
            "token_type_hint": token_type_hint,
            "client_id": client_id,
        }
        headers = {"Accept": "application/json"}
        if token_auth_method == "client_secret_basic" and client_secret:
            credentials = f"{quote(client_id, safe='')}:{quote(client_secret, safe='')}"
            headers["Authorization"] = "Basic " + base64.b64encode(credentials.encode()).decode(
                "ascii"
            )
        elif token_auth_method == "client_secret_post" and client_secret:
            data["client_secret"] = client_secret
        try:
            async with self._client() as client:
                response = await _bounded_response(
                    client,
                    "POST",
                    revocation_endpoint,
                    maximum=4 * 1024,
                    error="oauth_revocation_failed",
                    data=data,
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            raise HostedOAuthError("oauth_revocation_failed") from exc
        if response.status_code not in {200, 204}:
            raise HostedOAuthError("oauth_revocation_failed")
        return True

    async def revoke(self, item: HostedConnector, stored_material: str) -> bool:
        """Revoke a provider OAuth grant before deleting Rally's encrypted copy."""

        material = _stored_oauth_material(stored_material)
        revocation_endpoint = material["revocation_endpoint"]
        if not revocation_endpoint:
            return False
        endpoint = material["endpoint"] or ""
        try:
            revocation_endpoint = validate_oauth_url(item, revocation_endpoint, endpoint)
        except HostedConnectorError as exc:
            raise HostedOAuthError(exc.code) from exc
        token = material["refresh_token"] or material["access_token"] or ""
        auth_method = material["token_auth_method"]
        client_secret = material["client_secret"]
        if auth_method not in {"none", "client_secret_basic", "client_secret_post"}:
            raise HostedOAuthError("oauth_material_invalid")
        return await self._revoke_token(
            item,
            endpoint=endpoint,
            revocation_endpoint=revocation_endpoint,
            token=token,
            token_type_hint=("refresh_token" if material["refresh_token"] else "access_token"),
            client_id=material["client_id"] or "",
            client_secret=client_secret,
            token_auth_method=auth_method,
        )
