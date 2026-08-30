"""Hosted connector activation and bounded MCP capability verification.

The committed connector catalog describes the runner-facing adapters.  This
module owns the smaller, public control-plane contract: which providers can be
authorized in a browser today, which need a customer-created credential, and
which exact HTTPS endpoint Rally is allowed to probe.
"""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import json
import re
from dataclasses import dataclass
from typing import Any, Final, Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from connector_presets import ConnectorPresetError, build_connector_preset


class HostedConnectorError(RuntimeError):
    """A connector request could not be completed without widening authority."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


AuthReadiness = Literal["oauth", "token", "provider_app"]
TokenScheme = Literal["bearer", "basic"]


@dataclass(frozen=True)
class HostedConnector:
    id: str
    name: str
    endpoint: str | None
    readiness: AuthReadiness
    docs_url: str
    setup_url: str
    safe_preset: str
    oauth_ready: bool = False
    token_ready: bool = False
    endpoint_required: bool = False
    endpoint_suffixes: tuple[str, ...] = ()
    endpoint_paths: tuple[str, ...] = ()
    oauth_hosts: tuple[str, ...] = ()
    oauth_scope: str | None = None
    credential_label: str = "Access token"
    credential_help: str = "Create the narrowest credential the provider allows."
    token_url: str | None = None
    token_endpoint: str | None = None
    token_scheme: TokenScheme = "bearer"


_CONNECTORS: Final[dict[str, HostedConnector]] = {
    "google-workspace": HostedConnector(
        id="google-workspace",
        name="Google Workspace",
        endpoint=None,
        readiness="provider_app",
        docs_url="https://developers.google.com/workspace/guides/configure-mcp-servers",
        setup_url="https://console.cloud.google.com/auth/clients",
        safe_preset="read-minimal",
        credential_label="Google OAuth client",
        credential_help="Rally must register its read-only Workspace consent client before user authorization can begin.",
    ),
    "slack": HostedConnector(
        id="slack",
        name="Slack",
        endpoint="https://mcp.slack.com/mcp",
        readiness="provider_app",
        docs_url="https://docs.slack.dev/ai/slack-mcp-server/",
        setup_url="https://api.slack.com/apps",
        safe_preset="read-minimal",
        credential_label="Slack app registration",
        credential_help="Slack requires a confidential internal or Marketplace app for hosted MCP access.",
    ),
    "github": HostedConnector(
        id="github",
        name="GitHub",
        endpoint="https://api.githubcopilot.com/mcp",
        readiness="token",
        docs_url="https://github.com/github/github-mcp-server",
        setup_url="https://github.com/settings/personal-access-tokens",
        safe_preset="read-only",
        token_ready=True,
        credential_label="Fine-grained access token",
        credential_help="Use a dedicated fine-grained token with read access only to the repositories Rally may inspect.",
        token_url="https://github.com/settings/personal-access-tokens/new",
    ),
    "cloudflare": HostedConnector(
        id="cloudflare",
        name="Cloudflare",
        endpoint="https://observability.mcp.cloudflare.com/mcp",
        readiness="oauth",
        docs_url="https://developers.cloudflare.com/agents/model-context-protocol/cloudflare/servers-for-cloudflare/",
        setup_url="https://dash.cloudflare.com/profile/api-tokens",
        safe_preset="observability",
        oauth_ready=True,
        token_ready=True,
        oauth_hosts=("observability.mcp.cloudflare.com",),
        credential_label="Cloudflare API token",
        credential_help="Use a dedicated token limited to the account and observability permissions Rally needs.",
        token_url="https://dash.cloudflare.com/profile/api-tokens",
    ),
    "n8n": HostedConnector(
        id="n8n",
        name="n8n",
        endpoint=None,
        readiness="oauth",
        docs_url="https://docs.n8n.io/connect/connect-to-n8n-mcp-server/",
        setup_url="https://docs.n8n.io/connect/connect-to-n8n-mcp-server/",
        safe_preset="workflow-bounded",
        oauth_ready=True,
        token_ready=True,
        endpoint_required=True,
        endpoint_suffixes=("app.n8n.cloud",),
        endpoint_paths=("/mcp-server/http",),
        credential_label="n8n MCP access token",
        credential_help="Copy the one-time access token from Settings → Instance-level MCP. Rally still limits execution to approved workflow IDs.",
    ),
    "stripe": HostedConnector(
        id="stripe",
        name="Stripe",
        endpoint="https://mcp.stripe.com",
        readiness="oauth",
        docs_url="https://docs.stripe.com/mcp",
        setup_url="https://dashboard.stripe.com/settings/user",
        safe_preset="read-minimal",
        oauth_ready=True,
        token_ready=True,
        oauth_hosts=("mcp.stripe.com", "access.stripe.com"),
        oauth_scope="mcp",
        credential_label="Restricted Stripe key",
        credential_help="Use a restricted key and start in a sandbox. Rally does not enable money-moving tools in its safe preset.",
        token_url="https://dashboard.stripe.com/apikeys",
    ),
    "atlassian": HostedConnector(
        id="atlassian",
        name="Atlassian",
        endpoint="https://mcp.atlassian.com/v1/mcp/authv2",
        readiness="oauth",
        docs_url="https://developer.atlassian.com/cloud/rovo-mcp/guides/getting-started/",
        setup_url="https://id.atlassian.com/manage-profile/security/api-tokens",
        safe_preset="read-minimal",
        oauth_ready=True,
        token_ready=True,
        oauth_hosts=("mcp.atlassian.com", "auth.atlassian.com"),
        oauth_scope=(
            "read:me read:account offline_access email read:jira-work "
            "search:confluence read:confluence-user read:page:confluence "
            "read:comment:confluence read:space:confluence "
            "read:component:compass read:scorecard:compass read:event:compass "
            "read:metric:compass read:all:twg"
        ),
        credential_label="Atlassian service-account key",
        credential_help="OAuth is preferred. The token fallback requires an organization-enabled service-account API key.",
        token_url="https://developer.atlassian.com/cloud/rovo-mcp/guides/configuring-authentication-via-api-token/",
        token_endpoint="https://mcp.atlassian.com/v1/mcp",
    ),
    "salesforce": HostedConnector(
        id="salesforce",
        name="Salesforce",
        endpoint=None,
        readiness="provider_app",
        docs_url="https://developer.salesforce.com/docs/platform/hosted-mcp-servers/references/reference/sobject-reads.html",
        setup_url="https://help.salesforce.com/s/articleView?id=xcloud.external_client_apps.htm&type=5",
        safe_preset="sobject-reads",
        credential_label="Salesforce External Client App",
        credential_help="A Salesforce administrator must activate an External Client App before Rally can request SObject access.",
    ),
    "hyperagent": HostedConnector(
        id="hyperagent",
        name="HyperAgent",
        endpoint="https://hyperagent.com/api/mcp",
        readiness="oauth",
        docs_url="https://www.hyperagent.com/docs/concepts/agents/invocations/mcp-server/",
        setup_url="https://hyperagent.com/settings",
        safe_preset="read-minimal",
        oauth_ready=True,
        oauth_hosts=("hyperagent.com",),
        oauth_scope="threads:read approvals:read offline_access",
        credential_label="HyperAgent OAuth",
        credential_help="HyperAgent issues the connection in its browser consent flow; there is no token to paste.",
    ),
}

_MAX_TOOLS: Final = 128
_MAX_TOOL_NAME: Final = 160
_TOOL_NAME: Final = re.compile(r"^[A-Za-z0-9_.:/-]{1,160}$")


def connector(connector_id: str) -> HostedConnector:
    try:
        return _CONNECTORS[connector_id]
    except KeyError:
        raise HostedConnectorError("connector_not_available") from None


def public_catalog() -> list[dict[str, Any]]:
    """Return non-secret activation metadata in the dashboard's fixed order."""

    return [
        {
            "id": item.id,
            "name": item.name,
            "readiness": item.readiness,
            "oauth_ready": item.oauth_ready,
            "token_ready": item.token_ready,
            "endpoint_required": item.endpoint_required,
            "docs_url": item.docs_url,
            "setup_url": item.setup_url,
            "safe_preset": item.safe_preset,
            "oauth_scope": item.oauth_scope,
            "credential_label": item.credential_label,
            "credential_help": item.credential_help,
            "token_url": item.token_url,
            "token_scheme": item.token_scheme,
        }
        for item in _CONNECTORS.values()
    ]


def normalize_workflow_ids(
    item: HostedConnector,
    values: list[str] | tuple[str, ...] | None,
) -> tuple[str, ...]:
    supplied = values or []
    if item.id != "n8n":
        if supplied:
            raise HostedConnectorError("policy_scope_not_allowed")
        return ()
    if len(supplied) > 64 or any(not isinstance(value, str) for value in supplied):
        raise HostedConnectorError("policy_scope_invalid")
    normalized = tuple(sorted({value.strip() for value in supplied if value.strip()}))
    if not normalized:
        raise HostedConnectorError("policy_configuration_required")
    if any(
        len(value) > 256 or any(ord(character) < 33 or ord(character) == 127 for character in value)
        for value in normalized
    ):
        raise HostedConnectorError("policy_scope_invalid")
    return normalized


def _canonical_https(value: str, *, allow_query: bool = False) -> tuple[str, str, str]:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError):
        raise HostedConnectorError("endpoint_invalid") from None
    host = (parsed.hostname or "").rstrip(".").casefold()
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or port not in (None, 443)
        or (parsed.query and not allow_query)
    ):
        raise HostedConnectorError("endpoint_invalid")
    canonical = urlunsplit(
        (
            "https",
            parsed.netloc,
            parsed.path or "/",
            parsed.query if allow_query else "",
            "",
        )
    )
    return host, parsed.path or "/", canonical


def resolve_endpoint(item: HostedConnector, supplied: str | None = None) -> str:
    value = (supplied or item.endpoint or "").strip()
    if not value:
        raise HostedConnectorError("endpoint_required")
    host, path, canonical = _canonical_https(value)
    if item.endpoint:
        expected_host, expected_path, expected = _canonical_https(item.endpoint)
        if host != expected_host or path != expected_path or canonical != expected:
            raise HostedConnectorError("endpoint_not_allowed")
        return expected
    suffix_match = any(
        host == suffix or host.endswith("." + suffix) for suffix in item.endpoint_suffixes
    )
    if not suffix_match or (item.endpoint_paths and path not in item.endpoint_paths):
        raise HostedConnectorError("endpoint_not_allowed")
    return canonical


def resolve_token_endpoint(item: HostedConnector, supplied: str | None = None) -> str:
    """Resolve the endpoint used by a non-interactive credential fallback."""

    if supplied or item.token_endpoint is None:
        return resolve_endpoint(item, supplied)
    _, _, canonical = _canonical_https(item.token_endpoint)
    return canonical


def validate_oauth_url(item: HostedConnector, value: str, endpoint: str) -> str:
    """Pin every OAuth discovery, registration, and token URL to its provider."""

    host, _, canonical = _canonical_https(value, allow_query=True)
    endpoint_host, _, _ = _canonical_https(endpoint)
    allowed = set(item.oauth_hosts) | {endpoint_host}
    if not any(host == candidate or host.endswith("." + candidate) for candidate in allowed):
        raise HostedConnectorError("oauth_endpoint_not_allowed")
    return canonical


def pack_secret(
    *,
    credential: str,
    endpoint: str,
    scheme: Literal["bearer", "basic"] = "bearer",
    account: str | None = None,
    allowed_workflow_ids: tuple[str, ...] = (),
) -> str:
    if (
        not credential
        or len(credential.encode("utf-8")) > 48 * 1024
        or any(ord(character) < 33 or ord(character) == 127 for character in credential)
    ):
        raise HostedConnectorError("credential_invalid")
    if scheme == "basic" and (not account or "@" not in account or len(account) > 320):
        raise HostedConnectorError("account_required")
    return json.dumps(
        {
            "schema": "rally.connection-material/v1",
            "credential": credential,
            "endpoint": endpoint,
            "scheme": scheme,
            "account": account,
            "allowed_workflow_ids": list(allowed_workflow_ids),
        },
        separators=(",", ":"),
    )


def unpack_secret(value: str) -> dict[str, str | None]:
    try:
        material = json.loads(value)
    except (TypeError, ValueError):
        raise HostedConnectorError("credential_invalid") from None
    if not isinstance(material, dict) or material.get("schema") != "rally.connection-material/v1":
        raise HostedConnectorError("credential_invalid")
    credential = material.get("credential")
    endpoint = material.get("endpoint")
    scheme = material.get("scheme")
    account = material.get("account")
    if not isinstance(credential, str) or not credential or not isinstance(endpoint, str):
        raise HostedConnectorError("credential_invalid")
    if scheme not in {"bearer", "basic"}:
        raise HostedConnectorError("credential_invalid")
    if account is not None and not isinstance(account, str):
        raise HostedConnectorError("credential_invalid")
    return {
        "credential": credential,
        "endpoint": endpoint,
        "scheme": scheme,
        "account": account,
    }


def authorization_headers(item: HostedConnector, material: dict[str, str | None]) -> dict[str, str]:
    credential = material["credential"] or ""
    if material["scheme"] == "basic":
        account = material["account"] or ""
        encoded = base64.b64encode(f"{account}:{credential}".encode()).decode("ascii")
        headers = {"Authorization": f"Basic {encoded}"}
    else:
        headers = {"Authorization": f"Bearer {credential}"}
    if item.id == "github":
        headers.update(
            {
                "X-MCP-Toolsets": "context,repos,issues,pull_requests,users",
                "X-MCP-Readonly": "true",
                "X-MCP-Lockdown": "true",
            }
        )
    return headers


class McpConnectionVerifier:
    """Prove authentication and bounded live tool discovery without calling a tool."""

    async def verify(
        self,
        item: HostedConnector,
        material: dict[str, str | None],
        *,
        allowed_workflow_ids: tuple[str, ...] = (),
    ) -> int:
        endpoint = resolve_endpoint(item, material.get("endpoint"))
        headers = authorization_headers(item, material)
        try:
            async with asyncio.timeout(35):
                async with (
                    httpx.AsyncClient(
                        headers=headers,
                        timeout=httpx.Timeout(12.0, read=20.0),
                        follow_redirects=False,
                    ) as http_client,
                    streamable_http_client(
                        endpoint,
                        http_client=http_client,
                        terminate_on_close=True,
                    ) as (read_stream, write_stream, _),
                    ClientSession(read_stream, write_stream) as session,
                ):
                    await session.initialize()
                    cursor: str | None = None
                    names: list[str] = []
                    for _ in range(4):
                        page = await session.list_tools(cursor=cursor)
                        names.extend(str(tool.name) for tool in page.tools)
                        cursor = page.nextCursor
                        if not cursor:
                            break
                        if len(names) > _MAX_TOOLS:
                            raise HostedConnectorError("capability_check_failed")
        except Exception as exc:
            # Provider bodies and exception details can contain tenant information.
            raise HostedConnectorError("verification_failed") from exc
        if not names or len(names) > _MAX_TOOLS:
            raise HostedConnectorError("capability_check_failed")
        if any(len(name) > _MAX_TOOL_NAME or not _TOOL_NAME.fullmatch(name) for name in names):
            raise HostedConnectorError("capability_check_failed")
        if len(set(names)) != len(names):
            raise HostedConnectorError("capability_check_failed")
        try:
            policy = build_connector_preset(
                item.id,
                item.safe_preset,
                allowed_workflow_ids=(allowed_workflow_ids if item.id == "n8n" else None),
            )
        except ConnectorPresetError as exc:
            code = (
                "policy_configuration_required" if item.id == "n8n" else "safe_preset_unavailable"
            )
            raise HostedConnectorError(code) from exc
        approved = set(names).intersection(policy)
        if not approved:
            raise HostedConnectorError("safe_preset_mismatch")
        return len(approved)


def make_oauth_material(
    *,
    endpoint: str,
    access_token: str,
    refresh_token: str | None,
    token_type: str,
    expires_in: int | None,
    scope: str | None,
    client_id: str,
    client_secret: str | None,
    token_endpoint: str,
    revocation_endpoint: str | None,
    allowed_workflow_ids: tuple[str, ...] = (),
) -> str:
    return json.dumps(
        {
            "schema": "rally.oauth-material/v1",
            "endpoint": endpoint,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": token_type,
            "expires_in": expires_in,
            "obtained_at": dt.datetime.now(dt.UTC).isoformat(),
            "scope": scope,
            "client_id": client_id,
            "client_secret": client_secret,
            "token_endpoint": token_endpoint,
            "revocation_endpoint": revocation_endpoint,
            "allowed_workflow_ids": list(allowed_workflow_ids),
        },
        separators=(",", ":"),
    )
