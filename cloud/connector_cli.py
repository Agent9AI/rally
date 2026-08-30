"""Administrator workflow for Rally's connector gateway."""

from __future__ import annotations

import argparse
import asyncio
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

from connector_gateway import ConnectorGatewayError, discover_tools

DEFAULT_CONFIG = os.path.join(ROOT, "config", "rally.json")


def load_config(path: str) -> dict[str, Any]:
    with open(path) as handle:
        return json.load(handle)


def print_catalog(cfg: dict[str, Any], subject: str) -> int:
    settings = connectors.installation_settings(cfg, subject)
    print(f"Rally connector catalog · profile {settings['profile_id']}")
    print(f"{'CONNECTOR':18} {'RUNTIME':13} {'ENABLED':10} ENDPOINT")
    for item in connectors.catalog_rows(cfg, subject):
        endpoint = item.get("configured_endpoint") or "setup required"
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
    cfg: dict[str, Any], connector_id: str, endpoint: str, tools: list[str],
    subject: str, credential_file: str = "",
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
    if tools:
        override["tools"] = _parse_tool(tools)
    overrides[connector_id] = override
    path = connectors.save_local_settings(cfg, enabled, overrides, subject)
    resolved = connectors.configured_connector(cfg, connector_id, subject)
    print(f"enabled {connector_id} for {settings['profile_id']} in {path}")
    if not resolved.get("endpoint"):
        print("next: provide its tenant MCP endpoint with --endpoint")
    if not (override.get("tools") or {}):
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
    if not connector.get("endpoint"):
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
    disable = sub.add_parser("disable", help="remove connector authority from future runs")
    disable.add_argument("connector_id")
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
                args.profile, args.credential_file,
            )
        if args.command == "disable":
            return disable_connector(cfg, args.connector_id, args.profile)
        return asyncio.run(inspect_connector(
            cfg, args.connector_id, args.command == "auth", args.profile
        ))
    except (connectors.ConnectorConfigError, ConnectorGatewayError, OSError, ValueError) as exc:
        print(f"connector setup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
