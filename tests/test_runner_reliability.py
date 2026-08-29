import os
import tempfile
import unittest
from unittest import mock

import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import runner  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
