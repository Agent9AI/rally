import io
import json
import os
import sys
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import console as rally_console  # noqa: E402


def state(**changes):
    value = {
        "run_id": "r-20260829-console",
        "task": "Implement replay-safe webhook handling",
        "workdir": "/private/sensitive/path",
        "commissioned_by": "private@example.com",
        "thread_message_id": "<secret@example.com>",
        "created": "2026-08-29T12:00:00Z",
        "turn": 2,
        "actor": "claude",
        "halt": None,
        "checklist": [],
        "turns": [],
    }
    value.update(changes)
    return value


def config(enabled=False, public=False):
    return {
        "agents": {
            "claude": {"family": "anthropic", "model": "sonnet"},
            "agy": {"family": "google", "model": "gemini-3.7-flash-low"},
            "codex": {"family": "openai", "model": "gpt-5.4"},
        },
        "ingress": {
            "worker_url": "https://worker.example",
            "poll_token_keychain": "rally-poll-token",
        },
        "console": {
            "enabled": enabled,
            "public": public,
            "workspace_id": "workspace-test",
        },
    }


class ConsoleSnapshotTests(unittest.TestCase):
    def test_snapshot_excludes_private_runner_fields(self):
        payload = rally_console.build_snapshot(state(
            report=(
                "Open /private/sensitive/path/output.py for private@example.com; "
                "the model also linked [server.py]"
                "(file:///Users/terry/.agent-scratch/server.py) and "
                "/Users/another-person/unexpected/tool/output.py; raw "
                "file:///tmp/another-output.txt"
            ),
            checklist=[{
                "id": "c1", "description": "Check /private/sensitive/path/output.py",
                "state": "done", "owner": "claude", "verified_by": "agy",
                "evidence": "Reviewed /private/sensitive/path/output.py", "rejections": 0,
            }],
        ), config(), "2026-08-29T12:01:00Z")
        encoded = json.dumps(payload)
        self.assertNotIn("private@example.com", encoded)
        self.assertNotIn("/private/sensitive/path", encoded)
        self.assertNotIn("secret@example.com", encoded)
        self.assertNotIn("file:///", encoded)
        self.assertNotIn("/Users/", encoded)
        self.assertIn("[workspace]", encoded)
        self.assertIn("[local-file]", encoded)

    def test_status_is_derived_from_authoritative_halt(self):
        cases = [
            (None, "running"),
            ({"reason": "complete"}, "complete"),
            ({"reason": "blocked: c2"}, "blocked"),
            ({"reason": "turn_budget"}, "halted"),
        ]
        for halt, expected in cases:
            with self.subTest(halt=halt):
                payload = rally_console.build_snapshot(state(halt=halt), config())
                self.assertEqual(payload["status"], expected)

    def test_progress_and_verifier_come_from_checklist(self):
        checklist = [{
            "id": "c1", "description": "Prove replay safety", "state": "done",
            "owner": "claude", "verified_by": "agy", "evidence": "8 tests passed",
            "rejections": 0,
        }]
        payload = rally_console.build_snapshot(state(
            checklist=checklist,
            turns=[
                {"actor": "claude", "family": "anthropic", "model": "sonnet"},
                {"actor": "agy", "family": "google", "model": "gemini-3.7-flash-low"},
            ],
        ), config())
        self.assertEqual(payload["progress"], {"done": 1, "total": 1})
        self.assertEqual(payload["checklist"][0]["verified_by"], "agy")
        self.assertEqual(payload["value_receipt"], {
            "independently_verified": 1,
            "evidence_receipts": 1,
            "model_families": 2,
            "self_approved": 0,
        })
        codex = next(agent for agent in payload["agents"] if agent["id"] == "codex")
        self.assertFalse(codex["participated"])

    def test_real_turn_history_is_preserved_for_the_console(self):
        turns = [{
            "at": "2026-08-29T12:00:30Z", "turn": 1, "actor": "agy",
            "family": "google", "model": "gemini-3.7-flash-low",
            "narrative": "Replayed the suite independently.", "commit": "abc1234",
            "changes": [{
                "id": "c1", "state": "done", "owner": "claude",
                "verified_by": "agy", "evidence": "8 tests passed",
            }],
        }]
        payload = rally_console.build_snapshot(state(turns=turns), config())
        turn = next(item for item in payload["timeline"] if item["kind"] == "turn")
        self.assertEqual(turn["model"], "gemini-3.7-flash-low")
        self.assertEqual(turn["changes"][0]["verified_by"], "agy")

    def test_second_wind_recovery_is_public_proof_without_raw_error_output(self):
        continuity = {
            "mode": "second_wind",
            "second_wind": True,
            "recoveries_used": 1,
            "max_recoveries_per_run": 2,
            "active": None,
            "history": [{
                "id": "sw-1", "at": "2026-08-29T12:00:20Z", "turn": 1,
                "kind": "agent_error", "from_actor": "claude", "to_actor": "agy",
                "items": ["c1"], "status": "recovered",
                "detail": "secret raw CLI output from /private/sensitive/path",
            }],
        }
        payload = rally_console.build_snapshot(state(continuity=continuity), config())
        recovery = next(item for item in payload["timeline"] if item["kind"] == "recovery")
        self.assertEqual(recovery["model"], "Second Wind")
        self.assertIn("Claude to Gemini", recovery["narrative"])
        self.assertNotIn("secret raw CLI output", json.dumps(payload))
        self.assertEqual(payload["policy"]["continuity"], {
            "mode": "second_wind",
            "recoveries_used": 1,
            "max_recoveries_per_run": 2,
        })

    def test_cloud_claims_appear_only_for_an_actual_adk_record(self):
        local = rally_console.build_snapshot(state(), config())
        coordinated = rally_console.build_snapshot(state(cloud_coordinator={
            "status": "ready_for_rally", "coordinator_record": "Bounded handoff issued."
        }), config())
        self.assertEqual(local["coordination"]["status"], "local")
        self.assertIsNone(local["coordination"]["framework"])
        self.assertEqual(coordinated["coordination"]["framework"], "Google ADK")
        self.assertIn("Cloud Run", coordinated["coordination"]["services"])

    def test_private_workspace_publication_does_not_enable_public_visibility(self):
        response = io.BytesIO(b'{"ok":true}')
        with mock.patch.object(rally_console.transport, "get_key", return_value="secret"), \
                mock.patch.object(rally_console.urllib.request, "urlopen", return_value=response):
            result = rally_console.publish(state(), config(enabled=True, public=False))
        self.assertEqual(result, {"ok": True})
        payload = rally_console.build_snapshot(state(), config(enabled=True, public=False))
        self.assertEqual(payload["visibility"], "private")
        self.assertEqual(payload["workspace_id"], "workspace-test")

    def test_disabled_workspace_sync_does_not_publish(self):
        with mock.patch.object(rally_console.urllib.request, "urlopen") as urlopen:
            self.assertIsNone(rally_console.publish(state(), config(enabled=False, public=False)))
        urlopen.assert_not_called()

    def test_publication_uses_bearer_auth_and_the_run_route(self):
        response = io.BytesIO(b'{"ok":true}')
        with mock.patch.object(rally_console.transport, "get_key", return_value="secret"), \
                mock.patch.object(rally_console.urllib.request, "urlopen", return_value=response) as urlopen:
            result = rally_console.publish(state(), config(enabled=True, public=True))
        request = urlopen.call_args.args[0]
        self.assertEqual(result, {"ok": True})
        self.assertEqual(request.full_url, "https://worker.example/v1/console/runs/r-20260829-console")
        self.assertEqual(request.method, "PUT")
        self.assertEqual(request.headers["Authorization"], "Bearer secret")


if __name__ == "__main__":
    unittest.main()
