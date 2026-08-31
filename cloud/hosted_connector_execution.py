"""Tenant-isolated execution of certified hosted connector read tools.

This module is deliberately separate from the local connector gateway. Hosted
calls obtain one tenant's encrypted credential from ``ConnectorVault``, apply a
committed read-only preset, and emit content-free audit receipts. Raw arguments,
provider results, and credential material are never written to the receipt store.
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
import time
from dataclasses import asdict, dataclass, replace
from typing import Any, Final, Protocol
from urllib.parse import quote

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth_utils import check_resource_allowed, resource_url_from_server_url

from connector_presets import ConnectorPresetError, build_connector_preset
from credential_vault import (
    ConnectorSecret,
    ConnectorVault,
    CredentialVaultBusy,
    CredentialVaultError,
    certified_manifest_sha256,
)
from hosted_connectors import (
    HostedConnector,
    HostedConnectorError,
    McpConnectionVerifier,
    authorization_headers,
    connector,
    resolve_endpoint,
    resolve_token_endpoint,
    unpack_secret,
    validate_oauth_url,
)
from hosted_mcp_transport import HostedMcpTransportError, make_hosted_mcp_http_client


class HostedExecutionError(RuntimeError):
    """A hosted invocation failed without carrying private provider content."""

    def __init__(self, code: str, receipt: ExecutionReceipt | None = None):
        super().__init__(code)
        self.code = code
        self.receipt = receipt


class ExecutionReceiptStoreError(RuntimeError):
    """A content-free execution receipt could not be durably recorded."""


_TOOL_NAME: Final = re.compile(r"^[A-Za-z0-9_.:/-]{1,160}$")
_CERTIFICATION_SCHEMA: Final = "rally.connection-certification/v1"
_RECEIPT_SCHEMA: Final = "rally.connector-execution-receipt/v1"
_MAX_ARGUMENT_BYTES: Final = 64 * 1024
_MAX_RESULT_BYTES: Final = 256 * 1024
_MAX_TOOL_SCHEMA_BYTES: Final = 64 * 1024
_MAX_WORKFLOW_IDS: Final = 64
_MAX_TOKEN_RESPONSE_BYTES: Final = 64 * 1024
_MAX_TOKEN_BYTES: Final = 24 * 1024
_RECEIPT_RETENTION_DAYS: Final = 90
_EXECUTION_DEADLINE_SECONDS: Final = 42.0
_EXECUTION_CLEANUP_SECONDS: Final = 4.0
_RECEIPT_WRITE_SECONDS: Final = 4.0
_TERMINAL_AUTH_ERRORS: Final = frozenset(
    {
        "credential_expired",
        "credential_invalid",
        "credential_refresh_failed",
        "provider_authentication_failed",
    }
)


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        raise HostedExecutionError("arguments_invalid") from None


def _contains_secret(value: Any, private_values: tuple[str, ...]) -> bool:
    if isinstance(value, str):
        return any(secret_value in value for secret_value in private_values)
    if isinstance(value, list):
        return any(_contains_secret(entry, private_values) for entry in value)
    if isinstance(value, dict):
        return any(
            _contains_secret(key, private_values) or _contains_secret(entry, private_values)
            for key, entry in value.items()
        )
    return False


def _is_authenticated_401(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 401
    if isinstance(exc, HostedMcpTransportError):
        return exc.status_code == 401
    nested = getattr(exc, "exceptions", ())
    return isinstance(nested, tuple) and any(_is_authenticated_401(item) for item in nested)


def _owner_hash(uid: str) -> str:
    return hashlib.sha256(uid.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ExecutionReceipt:
    """Public, content-free evidence for one attempted connector invocation."""

    execution_id: str
    connector_id: str
    tool_name: str
    decision: str
    arguments_sha256: str
    argument_bytes: int
    created_at: str
    completed_at: str | None = None
    result_sha256: str | None = None
    result_bytes: int | None = None
    result_is_error: bool | None = None
    error_code: str | None = None
    duration_ms: int | None = None
    credential_generation: str | None = None
    certified_manifest_sha256: str | None = None
    policy_sha256: str | None = None
    schema: str = _RECEIPT_SCHEMA

    def public(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


class ExecutionReceiptStore(Protocol):
    async def put(self, uid: str, receipt: ExecutionReceipt) -> None: ...


class MemoryExecutionReceiptStore:
    """Explicit test/development receipt store, isolated by tenant hash."""

    def __init__(self):
        self.items: dict[tuple[str, str], dict[str, Any]] = {}

    async def put(self, uid: str, receipt: ExecutionReceipt) -> None:
        self.items[(_owner_hash(uid), receipt.execution_id)] = receipt.public()


class FirestoreExecutionReceiptStore:
    """Append/update content-free receipts without storing a tenant identifier."""

    def __init__(self, project_id: str, client: Any | None = None):
        if not project_id:
            raise ExecutionReceiptStoreError("receipt store is not configured")
        if client is None:
            from google.cloud import firestore

            client = firestore.AsyncClient(project=project_id)
        self.collection = client.collection("connector_execution_receipts")

    async def put(self, uid: str, receipt: ExecutionReceipt) -> None:
        record = {
            **receipt.public(),
            "owner_hash": _owner_hash(uid),
            "expires_at": _utc_now() + dt.timedelta(days=_RECEIPT_RETENTION_DAYS),
        }
        try:
            await self.collection.document(receipt.execution_id).set(record)
        except Exception as exc:
            raise ExecutionReceiptStoreError("could not record execution receipt") from exc


def make_execution_receipt_store() -> ExecutionReceiptStore:
    if os.getenv("RALLY_VAULT_BACKEND", "") == "google_kms":
        return FirestoreExecutionReceiptStore(os.getenv("GOOGLE_CLOUD_PROJECT", ""))
    if (
        os.getenv("RALLY_VAULT_BACKEND", "") == "memory"
        and os.getenv("RALLY_ALLOW_INSECURE_DEV") == "1"
    ):
        return MemoryExecutionReceiptStore()
    raise ExecutionReceiptStoreError("receipt store is not configured")


@dataclass(frozen=True, repr=False)
class _RuntimeMaterial:
    endpoint: str
    headers: dict[str, str]
    allowed_workflow_ids: tuple[str, ...]
    secret_values: tuple[str, ...]


@dataclass(frozen=True)
class HostedCallResult:
    payload: dict[str, Any]
    is_error: bool


@dataclass(frozen=True)
class HostedExecutionResult:
    payload: dict[str, Any]
    receipt: ExecutionReceipt


def _bounded_private_text(value: Any, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise HostedExecutionError("credential_refresh_failed")
    return value


class HostedOAuthRefresher:
    """Refresh one sealed OAuth grant against its provider-pinned token endpoint."""

    def __init__(self, client_factory=None, *, clock=_utc_now):
        self.client_factory = client_factory or (
            lambda: httpx.AsyncClient(
                timeout=httpx.Timeout(12.0, read=20.0),
                follow_redirects=False,
            )
        )
        self.clock = clock

    async def refresh(self, item: HostedConnector, stored_value: str) -> str:
        try:
            raw = json.loads(stored_value)
        except (TypeError, ValueError):
            raise HostedExecutionError("credential_refresh_failed") from None
        if not isinstance(raw, dict) or raw.get("schema") != "rally.oauth-material/v1":
            raise HostedExecutionError("credential_refresh_failed")
        endpoint = raw.get("endpoint")
        token_endpoint = raw.get("token_endpoint")
        refresh_token = _bounded_private_text(raw.get("refresh_token"), _MAX_TOKEN_BYTES)
        client_id = _bounded_private_text(raw.get("client_id"), 4096)
        if not isinstance(endpoint, str) or not isinstance(token_endpoint, str):
            raise HostedExecutionError("credential_refresh_failed")
        try:
            endpoint = resolve_endpoint(item, endpoint)
            token_endpoint = validate_oauth_url(item, token_endpoint, endpoint)
        except HostedConnectorError as exc:
            raise HostedExecutionError("credential_refresh_failed") from exc
        resource = raw.get("resource")
        if resource is not None:
            if not isinstance(resource, str) or len(resource.encode("utf-8")) > 2048:
                raise HostedExecutionError("credential_refresh_failed")
            try:
                resource = validate_oauth_url(item, resource, endpoint)
            except HostedConnectorError as exc:
                raise HostedExecutionError("credential_refresh_failed") from exc
            try:
                allowed_resource = check_resource_allowed(
                    requested_resource=resource_url_from_server_url(endpoint),
                    configured_resource=resource,
                )
            except ValueError:
                raise HostedExecutionError("credential_refresh_failed") from None
            if not allowed_resource:
                raise HostedExecutionError("credential_refresh_failed")

        auth_method = raw.get("token_auth_method")
        if auth_method not in {"none", "client_secret_basic", "client_secret_post"}:
            raise HostedExecutionError("credential_refresh_failed")
        client_secret = raw.get("client_secret")
        if auth_method != "none":
            client_secret = _bounded_private_text(client_secret, 8192)
        elif client_secret is not None and not isinstance(client_secret, str):
            raise HostedExecutionError("credential_refresh_failed")

        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        }
        if resource is not None:
            data["resource"] = resource
        headers = {"Accept": "application/json"}
        if auth_method == "client_secret_basic":
            credentials = f"{quote(client_id, safe='')}:{quote(client_secret or '', safe='')}"
            headers["Authorization"] = "Basic " + base64.b64encode(
                credentials.encode("utf-8")
            ).decode("ascii")
        elif auth_method == "client_secret_post":
            data["client_secret"] = client_secret or ""

        try:
            async with (
                asyncio.timeout(25),
                self.client_factory() as client,
                client.stream(
                    "POST",
                    token_endpoint,
                    data=data,
                    headers=headers,
                ) as response,
            ):
                declared = response.headers.get("content-length")
                if declared:
                    try:
                        if int(declared) > _MAX_TOKEN_RESPONSE_BYTES:
                            raise HostedExecutionError("credential_refresh_failed")
                    except ValueError:
                        raise HostedExecutionError("credential_refresh_failed") from None
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > _MAX_TOKEN_RESPONSE_BYTES:
                        raise HostedExecutionError("credential_refresh_failed")
                if response.status_code != 200:
                    raise HostedExecutionError("credential_refresh_failed")
        except HostedExecutionError:
            raise
        except Exception:  # noqa: BLE001 - suppress every untrusted token endpoint detail
            # Token endpoints often return sensitive diagnostics; never propagate them.
            raise HostedExecutionError("credential_refresh_failed") from None

        try:
            refreshed = json.loads(content)
        except (TypeError, ValueError):
            raise HostedExecutionError("credential_refresh_failed") from None
        if not isinstance(refreshed, dict):
            raise HostedExecutionError("credential_refresh_failed")
        access_token = _bounded_private_text(refreshed.get("access_token"), _MAX_TOKEN_BYTES)
        token_type = refreshed.get("token_type", raw.get("token_type"))
        if not isinstance(token_type, str) or token_type.casefold() != "bearer":
            raise HostedExecutionError("credential_refresh_failed")
        rotated_refresh = refreshed.get("refresh_token")
        if rotated_refresh is not None:
            rotated_refresh = _bounded_private_text(rotated_refresh, _MAX_TOKEN_BYTES)
        else:
            rotated_refresh = refresh_token
        expires_in = refreshed.get("expires_in", raw.get("expires_in"))
        if expires_in is not None and (
            isinstance(expires_in, bool) or not isinstance(expires_in, int) or expires_in <= 0
        ):
            raise HostedExecutionError("credential_refresh_failed")
        original_scope = raw.get("scope")
        refreshed_scope = refreshed.get("scope", original_scope)
        if refreshed_scope is not None and not isinstance(refreshed_scope, str):
            raise HostedExecutionError("credential_refresh_failed")
        if (
            isinstance(original_scope, str)
            and isinstance(refreshed_scope, str)
            and not set(refreshed_scope.split()).issubset(set(original_scope.split()))
        ):
            raise HostedExecutionError("credential_refresh_failed")

        updated = {
            **raw,
            "endpoint": endpoint,
            "access_token": access_token,
            "refresh_token": rotated_refresh,
            "token_type": "Bearer",
            "expires_in": expires_in,
            "obtained_at": self.clock().isoformat(),
            "scope": refreshed_scope,
            "token_endpoint": token_endpoint,
        }
        return json.dumps(updated, separators=(",", ":"))


def _workflow_ids(value: Any, item: HostedConnector) -> tuple[str, ...]:
    if value is None:
        values: list[Any] = []
    elif isinstance(value, list):
        values = value
    else:
        raise HostedExecutionError("credential_invalid")
    if len(values) > _MAX_WORKFLOW_IDS or any(not isinstance(entry, str) for entry in values):
        raise HostedExecutionError("credential_invalid")
    normalized = tuple(sorted(set(values)))
    if any(
        not entry
        or len(entry) > 256
        or any(ord(character) < 33 or ord(character) == 127 for character in entry)
        for entry in normalized
    ):
        raise HostedExecutionError("credential_invalid")
    if item.id == "n8n" and not normalized:
        raise HostedExecutionError("policy_configuration_required")
    if item.id != "n8n" and normalized:
        raise HostedExecutionError("credential_invalid")
    return normalized


def _stored_token_endpoint(item: HostedConnector, supplied: str) -> str:
    """Revalidate the exact endpoint accepted when a pasted token was stored."""

    if item.token_endpoint is not None:
        alternate = resolve_token_endpoint(item)
        if supplied == alternate:
            return alternate
    return resolve_token_endpoint(item, supplied)


def _parse_timestamp(value: Any) -> dt.datetime:
    if not isinstance(value, str):
        raise HostedExecutionError("credential_invalid")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        raise HostedExecutionError("credential_invalid") from None
    if parsed.tzinfo is None:
        raise HostedExecutionError("credential_invalid")
    return parsed.astimezone(dt.UTC)


def _runtime_material(
    item: HostedConnector,
    stored_value: str,
    *,
    now: dt.datetime,
) -> _RuntimeMaterial:
    try:
        raw = json.loads(stored_value)
    except (TypeError, ValueError):
        raise HostedExecutionError("credential_invalid") from None
    if not isinstance(raw, dict):
        raise HostedExecutionError("credential_invalid")

    schema = raw.get("schema")
    if schema == "rally.connection-material/v1":
        try:
            material = unpack_secret(stored_value)
            endpoint = _stored_token_endpoint(item, str(material["endpoint"] or ""))
            headers = authorization_headers(item, material)
        except HostedConnectorError as exc:
            raise HostedExecutionError(exc.code) from exc
        workflow_ids = _workflow_ids(raw.get("allowed_workflow_ids"), item)
        credential = str(material["credential"] or "")
        return _RuntimeMaterial(
            endpoint=endpoint,
            headers=headers,
            allowed_workflow_ids=workflow_ids,
            secret_values=(credential,),
        )

    if schema != "rally.oauth-material/v1":
        raise HostedExecutionError("credential_invalid")
    access_token = raw.get("access_token")
    token_type = raw.get("token_type")
    endpoint_value = raw.get("endpoint")
    if (
        not isinstance(access_token, str)
        or not access_token
        or not isinstance(token_type, str)
        or token_type.casefold() != "bearer"
        or not isinstance(endpoint_value, str)
    ):
        raise HostedExecutionError("credential_invalid")
    try:
        endpoint = resolve_endpoint(item, endpoint_value)
    except HostedConnectorError as exc:
        raise HostedExecutionError(exc.code) from exc
    expires_in = raw.get("expires_in")
    if expires_in is not None:
        if isinstance(expires_in, bool) or not isinstance(expires_in, int) or expires_in <= 0:
            raise HostedExecutionError("credential_invalid")
        obtained_at = _parse_timestamp(raw.get("obtained_at"))
        if obtained_at + dt.timedelta(seconds=expires_in) <= now + dt.timedelta(seconds=15):
            raise HostedExecutionError("credential_expired")
    workflow_ids = _workflow_ids(raw.get("allowed_workflow_ids"), item)
    material = {
        "credential": access_token,
        "endpoint": endpoint,
        "scheme": "bearer",
        "account": None,
    }
    headers = authorization_headers(item, material)
    private_values = tuple(
        value
        for value in (
            access_token,
            raw.get("refresh_token"),
            raw.get("client_secret"),
        )
        if isinstance(value, str) and value
    )
    return _RuntimeMaterial(
        endpoint=endpoint,
        headers=headers,
        allowed_workflow_ids=workflow_ids,
        secret_values=private_values,
    )


def _enforce_tool_policy(
    item: HostedConnector,
    tool_name: str,
    arguments: dict[str, Any],
    workflow_ids: tuple[str, ...],
) -> tuple[bytes, int, str]:
    if not _TOOL_NAME.fullmatch(tool_name):
        raise HostedExecutionError("tool_invalid")
    try:
        preset = build_connector_preset(
            item.id,
            item.safe_preset,
            allowed_workflow_ids=(workflow_ids if item.id == "n8n" else None),
        )
    except ConnectorPresetError as exc:
        raise HostedExecutionError("safe_preset_unavailable") from exc
    rule = preset.get(tool_name)
    if not isinstance(rule, dict):
        raise HostedExecutionError("tool_not_allowed")
    if rule.get("risk") != "read":
        raise HostedExecutionError("human_approval_required")
    constraints = rule.get("constraints")
    if not isinstance(constraints, dict):
        raise HostedExecutionError("safe_preset_unavailable")
    argument_rules = constraints.get("arguments", {})
    if not isinstance(argument_rules, dict):
        raise HostedExecutionError("safe_preset_unavailable")
    if argument_rules and any(name not in argument_rules for name in arguments):
        raise HostedExecutionError("argument_not_allowed")
    for name, constraint in argument_rules.items():
        if not isinstance(constraint, dict):
            raise HostedExecutionError("safe_preset_unavailable")
        value = arguments.get(name)
        if constraint.get("required") is True and name not in arguments:
            raise HostedExecutionError("argument_required")
        if name not in arguments:
            continue
        max_length = constraint.get("max_length")
        if max_length is not None and (
            not isinstance(max_length, int) or not isinstance(value, str) or len(value) > max_length
        ):
            raise HostedExecutionError("argument_invalid")
        allowed_values = constraint.get("allowed_values")
        if allowed_values is not None and value not in allowed_values:
            raise HostedExecutionError("argument_not_allowed")
    encoded = _canonical_json(arguments)
    configured_cap = constraints.get("max_argument_bytes", _MAX_ARGUMENT_BYTES)
    if isinstance(configured_cap, bool) or not isinstance(configured_cap, int):
        raise HostedExecutionError("safe_preset_unavailable")
    if len(encoded) > min(configured_cap, _MAX_ARGUMENT_BYTES):
        raise HostedExecutionError("arguments_too_large")
    result_cap = constraints.get("max_result_bytes", _MAX_RESULT_BYTES)
    if isinstance(result_cap, bool) or not isinstance(result_cap, int) or result_cap < 1:
        raise HostedExecutionError("safe_preset_unavailable")
    policy_sha256 = hashlib.sha256(_canonical_json(preset)).hexdigest()
    return encoded, min(result_cap, _MAX_RESULT_BYTES), policy_sha256


def _route(item: HostedConnector, material: _RuntimeMaterial, tool_name: str) -> tuple[str, str]:
    if not item.service_endpoints:
        return material.endpoint, tool_name
    service, separator, raw_name = tool_name.partition(".")
    endpoint = dict(item.service_endpoints).get(service)
    if not separator or not raw_name or endpoint is None:
        raise HostedExecutionError("tool_not_allowed")
    return endpoint, raw_name


class HostedMcpCaller:
    """Make one bounded MCP call with headers created from one vault secret."""

    async def call(
        self,
        *,
        endpoint: str,
        headers: dict[str, str],
        tool_name: str,
        arguments: dict[str, Any],
        expected_schema_sha256: str,
    ) -> HostedCallResult:
        try:
            async with asyncio.timeout(35):
                async with (
                    make_hosted_mcp_http_client(
                        headers=headers,
                        client_factory=httpx.AsyncClient,
                    ) as http_client,
                    streamable_http_client(
                        endpoint,
                        http_client=http_client,
                        terminate_on_close=True,
                    ) as (read_stream, write_stream, _),
                    ClientSession(read_stream, write_stream) as session,
                ):
                    await session.initialize()
                    tools = await McpConnectionVerifier().discover_tools(session)
                    selected = next(
                        (tool for tool in tools if str(tool.name) == tool_name),
                        None,
                    )
                    if selected is None:
                        raise HostedExecutionError("tool_unavailable")
                    schema = getattr(selected, "inputSchema", None)
                    if not isinstance(schema, dict):
                        raise HostedExecutionError("tool_schema_invalid")
                    try:
                        encoded_schema = _canonical_json(schema)
                    except HostedExecutionError as exc:
                        raise HostedExecutionError("tool_schema_invalid") from exc
                    if len(encoded_schema) > _MAX_TOOL_SCHEMA_BYTES:
                        raise HostedExecutionError("tool_schema_too_large")
                    current_schema_sha256 = hashlib.sha256(encoded_schema).hexdigest()
                    if not secrets.compare_digest(
                        current_schema_sha256,
                        expected_schema_sha256,
                    ):
                        raise HostedExecutionError("tool_schema_changed")
                    result = await session.call_tool(tool_name, arguments=arguments)
                    payload = result.model_dump(mode="json", by_alias=True, exclude_none=True)
                    if not isinstance(payload, dict):
                        raise HostedExecutionError("provider_result_invalid")
                    return HostedCallResult(payload=payload, is_error=result.isError is True)
        except HostedExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001 - suppress every untrusted MCP/provider detail
            # Never carry a provider exception or response body across this boundary.
            if _is_authenticated_401(exc):
                raise HostedExecutionError("provider_authentication_failed") from None
            raise HostedExecutionError("provider_unavailable") from None


class HostedConnectorExecutor:
    def __init__(
        self,
        vault: ConnectorVault,
        receipt_store: ExecutionReceiptStore,
        caller: HostedMcpCaller,
        refresher: HostedOAuthRefresher | None = None,
        *,
        clock=_utc_now,
        execution_deadline_seconds: float = _EXECUTION_DEADLINE_SECONDS,
        cleanup_timeout_seconds: float = _EXECUTION_CLEANUP_SECONDS,
        receipt_timeout_seconds: float = _RECEIPT_WRITE_SECONDS,
    ):
        self.vault = vault
        self.receipt_store = receipt_store
        self.caller = caller
        self.refresher = refresher or HostedOAuthRefresher(clock=clock)
        self.clock = clock
        self.execution_deadline_seconds = execution_deadline_seconds
        self.cleanup_timeout_seconds = cleanup_timeout_seconds
        self.receipt_timeout_seconds = receipt_timeout_seconds

    async def _record(self, uid: str, receipt: ExecutionReceipt) -> None:
        try:
            async with asyncio.timeout(self.receipt_timeout_seconds):
                await self.receipt_store.put(uid, receipt)
        except Exception as exc:
            if isinstance(exc, ExecutionReceiptStoreError):
                raise HostedExecutionError("receipt_unavailable") from exc
            raise HostedExecutionError("receipt_unavailable") from exc

    async def _release_lease(
        self,
        uid: str,
        connector_id: str,
        lease: str,
    ) -> bool:
        """Release a connector lease within the request's reserved cleanup budget."""

        release = asyncio.create_task(
            self.vault.release_execution(
                uid,
                connector_id,
                expected_lease=lease,
            )
        )
        try:
            async with asyncio.timeout(self.cleanup_timeout_seconds):
                return await asyncio.shield(release)
        except TimeoutError:
            release.cancel()
            await asyncio.gather(release, return_exceptions=True)
            raise CredentialVaultError("connector lease cleanup timed out") from None

    async def _refresh_runtime_material(
        self,
        *,
        uid: str,
        connector_id: str,
        item: HostedConnector,
        previous: ConnectorSecret,
        expected_generation: str,
        expected_lease: str,
        now: dt.datetime,
    ) -> tuple[ConnectorSecret, _RuntimeMaterial, str]:
        refreshed_value = await self.refresher.refresh(item, previous.value)
        try:
            refreshed = ConnectorSecret(refreshed_value, previous.kind)
        except CredentialVaultError as invalid:
            raise HostedExecutionError("credential_refresh_failed") from invalid
        rotated = await self.vault.rotate(
            uid,
            connector_id,
            expected_generation=expected_generation,
            expected_lease=expected_lease,
            expected=previous,
            secret=refreshed,
        )
        if rotated is not None:
            return (
                refreshed,
                _runtime_material(item, refreshed.value, now=now),
                rotated.credential_generation,
            )

        # Another request may have won the compare-and-swap with a good rotation.
        # Reuse only that exact tenant's now-valid sealed material; never overwrite it.
        winner = await self.vault.get_connection(uid, connector_id)
        if (
            winner is not None
            and winner.record.status == "ready"
            and winner.record.execution_lease == expected_lease
            and winner.record.credential_generation != expected_generation
            and winner.secret != previous
            and winner.secret.kind == previous.kind
        ):
            try:
                return (
                    winner.secret,
                    _runtime_material(item, winner.secret.value, now=now),
                    winner.record.credential_generation,
                )
            except HostedExecutionError:
                pass
        raise HostedExecutionError("credential_refresh_conflict")

    async def _require_reconnect(
        self,
        uid: str,
        connector_id: str,
        expected: ConnectorSecret,
        expected_generation: str,
        expected_lease: str,
    ) -> None:
        try:
            demoted = await self.vault.quarantine(
                uid,
                connector_id,
                expected_generation=expected_generation,
                expected_lease=expected_lease,
                expected=expected,
                error_code="reconnect_required",
            )
        except CredentialVaultError as exc:
            raise HostedExecutionError("vault_unavailable") from exc
        if not demoted:
            raise HostedExecutionError("credential_refresh_conflict")

    async def execute(
        self,
        *,
        uid: str,
        connector_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> HostedExecutionResult:
        if not isinstance(arguments, dict) or any(not isinstance(key, str) for key in arguments):
            raise HostedExecutionError("arguments_invalid")
        argument_bytes = _canonical_json(arguments)
        created = self.clock()
        receipt = ExecutionReceipt(
            execution_id=secrets.token_hex(16),
            connector_id=connector_id,
            tool_name=tool_name,
            decision="started",
            arguments_sha256=hashlib.sha256(argument_bytes).hexdigest(),
            argument_bytes=len(argument_bytes),
            created_at=_iso(created),
        )
        started = time.monotonic()

        result_hash: str | None = None
        result_size: int | None = None
        result_is_error: bool | None = None
        secret: ConnectorSecret | None = None
        credential_generation: str | None = None
        certified_manifest: str | None = None
        policy_sha256: str | None = None
        lease: str | None = None
        called: HostedCallResult | None = None
        failure: HostedExecutionError | None = None
        cancellation: asyncio.CancelledError | None = None
        try:
            try:
                async with asyncio.timeout(self.execution_deadline_seconds):
                    await self._record(uid, receipt)
                    item = connector(connector_id)
                    try:
                        claimed = await self.vault.claim_execution(uid, connector_id)
                    except CredentialVaultBusy:
                        raise HostedExecutionError("connection_busy") from None
                    if claimed is None:
                        current = await self.vault.get_connection(uid, connector_id)
                        if current is None:
                            raise HostedExecutionError("connection_not_found")
                        raise HostedExecutionError("connection_not_ready")
                    record = claimed.record
                    secret = claimed.secret
                    lease = record.execution_lease
                    if (
                        record.status != "ready"
                        or record.proof_version != _CERTIFICATION_SCHEMA
                        or not record.canary_tool
                        or not record.tool_schema_sha256
                        or not record.credential_generation
                        or not lease
                        or record.tool_count != len(record.certified_tools)
                        or record.certified_manifest_sha256
                        != certified_manifest_sha256(record.certified_tools)
                    ):
                        raise HostedExecutionError("connection_not_ready")
                    credential_generation = record.credential_generation
                    certified_manifest = record.certified_manifest_sha256
                    refreshed_once = False
                    try:
                        material = _runtime_material(item, secret.value, now=created)
                    except HostedExecutionError as exc:
                        if exc.code != "credential_expired" or secret.kind != "oauth_refresh_token":
                            raise
                        (
                            secret,
                            material,
                            credential_generation,
                        ) = await self._refresh_runtime_material(
                            uid=uid,
                            connector_id=connector_id,
                            item=item,
                            previous=secret,
                            expected_generation=credential_generation,
                            expected_lease=lease,
                            now=created,
                        )
                        refreshed_once = True
                    argument_bytes, result_cap, policy_sha256 = _enforce_tool_policy(
                        item,
                        tool_name,
                        arguments,
                        material.allowed_workflow_ids,
                    )
                    expected_schema_sha256 = dict(record.certified_tools).get(tool_name)
                    if expected_schema_sha256 is None:
                        raise HostedExecutionError("tool_not_certified")
                    endpoint, remote_tool_name = _route(item, material, tool_name)
                    try:
                        called = await self.caller.call(
                            endpoint=endpoint,
                            headers=material.headers,
                            tool_name=remote_tool_name,
                            arguments=arguments,
                            expected_schema_sha256=expected_schema_sha256,
                        )
                    except HostedExecutionError as exc:
                        if (
                            exc.code != "provider_authentication_failed"
                            or secret.kind != "oauth_refresh_token"
                            or refreshed_once
                        ):
                            raise
                        (
                            secret,
                            material,
                            credential_generation,
                        ) = await self._refresh_runtime_material(
                            uid=uid,
                            connector_id=connector_id,
                            item=item,
                            previous=secret,
                            expected_generation=credential_generation,
                            expected_lease=lease,
                            now=created,
                        )
                        endpoint, remote_tool_name = _route(item, material, tool_name)
                        called = await self.caller.call(
                            endpoint=endpoint,
                            headers=material.headers,
                            tool_name=remote_tool_name,
                            arguments=arguments,
                            expected_schema_sha256=expected_schema_sha256,
                        )
                    encoded_result = _canonical_json(called.payload)
                    result_hash = hashlib.sha256(encoded_result).hexdigest()
                    result_size = len(encoded_result)
                    result_is_error = called.is_error
                    if result_size > result_cap:
                        raise HostedExecutionError("result_too_large")
                    if _contains_secret(called.payload, material.secret_values):
                        raise HostedExecutionError("secret_detected")
                    if called.is_error:
                        raise HostedExecutionError("provider_tool_error")
            except asyncio.CancelledError as exc:
                cancellation = exc
                failure = HostedExecutionError("execution_cancelled")
            except TimeoutError:
                failure = HostedExecutionError("execution_timeout")
            except (CredentialVaultError, HostedConnectorError) as exc:
                code = "vault_unavailable" if isinstance(exc, CredentialVaultError) else exc.code
                failure = HostedExecutionError(code)
            except HostedExecutionError as exc:
                failure = exc
            except Exception:  # noqa: BLE001 - suppress every untrusted provider/runtime detail
                failure = HostedExecutionError("execution_failed")

            if (
                failure is not None
                and failure.code in _TERMINAL_AUTH_ERRORS
                and secret is not None
                and credential_generation is not None
                and lease is not None
            ):
                try:
                    async with asyncio.timeout(self.cleanup_timeout_seconds):
                        await self._require_reconnect(
                            uid,
                            connector_id,
                            secret,
                            credential_generation,
                            lease,
                        )
                except (TimeoutError, HostedExecutionError) as exc:
                    failure = (
                        exc
                        if isinstance(exc, HostedExecutionError)
                        else HostedExecutionError("vault_unavailable")
                    )
                else:
                    failure = HostedExecutionError("reconnect_required")
                    lease = None
        finally:
            if lease is not None:
                try:
                    released = await self._release_lease(uid, connector_id, lease)
                except CredentialVaultError:
                    failure = HostedExecutionError("vault_unavailable")
                else:
                    if not released:
                        failure = HostedExecutionError("credential_refresh_conflict")

        bound_receipt = replace(
            receipt,
            credential_generation=credential_generation,
            certified_manifest_sha256=certified_manifest,
            policy_sha256=policy_sha256,
        )
        if failure is None and called is not None:
            completed = replace(
                bound_receipt,
                decision="allowed",
                completed_at=_iso(self.clock()),
                result_sha256=result_hash,
                result_bytes=result_size,
                result_is_error=False,
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            )
            await self._record(uid, completed)
            return HostedExecutionResult(payload=called.payload, receipt=completed)

        failure = failure or HostedExecutionError("execution_failed")

        failed = replace(
            bound_receipt,
            decision=(
                "denied"
                if failure.code
                in {
                    "argument_invalid",
                    "argument_not_allowed",
                    "argument_required",
                    "arguments_invalid",
                    "arguments_too_large",
                    "connection_not_found",
                    "connection_not_ready",
                    "connection_busy",
                    "credential_expired",
                    "human_approval_required",
                    "tool_invalid",
                    "tool_not_allowed",
                    "tool_not_certified",
                }
                else "failed"
            ),
            completed_at=_iso(self.clock()),
            result_sha256=result_hash,
            result_bytes=result_size,
            result_is_error=result_is_error,
            error_code=failure.code,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        )
        await self._record(uid, failed)
        if cancellation is not None:
            raise cancellation
        raise HostedExecutionError(failure.code, failed)
