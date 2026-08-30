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


def config(local_path, enabled=None, overrides=None):
    return {
        "connectors": {
            "registry": os.path.join(ROOT, "config", "connectors.json"),
            "local": local_path,
            "enabled": enabled or [],
            "overrides": overrides or {},
        }
    }


class TestConnectorAuthority(unittest.TestCase):
    def test_catalog_has_ten_honestly_staged_connectors(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = {row["id"]: row for row in C.catalog_rows(config(os.path.join(directory, "x")))}
        self.assertEqual(len(rows), 10)
        self.assertEqual(
            {name for name, item in rows.items() if item["runtime"] == "gateway"},
            {"bigquery", "atlassian", "salesforce", "hyperagent"},
        )
        self.assertEqual(rows["bigquery"]["configured_endpoint"],
                         "https://bigquery.googleapis.com/mcp")
        self.assertEqual(rows["atlassian"]["configured_endpoint"],
                         "https://mcp.atlassian.com/v1/mcp")
        self.assertFalse(rows["salesforce"]["configured_endpoint"])
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

    def test_unknown_and_roadmap_connectors_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            for connector_id in ("missing", "slack"):
                with self.subTest(connector_id=connector_id):
                    with self.assertRaises(C.ConnectorConfigError):
                        C.authority_snapshot(
                            config(os.path.join(directory, "x"), [connector_id]),
                            "r-test", os.path.join(directory, "receipts.jsonl"),
                        )

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
                {"salesforce": {"endpoint": "https://salesforce.example/mcp"}},
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
