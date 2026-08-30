import os
import tempfile
import unittest
from unittest import mock

import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import runner  # noqa: E402


def runtime_config(second_wind=False):
    return {
        "agents": {
            "claude": {"model": "sonnet", "family": "anthropic", "address": "c@example.com"},
            "agy": {"model": "gemini-3.7-flash-low", "family": "google", "address": "g@example.com"},
        },
        "limits": {
            "turns_max": 12, "sends_per_run": 60, "no_progress_halt": 3,
            "reprompts_max": 1, "rejections_max": 2, "turn_timeout_sec": 30,
        },
        "continuity": {
            "second_wind": second_wind,
            "max_recoveries_per_run": 2,
        },
        "mail": {"enabled": False},
    }


def reply(run, actor, checklist, narrative="handled"):
    return "```json\n%s\n```" % __import__("json").dumps({
        "rally_version": 1,
        "run_id": run.s["run_id"],
        "turn": run.s["turn"],
        "from_agent": actor,
        "narrative": narrative,
        "checklist": checklist,
    })


class DurableIngressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.runs = self.tmp.name
        self.patches = [
            mock.patch.object(runner, "RUNS", self.runs),
            mock.patch.object(runner, "SERVE_LOCK", os.path.join(self.runs, "serve.lock")),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_commission_request_key_recovers_existing_run(self):
        run = runner.Run.create("ship it", ".", {})
        run.s["commission_request_key"] = "edge-message-1"
        run.s["commission_message_id"] = "<mail-1@example>"
        run.save()

        recovered = runner.Run.find_commission(
            "edge-message-1", "<mail-1@example>"
        )

        self.assertIsNotNone(recovered)
        self.assertEqual(recovered.s["run_id"], run.s["run_id"])

    def test_terminal_commission_replay_does_not_run_agents_again(self):
        run = runner.Run.create("ship it", ".", {})
        run.s["commission_request_key"] = "edge-message-1"
        run.s["report"] = "already delivered"
        run.save()

        with mock.patch.object(runner, "attach_cloud_coordination") as cloud, \
                mock.patch.object(runner, "loop") as loop:
            recovered_id = runner.handle_commission(
                {}, "ship it", "owner@example.com", request_key="edge-message-1"
            )

        self.assertEqual(recovered_id, run.s["run_id"])
        cloud.assert_not_called()
        loop.assert_not_called()

    def test_failed_handler_is_not_acknowledged(self):
        cfg = {
            "ingress": {
                "commission_address": "rally@example.com",
                "worker_url": "https://worker.example",
                "poll_interval_sec": 1,
            }
        }
        message = {
            "id": "00000000-0000-4000-8000-000000000001",
            "kind": "commission",
            "detail": {"task": "ship it", "sender": "owner@example.com"},
        }
        with mock.patch("ingress.collect", return_value=[message]), \
                mock.patch("ingress.ack") as ack, \
                mock.patch.object(runner, "handle_commission", side_effect=RuntimeError("boom")):
            self.assertEqual(runner.serve(cfg, once=True), 0)

        ack.assert_called_once_with(cfg, [])

    def test_retryable_hydration_error_stays_queued(self):
        cfg = {
            "ingress": {
                "commission_address": "rally@example.com",
                "worker_url": "https://worker.example",
                "poll_interval_sec": 1,
            }
        }
        message = {
            "id": "00000000-0000-4000-8000-000000000001",
            "error": "resend 503",
            "retryable": True,
        }
        with mock.patch("ingress.collect", return_value=[message]), \
                mock.patch("ingress.ack") as ack:
            self.assertEqual(runner.serve(cfg, once=True), 0)

        ack.assert_called_once_with(cfg, [])

    def test_accepted_turn_is_retained_for_live_console_provenance(self):
        cfg = {
            "agents": {
                "claude": {"model": "sonnet", "family": "anthropic", "address": "c@example.com"},
                "agy": {"model": "gemini-3.7-flash-low", "family": "google", "address": "g@example.com"},
            },
            "limits": {
                "turns_max": 12, "sends_per_run": 60, "no_progress_halt": 3,
                "reprompts_max": 1, "rejections_max": 2, "turn_timeout_sec": 30,
            },
            "mail": {"enabled": False},
        }
        run = runner.Run.create("prove the console", self.tmp.name, cfg)

        self.assertIsNone(runner.take_turn(run, cfg, dry=True))

        self.assertEqual(len(run.s["turns"]), 1)
        self.assertEqual(run.s["turns"][0]["actor"], "claude")
        self.assertEqual(run.s["turns"][0]["model"], "sonnet")
        self.assertGreaterEqual(len(run.s["turns"][0]["changes"]), 1)

    def test_console_outage_never_controls_authoritative_execution(self):
        run = runner.Run.create("ship it", ".", {})
        with mock.patch.object(
            runner.rally_console,
            "publish",
            side_effect=runner.rally_console.ConsoleError("edge unavailable"),
        ):
            self.assertFalse(runner.sync_console(run, {"console": {"enabled": True}}))
        self.assertIsNone(run.s["halt"])

    def test_three_family_rotation_is_stable_and_snapshotted(self):
        cfg = runtime_config()
        cfg["agents"]["codex"] = {
            "model": "gpt-5.4", "family": "openai", "address": "o@example.com",
        }
        run = runner.Run.create("ship it", self.tmp.name, cfg)

        self.assertEqual(run.s["agent_order"], ["claude", "agy", "codex"])
        self.assertEqual(runner.next_actor(run.s, cfg, "claude"), "agy")
        self.assertEqual(runner.next_actor(run.s, cfg, "agy"), "codex")
        self.assertEqual(runner.next_actor(run.s, cfg, "codex"), "claude")

    def test_agent_failure_halts_when_second_wind_is_off(self):
        cfg = runtime_config(second_wind=False)
        run = runner.Run.create("ship it", self.tmp.name, cfg)

        with mock.patch.object(
            runner.agents, "run_agent", side_effect=runner.agents.AgentError("timeout")
        ):
            self.assertEqual(runner.take_turn(run, cfg), "agent_error")

        self.assertEqual(run.s["actor"], "claude")
        self.assertEqual(run.s["halt"]["reason"], "agent_error")
        self.assertEqual(run.s["continuity"]["recoveries_used"], 0)

    def test_agent_failure_hands_saved_state_to_backup_with_second_wind(self):
        cfg = runtime_config(second_wind=True)
        run = runner.Run.create("ship it", self.tmp.name, cfg)
        run.s["checklist"] = [{
            "id": "c1", "description": "Implement it", "state": "claimed",
            "owner": "claude", "verified_by": None, "evidence": None, "rejections": 0,
        }]
        run.save()

        with mock.patch.object(
            runner.agents, "run_agent", side_effect=runner.agents.AgentError("timeout")
        ):
            self.assertIsNone(runner.take_turn(run, cfg))

        self.assertEqual(run.s["actor"], "agy")
        self.assertIsNone(run.s["halt"])
        recovery = run.s["continuity"]
        self.assertEqual(recovery["recoveries_used"], 1)
        self.assertEqual(recovery["active"]["items"], ["c1"])
        self.assertIn("SECOND WIND RECOVERY", runner.build_prompt(run, "agy", cfg))

    def test_backup_can_repair_a_block_without_self_approving(self):
        cfg = runtime_config(second_wind=True)
        run = runner.Run.create("ship it", self.tmp.name, cfg)
        run.s["turn"] = 2
        run.s["checklist"] = [{
            "id": "c1", "description": "Implement it", "state": "claimed",
            "owner": "claude", "verified_by": None, "evidence": "first attempt",
            "rejections": 0,
        }]
        run.save()
        blocked = [{
            **run.s["checklist"][0], "state": "blocked", "evidence": "tool path failed",
        }]
        repaired = [{
            **run.s["checklist"][0], "state": "awaiting-verification",
            "owner": "agy", "evidence": "backup path passes tests",
        }]

        with mock.patch.object(
            runner.agents, "run_agent",
            side_effect=[reply(run, "claude", blocked), reply(run, "agy", repaired)],
        ):
            self.assertIsNone(runner.take_turn(run, cfg))
            self.assertEqual(run.s["continuity"]["active"]["to_actor"], "agy")
            self.assertIsNone(runner.take_turn(run, cfg))

        item = run.s["checklist"][0]
        self.assertEqual(item["state"], "awaiting-verification")
        self.assertEqual(item["owner"], "agy")
        self.assertIsNone(item["verified_by"])
        self.assertEqual(run.s["continuity"]["history"][0]["status"], "recovered")


if __name__ == "__main__":
    unittest.main()
