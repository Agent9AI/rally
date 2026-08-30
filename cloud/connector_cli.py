"""Administrator workflow for Rally's connector gateway."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import subprocess
import sys
import urllib.parse
import webbrowser
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import connectors

from connector_approvals import (
    ApprovalError,
    get_for_review,
    list_public,
)
from connector_approvals import (
    approve as approve_request,
)
from connector_credentials import (
    ConnectorCredentialError,
    OAuthClientCredentials,
    OAuthTokenMaterial,
    ProfileKeychainStore,
    delete_profile_credentials,
)
from connector_gateway import ConnectorGatewayError, discover_tools
from connector_presets import ConnectorPresetError, build_connector_preset

DEFAULT_CONFIG = os.path.join(ROOT, "config", "rally.json")


def _credential_store(
    cfg: dict[str, Any], connector_id: str, subject: str
) -> ProfileKeychainStore:
    connector = connectors.configured_connector(cfg, connector_id, subject)
    service = (connector.get("auth") or {}).get("keychain_service")
    if not service:
        raise connectors.ConnectorConfigError(
            f"{connector_id} does not use profile Keychain credentials"
        )
    return ProfileKeychainStore.from_namespaced_service(service)


def register_oauth_client(
    cfg: dict[str, Any], connector_id: str, subject: str, public_client: bool
) -> int:
    connector = connectors.configured_connector(cfg, connector_id, subject)
    if (connector.get("auth") or {}).get("registration") != "pre_registered":
        raise connectors.ConnectorConfigError(
            f"{connector_id} does not require a pre-registered OAuth client"
        )
    client_id = input("OAuth client ID: ").strip()
    client_secret = None if public_client else getpass.getpass("OAuth client secret: ")
    _credential_store(cfg, connector_id, subject).save_client(
        OAuthClientCredentials(client_id, client_secret or None)
    )
    print(f"stored {connector_id} OAuth client registration for this isolated profile")
    return 0


def import_bearer_token(cfg: dict[str, Any], connector_id: str, subject: str) -> int:
    connector = connectors.configured_connector(cfg, connector_id, subject)
    if (connector.get("auth") or {}).get("type") != "external_bearer":
        raise connectors.ConnectorConfigError(
            f"{connector_id} does not accept an externally obtained bearer token"
        )
    token = getpass.getpass("Bearer token (stored only in macOS Keychain): ")
    _credential_store(cfg, connector_id, subject).save_tokens(OAuthTokenMaterial(token))
    print(f"stored {connector_id} bearer token for this isolated profile")
    return 0


def disconnect_credentials(cfg: dict[str, Any], connector_id: str, subject: str) -> int:
    deleted = delete_profile_credentials(_credential_store(cfg, connector_id, subject))
    print(
        f"disconnected {connector_id} for this profile"
        if deleted
        else f"{connector_id} had no stored profile credentials"
    )
    return 0


def _approval_path(run_dir: str) -> str:
    policy_path = os.path.join(os.path.abspath(run_dir), "connector-authority.json")
    try:
        with open(policy_path) as handle:
            authority = json.load(handle)
    except (OSError, ValueError) as exc:
        raise ConnectorGatewayError(f"cannot read run connector authority: {exc}") from exc
    path = authority.get("approval_path")
    if not path:
        raise ConnectorGatewayError("this run has no human-approval ledger")
    return str(path)


def list_approvals(run_dir: str, status: str | None) -> int:
    print(json.dumps(list_public(_approval_path(run_dir), status=status), indent=2))
    return 0


def review_approval(run_dir: str, approval_id: str) -> int:
    print(json.dumps(get_for_review(_approval_path(run_dir), approval_id), indent=2))
    return 0


def approve(run_dir: str, approval_id: str, human_identity: str) -> int:
    print(
        json.dumps(
            approve_request(
                _approval_path(run_dir),
                approval_id,
                human_identity=human_identity,
            ),
            indent=2,
        )
    )
    return 0


def load_config(path: str) -> dict[str, Any]:
    with open(path) as handle:
        return json.load(handle)


def print_catalog(cfg: dict[str, Any], subject: str) -> int:
    settings = connectors.installation_settings(cfg, subject)
    print(f"Rally connector catalog · profile {settings['profile_id']}")
    print(f"{'CONNECTOR':18} {'RUNTIME':13} {'ENABLED':10} ENDPOINT")
    for item in connectors.catalog_rows(cfg, subject):
        endpoint = item.get("configured_endpoint")
        if not endpoint and item.get("dispatch"):
            endpoint = f"{len(item['dispatch']['services'])} pinned services"
        endpoint = endpoint or "setup required"
        enabled = "yes" if item["enabled"] else "no"
        print(f"{item['id']:18} {item['runtime']:13} {enabled:10} {endpoint}")
    print("\nCredentials are held by Google ADC or macOS Keychain, never these files.")
    return 0


def _parse_tool(values: list[str]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for value in values:
        name, separator, risk = value.partition("=")
        if not separator:
            raise connectors.ConnectorConfigError(
                "tool policy must be NAME=read|verify_first|human_approval"
            )
        if risk not in connectors.RISK_CLASSES - {"deny"}:
            raise connectors.ConnectorConfigError(f"invalid risk class: {risk}")
        result[name] = {"risk": risk}
    return result


def enable_connector(
    cfg: dict[str, Any],
    connector_id: str,
    endpoint: str,
    tools: list[str],
    subject: str,
    credential_file: str = "",
    preset: str = "",
    workflow_ids: list[str] | None = None,
) -> int:
    item = connectors.configured_connector(cfg, connector_id, subject)
    if item["runtime"] != "gateway":
        raise connectors.ConnectorConfigError(
            f"{connector_id} is still a researched roadmap path, not a runnable gateway"
        )
    settings = connectors.installation_settings(cfg, subject)
    enabled = set(settings["enabled"])
    enabled.add(connector_id)
    overrides = settings["overrides"]
    override = dict(overrides.get(connector_id) or {})
    if endpoint:
        override["endpoint"] = endpoint
    if credential_file:
        override["credential_file"] = os.path.abspath(os.path.expanduser(credential_file))
    if preset and tools:
        raise connectors.ConnectorConfigError("use either --preset or --tool, not both")
    if preset:
        override["tools"] = build_connector_preset(
            connector_id,
            preset,
            allowed_workflow_ids=workflow_ids,
        )
    elif tools:
        override["tools"] = _parse_tool(tools)
    overrides[connector_id] = override
    path = connectors.save_local_settings(cfg, enabled, overrides, subject)
    resolved = connectors.configured_connector(cfg, connector_id, subject)
    print(f"enabled {connector_id} for {settings['profile_id']} in {path}")
    if not resolved.get("endpoint") and not resolved.get("dispatch"):
        print("next: provide its tenant MCP endpoint with --endpoint")
    if preset:
        print(f"policy preset: {preset} ({len(override['tools'])} exact tools)")
    elif not (override.get("tools") or {}):
        print("discovery only: no remote tool can execute until --tool allowlists are added")
    return 0


def disable_connector(cfg: dict[str, Any], connector_id: str, subject: str) -> int:
    connectors.configured_connector(cfg, connector_id, subject)
    settings = connectors.installation_settings(cfg, subject)
    enabled = set(settings["enabled"])
    enabled.discard(connector_id)
    path = connectors.save_local_settings(
        cfg, enabled, settings["overrides"], subject
    )
    print(
        f"disabled {connector_id} for {settings['profile_id']} in {path}; "
        "that profile's stored OAuth credentials were not deleted"
    )
    return 0


def install_gateway() -> int:
    command = os.path.join(ROOT, "bin", "rally-connectors")
    result = subprocess.run(
        ["agy", "mcp", "add", "rally-connectors", command],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode:
        return result.returncode
    print("Antigravity now launches the same run-scoped Rally gateway as Claude and Codex.")
    return 0


async def _interactive_oauth(connector: dict[str, Any]) -> list[dict[str, Any]]:
    loop = asyncio.get_running_loop()
    callback: asyncio.Future[tuple[str, str | None]] = loop.create_future()

    async def receive(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = (await reader.readline()).decode(errors="replace").strip()
            target = request_line.split(" ", 2)[1]
            while await reader.readline() not in (b"\r\n", b"\n", b""):
                pass
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(target).query)
            if query.get("error"):
                raise ConnectorGatewayError("OAuth provider returned {}".format(query["error"][0]))
            code = (query.get("code") or [""])[0]
            state = (query.get("state") or [None])[0]
            if not callback.done():
                callback.set_result((code, state))
            body = (
                b"<!doctype html><title>Rally connected</title>"
                b"<style>body{font:18px system-ui;max-width:620px;margin:12vh auto;padding:24px;"
                b"color:#10233f}b{color:#246bfd}</style>"
                b"<h1><b>Rally connected.</b></h1><p>You can close this tab and return to the terminal.</p>"
            )
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
                + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                + body
            )
            await writer.drain()
        except (ConnectorGatewayError, IndexError, OSError, UnicodeError, ValueError) as exc:
            if not callback.done():
                callback.set_exception(exc)
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(receive, "127.0.0.1", 8765)
    redirect_uri = "http://127.0.0.1:8765/callback"

    async def redirect(url: str) -> None:
        print(f"Open this authorization URL if your browser does not open:\n{url}\n")
        webbrowser.open(url)

    async def callback_handler() -> tuple[str, str | None]:
        return await asyncio.wait_for(callback, timeout=300)

    async with server:
        return await discover_tools(
            connector, oauth_handlers=(redirect, callback_handler, redirect_uri)
        )


async def inspect_connector(
    cfg: dict[str, Any], connector_id: str, interactive: bool, subject: str
) -> int:
    connector = connectors.configured_connector(cfg, connector_id, subject)
    if connector["runtime"] != "gateway":
        raise connectors.ConnectorConfigError(
            f"{connector_id} is catalogued but its gateway adapter is not shipped"
        )
    if not connector.get("endpoint") and not connector.get("dispatch"):
        raise connectors.ConnectorConfigError(
            f"{connector_id} needs a tenant MCP endpoint; use connectors enable {connector_id} --endpoint URL"
        )
    if connector.get("auth", {}).get("type") == "google_adc" and interactive:
        print(
            "BigQuery uses Google Application Default Credentials; no Rally OAuth token is stored."
        )
    tools = (
        await _interactive_oauth(connector)
        if interactive and connector.get("auth", {}).get("type") == "oauth_2_1"
        else await discover_tools(connector)
    )
    print(f"{connector['name']} answered with {len(tools)} MCP tool(s):")
    allowed = connector.get("tool_policy") or {}
    for tool in tools:
        marker = (
            "allowed:{}".format(allowed[tool["name"]]["risk"])
            if tool["name"] in allowed
            else "denied"
        )
        print(f"  {tool['name']:48} {marker}")
    if not allowed:
        print("No calls are allowed yet. Re-run enable with --tool NAME=read after review.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rally connectors")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument(
        "--profile",
        default=os.environ.get("RALLY_CONNECTOR_SUBJECT", "local"),
        help="commissioner identity whose isolated connection profile is managed",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="show catalog and installation state")
    sub.add_parser("install", help="register Rally's gateway with Antigravity")
    for command, help_text in (
        ("auth", "complete OAuth and prove live discovery"),
        ("discover", "list live remote tools using existing credentials"),
        ("doctor", "prove authentication, endpoint, and tool discovery"),
    ):
        child = sub.add_parser(command, help=help_text)
        child.add_argument("connector_id")
    enable = sub.add_parser("enable", help="enable a connector with an explicit tool policy")
    enable.add_argument("connector_id")
    enable.add_argument("--endpoint", default="")
    enable.add_argument(
        "--credential-file", default="",
        help="profile-specific Google ADC file (required for non-local BigQuery profiles)",
    )
    enable.add_argument("--tool", action="append", default=[], metavar="NAME=RISK")
    enable.add_argument(
        "--preset", default="", help="provider-safe preset such as read-minimal"
    )
    enable.add_argument(
        "--workflow-id",
        action="append",
        default=[],
        help="n8n workflow ID permitted by workflow-bounded (repeatable)",
    )
    disable = sub.add_parser("disable", help="remove connector authority from future runs")
    disable.add_argument("connector_id")
    register = sub.add_parser(
        "register-client", help="store a provider-issued OAuth client registration"
    )
    register.add_argument("connector_id")
    register.add_argument(
        "--public-client", action="store_true", help="registration has no client secret"
    )
    token = sub.add_parser(
        "import-token", help="store an externally obtained bearer token without echoing it"
    )
    token.add_argument("connector_id")
    disconnect = sub.add_parser(
        "disconnect", help="delete this profile's stored connector credentials"
    )
    disconnect.add_argument("connector_id")
    approvals = sub.add_parser("approvals", help="list content-free run approvals")
    approvals.add_argument("run_dir")
    approvals.add_argument(
        "--status", choices=("pending", "approved", "consumed", "expired")
    )
    review = sub.add_parser("review", help="privately inspect one exact approval request")
    review.add_argument("run_dir")
    review.add_argument("approval_id")
    approve_command = sub.add_parser("approve", help="approve one exact request once")
    approve_command.add_argument("run_dir")
    approve_command.add_argument("approval_id")
    approve_command.add_argument("--as", dest="human_identity", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        cfg = load_config(os.path.abspath(args.config))
        if args.command == "list":
            return print_catalog(cfg, args.profile)
        if args.command == "install":
            return install_gateway()
        if args.command == "enable":
            return enable_connector(
                cfg, args.connector_id, args.endpoint, args.tool,
                args.profile, args.credential_file, args.preset, args.workflow_id,
            )
        if args.command == "disable":
            return disable_connector(cfg, args.connector_id, args.profile)
        if args.command == "register-client":
            return register_oauth_client(
                cfg, args.connector_id, args.profile, args.public_client
            )
        if args.command == "import-token":
            return import_bearer_token(cfg, args.connector_id, args.profile)
        if args.command == "disconnect":
            return disconnect_credentials(cfg, args.connector_id, args.profile)
        if args.command == "approvals":
            return list_approvals(args.run_dir, args.status)
        if args.command == "review":
            return review_approval(args.run_dir, args.approval_id)
        if args.command == "approve":
            return approve(args.run_dir, args.approval_id, args.human_identity)
        return asyncio.run(inspect_connector(
            cfg, args.connector_id, args.command == "auth", args.profile
        ))
    except (
        ApprovalError,
        ConnectorCredentialError,
        ConnectorPresetError,
        connectors.ConnectorConfigError,
        ConnectorGatewayError,
        OSError,
        ValueError,
    ) as exc:
        print(f"connector setup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
