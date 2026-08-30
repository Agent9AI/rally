"""Deny-by-default MCP gateway shared by Rally's cross-family workers."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import httpx
from google.auth import default as google_auth_default
from google.auth import load_credentials_from_file
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request as GoogleAuthRequest
from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.streamable_http import streamable_http_client
from mcp.server.fastmcp import FastMCP
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken


class ConnectorGatewayError(RuntimeError):
    pass


class KeychainTokenStorage(TokenStorage):
    """Keep OAuth material in macOS Keychain, never in Rally config or receipts."""

    def __init__(self, service: str):
        self.service = service

    def _read(self, account: str) -> str | None:
        try:
            result = subprocess.run(
                ["security", "find-generic-password", "-w", "-s", self.service, "-a", account],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout.strip() or None

    def _write(self, account: str, value: str) -> None:
        try:
            subprocess.run(
                [
                    "security",
                    "add-generic-password",
                    "-U",
                    "-s",
                    self.service,
                    "-a",
                    account,
                    "-w",
                    value,
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ConnectorGatewayError(
                f"could not write OAuth state to macOS Keychain service {self.service}"
            ) from exc

    async def get_tokens(self) -> OAuthToken | None:
        value = await asyncio.to_thread(self._read, "tokens")
        return OAuthToken.model_validate_json(value) if value else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        await asyncio.to_thread(self._write, "tokens", tokens.model_dump_json())

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        value = await asyncio.to_thread(self._read, "client")
        return OAuthClientInformationFull.model_validate_json(value) if value else None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        await asyncio.to_thread(self._write, "client", client_info.model_dump_json())


def load_authority(path: str | None = None) -> dict[str, Any]:
    policy_path = path or os.environ.get("RALLY_CONNECTOR_POLICY", "")
    if not policy_path:
        raise ConnectorGatewayError("RALLY_CONNECTOR_POLICY is not set")
    try:
        with open(policy_path) as handle:
            authority = json.load(handle)
    except (OSError, ValueError) as exc:
        raise ConnectorGatewayError(f"cannot read connector authority: {exc}") from exc
    if authority.get("schema_version") != "rally.connector-authority/v1":
        raise ConnectorGatewayError("unsupported connector authority schema")
    if authority.get("default_decision") != "deny":
        raise ConnectorGatewayError("connector authority must default to deny")
    return authority


def connector_by_id(authority: dict[str, Any], connector_id: str) -> dict[str, Any]:
    for connector in authority.get("connectors") or []:
        if connector.get("id") == connector_id:
            return connector
    raise ConnectorGatewayError(f"connector {connector_id} is not enabled for this run")


def _google_headers(auth: dict[str, Any]) -> dict[str, str]:
    try:
        scopes = auth.get("scopes") or ["https://www.googleapis.com/auth/cloud-platform"]
        credential_file = auth.get("credential_file")
        if credential_file:
            credentials, _ = load_credentials_from_file(
                os.path.abspath(os.path.expanduser(credential_file)), scopes=scopes
            )
        else:
            credentials, _ = google_auth_default(scopes=scopes)
        if not credentials.valid:
            credentials.refresh(GoogleAuthRequest())
    except (GoogleAuthError, OSError, ValueError) as exc:
        raise ConnectorGatewayError(
            "Google Application Default Credentials could not be refreshed"
        ) from exc
    if not credentials.token:
        raise ConnectorGatewayError("Google Application Default Credentials returned no token")
    headers = {"Authorization": "Bearer " + credentials.token}
    quota_project = getattr(credentials, "quota_project_id", None)
    if quota_project:
        headers["x-goog-user-project"] = quota_project
    return headers


async def _not_interactive(_: str) -> None:
    raise ConnectorGatewayError(
        "connector OAuth is not authorized; run './bin/rally connectors auth <id>'"
    )


async def _no_callback() -> tuple[str, str | None]:
    raise ConnectorGatewayError("interactive OAuth is disabled inside an agent run")


def oauth_provider(
    connector: dict[str, Any],
    redirect_uri: str = "http://127.0.0.1:8765/callback",
    redirect_handler: Any = _not_interactive,
    callback_handler: Any = _no_callback,
) -> OAuthClientProvider:
    auth = connector.get("auth") or {}
    service = auth.get("keychain_service")
    if not service:
        raise ConnectorGatewayError("{} has no OAuth Keychain service".format(connector["id"]))
    metadata = OAuthClientMetadata(
        redirect_uris=[redirect_uri],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        client_name="Rally connector gateway",
        software_id="https://github.com/Agent9AI/rally",
        software_version="0.1.0",
    )
    return OAuthClientProvider(
        connector["endpoint"],
        metadata,
        KeychainTokenStorage(service),
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )


@asynccontextmanager
async def remote_session(
    connector: dict[str, Any], oauth_handlers: tuple[Any, Any, str] | None = None
) -> AsyncIterator[ClientSession]:
    endpoint = connector.get("endpoint")
    if not endpoint:
        raise ConnectorGatewayError(
            "{} needs an endpoint before it can connect".format(connector.get("id", "connector"))
        )
    auth = connector.get("auth") or {}
    auth_type = auth.get("type")
    client_kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(30.0, read=90.0),
        "follow_redirects": True,
    }
    if auth_type == "google_adc":
        client_kwargs["headers"] = await asyncio.to_thread(_google_headers, auth)
    elif auth_type == "oauth_2_1":
        if oauth_handlers:
            redirect_handler, callback_handler, redirect_uri = oauth_handlers
            client_kwargs["auth"] = oauth_provider(
                connector, redirect_uri, redirect_handler, callback_handler
            )
        else:
            client_kwargs["auth"] = oauth_provider(connector)
    else:
        raise ConnectorGatewayError("unsupported auth type for {}".format(connector["id"]))

    try:
        async with (
            httpx.AsyncClient(**client_kwargs) as http_client,
            streamable_http_client(endpoint, http_client=http_client, terminate_on_close=True) as (
                read_stream,
                write_stream,
                _,
            ),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            yield session
    except ConnectorGatewayError:
        raise
    except Exception as exc:
        raise ConnectorGatewayError(
            "{} connection failed: {}".format(connector["id"], str(exc)[:500])
        ) from exc


async def discover_tools(
    connector: dict[str, Any], oauth_handlers: tuple[Any, Any, str] | None = None
) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    cursor: str | None = None
    async with remote_session(connector, oauth_handlers) as session:
        while True:
            result = await session.list_tools(cursor=cursor)
            tools.extend(
                [
                    {
                        "name": tool.name,
                        "title": tool.title,
                        "description": tool.description,
                        "input_schema": tool.inputSchema,
                    }
                    for tool in result.tools
                ]
            )
            cursor = result.nextCursor
            if not cursor:
                break
    return tools


def _json_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _receipt(authority: dict[str, Any], value: dict[str, Any]) -> None:
    path = authority.get("receipt_path")
    if not path:
        return
    record = {
        "at": datetime.now(UTC).isoformat(),
        "run_id": authority.get("run_id"),
        "actor": os.environ.get("RALLY_ACTOR", "unknown"),
        **value,
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def public_connector_list(authority: dict[str, Any]) -> dict[str, Any]:
    return {
        "default_decision": authority["default_decision"],
        "connectors": [
            {
                "id": item["id"],
                "name": item["name"],
                "ready": bool(item.get("endpoint")),
                "allowed_tools": sorted(
                    name
                    for name, rule in (item.get("tool_policy") or {}).items()
                    if rule.get("risk") == "read"
                ),
            }
            for item in authority.get("connectors") or []
        ],
    }


async def call_allowed_tool(
    authority: dict[str, Any],
    connector_id: str,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    connector = connector_by_id(authority, connector_id)
    rule = (connector.get("tool_policy") or {}).get(tool_name)
    if not rule or rule.get("risk") == "deny":
        _receipt(
            authority,
            {
                "connector_id": connector_id,
                "tool": tool_name,
                "risk": (rule or {}).get("risk", "deny"),
                "decision": "denied",
                "arguments_sha256": _json_hash(arguments or {}),
                "reason": "not_allowlisted",
            },
        )
        raise ConnectorGatewayError(
            f"{connector_id}.{tool_name} is not on this run's tool allowlist"
        )
    risk = rule.get("risk")
    if risk in {"verify_first", "human_approval"}:
        _receipt(
            authority,
            {
                "connector_id": connector_id,
                "tool": tool_name,
                "risk": risk,
                "decision": "denied",
                "arguments_sha256": _json_hash(arguments or {}),
                "reason": "pre_execution_gate_unavailable",
            },
        )
        raise ConnectorGatewayError(
            f"{connector_id}.{tool_name} requires a pre-execution gate that is not enabled"
        )
    started = time.monotonic()
    args = arguments or {}
    try:
        async with remote_session(connector) as session:
            result = await session.call_tool(tool_name, args)
        payload = result.model_dump(mode="json", by_alias=True, exclude_none=True)
        _receipt(
            authority,
            {
                "connector_id": connector_id,
                "tool": tool_name,
                "risk": risk,
                "decision": "allowed",
                "arguments_sha256": _json_hash(args),
                "result_sha256": _json_hash(payload),
                "result_is_error": bool(result.isError),
                "duration_ms": round((time.monotonic() - started) * 1000),
            },
        )
        return payload
    except Exception as exc:
        _receipt(
            authority,
            {
                "connector_id": connector_id,
                "tool": tool_name,
                "risk": risk,
                "decision": "failed",
                "arguments_sha256": _json_hash(args),
                "error_type": type(exc).__name__,
                "duration_ms": round((time.monotonic() - started) * 1000),
            },
        )
        raise


mcp = FastMCP(
    "Rally connectors",
    instructions=(
        "A run-scoped, deny-by-default gateway. Discover enabled connectors and "
        "their remote tools, then call only tools explicitly allowed by Rally policy."
    ),
)


@mcp.tool(name="rally_connector_list")
def gateway_list() -> dict[str, Any]:
    """List connectors and allowed tools frozen into this Rally run."""
    return public_connector_list(load_authority())


@mcp.tool(name="rally_connector_tools")
async def gateway_tools(connector_id: str) -> dict[str, Any]:
    """Discover a run-enabled connector's live MCP tools without executing one."""
    authority = load_authority()
    connector = connector_by_id(authority, connector_id)
    tools = await discover_tools(connector)
    allowed = connector.get("tool_policy") or {}
    return {
        "connector_id": connector_id,
        "tools": [
            {
                **tool,
                "allowed": (allowed.get(tool["name"]) or {}).get("risk") == "read",
                "risk": (allowed.get(tool["name"]) or {}).get("risk", "deny"),
            }
            for tool in tools
        ],
    }


@mcp.tool(name="rally_connector_call")
async def gateway_call(
    connector_id: str, tool_name: str, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Call one explicitly allowlisted connector tool and write a content-free receipt."""
    return await call_allowed_tool(load_authority(), connector_id, tool_name, arguments)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", help="authority file; defaults to RALLY_CONNECTOR_POLICY")
    parser.add_argument(
        "--inspect", action="store_true", help="print secret-free authority summary"
    )
    args = parser.parse_args()
    if args.policy:
        os.environ["RALLY_CONNECTOR_POLICY"] = os.path.abspath(args.policy)
    if args.inspect:
        print(json.dumps(public_connector_list(load_authority()), indent=2))
        return 0
    mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
