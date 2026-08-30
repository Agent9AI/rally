import copy
import json
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import connectors as C


def config(local_path, enabled=None, overrides=None, registry=None):
    return {
        "connectors": {
            "registry": registry or os.path.join(ROOT, "config", "connectors.json"),
            "local": local_path,
            "enabled": enabled or [],
            "overrides": overrides or {},
        }
    }


class TestConnectorAuthority(unittest.TestCase):
    def test_catalog_has_ten_honest_gateway_adapters(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = {row["id"]: row for row in C.catalog_rows(config(os.path.join(directory, "x")))}
        self.assertEqual(len(rows), 10)
        self.assertEqual(
            {name for name, item in rows.items() if item["runtime"] == "gateway"},
            set(rows),
        )
        self.assertFalse(rows["google-workspace"]["configured_endpoint"])
        self.assertEqual(
            rows["google-workspace"]["dispatch"]["services"],
            C.GOOGLE_WORKSPACE_ENDPOINTS,
        )
        self.assertEqual(rows["slack"]["configured_endpoint"],
                         "https://mcp.slack.com/mcp")
        self.assertEqual(rows["github"]["configured_endpoint"],
                         "https://api.githubcopilot.com/mcp")
        self.assertEqual(rows["cloudflare"]["configured_endpoint"],
                         "https://observability.mcp.cloudflare.com/mcp")
        self.assertFalse(rows["n8n"]["configured_endpoint"])
        self.assertEqual(rows["stripe"]["configured_endpoint"],
                         "https://mcp.stripe.com")
        self.assertEqual(rows["bigquery"]["configured_endpoint"],
                         "https://bigquery.googleapis.com/mcp")
        self.assertEqual(rows["atlassian"]["configured_endpoint"],
                         "https://mcp.atlassian.com/v1/mcp/authv2")
        self.assertFalse(rows["salesforce"]["configured_endpoint"])
        self.assertEqual(
            rows["salesforce"]["auth"]["registration"], "pre_registered"
        )
        self.assertEqual(
            rows["salesforce"]["auth"]["client_type"],
            "public_or_confidential",
        )
        self.assertFalse(
            rows["salesforce"]["auth"]["dynamic_client_registration"]
        )
        self.assertEqual(rows["hyperagent"]["configured_endpoint"],
                         "https://hyperagent.com/api/mcp")

    def test_disabled_installation_has_zero_connector_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            authority = C.authority_snapshot(
                config(os.path.join(directory, "x")), "r-test",
                os.path.join(directory, "receipts.jsonl"),
            )
        self.assertEqual(authority["default_decision"], "deny")
        self.assertEqual(authority["connectors"], [])
        self.assertTrue(authority["policy"]["require_explicit_tool_allowlist"])

    def test_enabled_authority_is_secret_free_and_tool_specific(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = config(
                os.path.join(directory, "x"), ["bigquery"],
                {"bigquery": {"tools": {"execute_sql": "read"}}},
            )
            authority = C.authority_snapshot(
                cfg, "r-test", os.path.join(directory, "receipts.jsonl")
            )
        connector = authority["connectors"][0]
        self.assertEqual(connector["id"], "bigquery")
        self.assertEqual(connector["tool_policy"], {"execute_sql": {"risk": "read"}})
        rendered = json.dumps(authority).lower()
        self.assertNotIn("access_token", rendered)
        self.assertNotIn("client_secret", rendered)

    def test_argument_constraints_survive_into_immutable_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = config(
                os.path.join(directory, "x"), ["bigquery"],
                {"bigquery": {"tools": {"execute_sql_readonly": {
                    "risk": "read",
                    "constraints": {
                        "arguments": {
                            "project_id": {
                                "required": True,
                                "allowed_values": ["approved-project"],
                            }
                        },
                        "max_result_bytes": 65536,
                    },
                }}}},
            )
            authority = C.authority_snapshot(
                cfg, "r-test", os.path.join(directory, "receipts.jsonl")
            )
        rule = authority["connectors"][0]["tool_policy"]["execute_sql_readonly"]
        self.assertEqual(rule["constraints"]["arguments"]["project_id"]
                         ["allowed_values"], ["approved-project"])
        self.assertEqual(rule["constraints"]["max_result_bytes"], 65536)

    def test_unknown_connectors_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(C.ConnectorConfigError):
                C.authority_snapshot(
                    config(os.path.join(directory, "x"), ["missing"]),
                    "r-test", os.path.join(directory, "receipts.jsonl"),
                )

    def test_promoted_connectors_freeze_dispatch_auth_and_safety_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            authority = C.authority_snapshot(
                config(
                    os.path.join(directory, "x"),
                    ["google-workspace", "slack", "github"],
                ),
                "r-test",
                os.path.join(directory, "receipts.jsonl"),
            )
        connectors = {item["id"]: item for item in authority["connectors"]}
        workspace = connectors["google-workspace"]
        self.assertEqual(workspace["endpoint"], "")
        self.assertFalse(workspace["endpoint_required"])
        self.assertEqual(workspace["dispatch"], {
            "strategy": "tool_prefix",
            "separator": ".",
            "services": C.GOOGLE_WORKSPACE_ENDPOINTS,
        })
        self.assertEqual(len(workspace["dispatch"]["services"]), 8)

        slack = connectors["slack"]
        self.assertEqual(slack["endpoint"], "https://mcp.slack.com/mcp")
        self.assertEqual(slack["auth"]["registration"], "pre_registered")
        self.assertEqual(slack["auth"]["client_type"], "confidential")
        self.assertFalse(slack["auth"]["dynamic_client_registration"])
        self.assertEqual(
            slack["auth"]["scopes"],
            [
                "search:read.public",
                "search:read.files",
                "search:read.users",
                "files:read",
                "channels:history",
                "channels:read",
                "users:read",
                "users:read.email",
            ],
        )

        self.assertEqual(workspace["auth"]["scopes"], C.GOOGLE_WORKSPACE_READ_SCOPES)
        for scope in workspace["auth"]["scopes"]:
            self.assertNotIn(".compose", scope)
            self.assertNotIn(".create", scope)

        github = connectors["github"]
        self.assertEqual(github["endpoint"], "https://api.githubcopilot.com/mcp")
        self.assertEqual(github["auth"]["type"], "external_bearer")
        self.assertEqual(github["auth"]["toolsets"], C.GITHUB_TOOLSETS)
        self.assertNotIn("request_headers", github)

        for connector in connectors.values():
            self.assertEqual(connector["auth"]["authorization_status"],
                             "customer_required")
            self.assertTrue(connector["auth"]["keychain_service"].endswith(
                authority["credential_profile"]
            ))
        self.assertNotIn('"authorization_status": "complete"', json.dumps(authority))

    def test_promoted_connector_endpoints_cannot_be_overridden(self):
        with tempfile.TemporaryDirectory() as directory:
            for connector_id in ("google-workspace", "slack", "github"):
                with self.subTest(connector_id=connector_id):
                    cfg = config(
                        os.path.join(directory, "x"),
                        [connector_id],
                        {connector_id: {"endpoint": "https://attacker.example/mcp"}},
                    )
                    with self.assertRaisesRegex(C.ConnectorConfigError,
                                                "cannot be overridden"):
                        C.authority_snapshot(
                            cfg, "r-test", os.path.join(directory, "receipts.jsonl")
                        )

    def test_promoted_catalog_metadata_fails_closed_on_drift(self):
        with open(os.path.join(ROOT, "config", "connectors.json")) as handle:
            original = json.load(handle)

        def connector(catalog, connector_id):
            return next(item for item in catalog["connectors"]
                        if item["id"] == connector_id)

        cases = []
        missing_service = copy.deepcopy(original)
        del connector(missing_service, "google-workspace")["dispatch"]["services"]["people"]
        cases.append(("missing workspace service", missing_service))

        unlisted_host = copy.deepcopy(original)
        connector(unlisted_host, "google-workspace")["allowed_endpoint_hosts"].remove(
            "people.googleapis.com"
        )
        cases.append(("workspace host allowlist drift", unlisted_host))

        wrong_path = copy.deepcopy(original)
        connector(wrong_path, "google-workspace")["allowed_endpoint_exact_paths"] = ["/mcp"]
        cases.append(("workspace path allowlist drift", wrong_path))

        dynamic_slack = copy.deepcopy(original)
        connector(dynamic_slack, "slack")["auth"]["dynamic_client_registration"] = True
        cases.append(("Slack dynamic registration", dynamic_slack))

        broad_google_scope = copy.deepcopy(original)
        connector(broad_google_scope, "google-workspace")["auth"]["scopes"].append(
            "https://www.googleapis.com/auth/gmail.compose"
        )
        cases.append(("Google write scope", broad_google_scope))

        broad_github = copy.deepcopy(original)
        connector(broad_github, "github")["auth"]["toolsets"].append("actions")
        cases.append(("GitHub toolset drift", broad_github))

        redirected_github = copy.deepcopy(original)
        connector(redirected_github, "github")["endpoint"] = "https://example.com/mcp"
        cases.append(("GitHub endpoint drift", redirected_github))

        with tempfile.TemporaryDirectory() as directory:
            registry = os.path.join(directory, "connectors.json")
            for label, catalog in cases:
                with self.subTest(case=label):
                    with open(registry, "w") as handle:
                        json.dump(catalog, handle)
                    with self.assertRaises(C.ConnectorConfigError):
                        C.catalog_rows(config(os.path.join(directory, "x"), registry=registry))

    def test_run_files_are_private_and_point_to_one_gateway(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = C.prepare_run(
                "r-test", directory, config(os.path.join(directory, "local.json"))
            )
            for key in ("policy_path", "mcp_config_path"):
                mode = stat.S_IMODE(os.stat(summary[key]).st_mode)
                self.assertEqual(mode, 0o600)
            with open(summary["mcp_config_path"]) as handle:
                mcp_config = json.load(handle)
            self.assertEqual(list(mcp_config["mcpServers"]), ["rally-connectors"])
            self.assertTrue(
                mcp_config["mcpServers"]["rally-connectors"]["command"].endswith(
                    "/bin/rally-connectors"
                )
            )
            self.assertEqual(
                summary["approval_path"],
                os.path.join(directory, "connector-approvals.json"),
            )
            with open(summary["policy_path"]) as handle:
                authority = json.load(handle)
            self.assertTrue(authority["policy"]["human_approval_tools_enabled"])
            self.assertEqual(authority["approval_path"], summary["approval_path"])
            enabled_cfg = config(
                os.path.join(directory, "missing-local.json"), ["bigquery"]
            )
            enabled_cfg["agents"] = {"agy": {"bin": "agy"}}
            isolated = mock.Mock(returncode=0, stdout=(
                "NAME TYPE STATUS COMMAND/URL\n"
                "rally-connectors stdio enabled /rally/bin/rally-connectors\n"
            ))
            with mock.patch.object(C.subprocess, "run", return_value=isolated):
                C.assert_worker_isolation(enabled_cfg)
            exposed = mock.Mock(returncode=0, stdout=(
                isolated.stdout + "figma http enabled https://mcp.figma.com/mcp\n"
            ))
            with mock.patch.object(C.subprocess, "run", return_value=exposed):
                with self.assertRaises(C.ConnectorConfigError):
                    C.assert_worker_isolation(enabled_cfg)

    def test_connection_policy_and_oauth_storage_are_isolated_per_user(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = config(os.path.join(directory, "local.json"))
            C.save_local_settings(
                cfg, ["atlassian"],
                {"atlassian": {"tools": {"search": "read"}}},
                "alice@example.com",
            )
            C.save_local_settings(
                cfg, ["salesforce"],
                {"salesforce": {"endpoint":
                    "https://api.salesforce.com/platform/mcp/v1/platform/sobject-reads"}},
                "bob@example.com",
            )

            alice = C.installation_settings(cfg, "alice@example.com")
            bob = C.installation_settings(cfg, "bob@example.com")
            self.assertEqual(alice["enabled"], ["atlassian"])
            self.assertEqual(bob["enabled"], ["salesforce"])
            self.assertNotEqual(alice["profile_id"], bob["profile_id"])
            atlassian = C.configured_connector(cfg, "atlassian", "alice@example.com")
            self.assertTrue(atlassian["auth"]["keychain_service"].endswith(
                alice["profile_id"]
            ))
            hyperagent = C.configured_connector(cfg, "hyperagent", "alice@example.com")
            self.assertTrue(hyperagent["auth"]["keychain_service"].endswith(
                alice["profile_id"]
            ))
            with open(alice["local_path"]) as handle:
                raw = handle.read()
            self.assertNotIn("alice@example.com", raw)
            self.assertNotIn("bob@example.com", raw)

    def test_provider_endpoints_cannot_be_redirected_into_arbitrary_networks(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = config(os.path.join(directory, "local.json"))
            C.save_local_settings(
                cfg, ["bigquery"],
                {"bigquery": {"endpoint": "https://attacker.example/mcp"}},
            )
            with self.assertRaisesRegex(C.ConnectorConfigError, "cannot be overridden"):
                C.authority_snapshot(
                    cfg, "r-test", os.path.join(directory, "receipts.jsonl")
                )
            C.save_local_settings(
                cfg, ["salesforce"],
                {"salesforce": {"endpoint": "https://127.0.0.1/mcp"}},
            )
            with self.assertRaisesRegex(C.ConnectorConfigError, "provider allowlist"):
                C.authority_snapshot(
                    cfg, "r-test", os.path.join(directory, "receipts.jsonl")
                )

    def test_n8n_cloud_endpoint_is_tenant_scoped_and_path_pinned(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = config(os.path.join(directory, "local.json"))
            good = "https://agent9.app.n8n.cloud/mcp-server/http"
            C.save_local_settings(cfg, ["n8n"], {"n8n": {"endpoint": good}})
            authority = C.authority_snapshot(
                cfg, "r-test", os.path.join(directory, "receipts.jsonl")
            )
            self.assertEqual(authority["connectors"][0]["endpoint"], good)
            for bad in (
                "https://app.n8n.cloud/mcp-server/http",
                "https://agent9.app.n8n.cloud/admin",
                "https://agent9.app.n8n.cloud.evil.example/mcp-server/http",
            ):
                with self.subTest(endpoint=bad):
                    C.save_local_settings(cfg, ["n8n"], {"n8n": {"endpoint": bad}})
                    with self.assertRaises(C.ConnectorConfigError):
                        C.authority_snapshot(
                            cfg, "r-test", os.path.join(directory, "receipts.jsonl")
                        )

    def test_nonlocal_bigquery_profile_refuses_shared_adc(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = config(os.path.join(directory, "local.json"))
            C.save_local_settings(cfg, ["bigquery"], {}, "alice@example.com")
            with self.assertRaisesRegex(C.ConnectorConfigError, "own Google ADC"):
                C.authority_snapshot(
                    cfg, "r-test", os.path.join(directory, "receipts.jsonl"),
                    "alice@example.com",
                )


if __name__ == "__main__":
    unittest.main()
