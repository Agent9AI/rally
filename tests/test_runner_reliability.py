import io
import json
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
            mock.patch.object(runner, "LEDGER", os.path.join(self.runs, "send-ledger.json")),
            mock.patch.object(runner, "QUARANTINE", os.path.join(self.runs, "quarantine.jsonl")),
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

    def test_initial_commission_metadata_is_durable_before_connector_setup(self):
        run_id = "r-20260831-atomic-create"
        observed = {}

        def prepare(_run_id, run_dir, _cfg, _subject):
            with open(os.path.join(run_dir, "state.json")) as handle:
                observed.update(json.load(handle))
            return {}

        with mock.patch.object(runner.connectors, "prepare_run", side_effect=prepare):
            runner.Run.create(
                "ship it",
                ".",
                runtime_config(),
                run_id=run_id,
                connector_subject="owner@example.com",
                commissioned_by="owner@example.com",
                commission_message_id="<mail-1@example>",
                commission_request_key="queue-1",
                workspace_id="workspace-one",
            )

        self.assertEqual(observed["run_id"], run_id)
        self.assertEqual(observed["commission_request_key"], "queue-1")
        self.assertEqual(observed["commission_message_id"], "<mail-1@example>")
        self.assertEqual(observed["commissioned_by"], "owner@example.com")
        self.assertEqual(observed["workspace_id"], "workspace-one")

    def test_report_prompt_uses_latest_recheck_not_stale_evidence_prefix(self):
        stale = "Verified at first checkpoint: 834 words. " + ("old " * 180)
        current = "RE-CHECKED after repair: 897 words and all constraints hold."
        prompt = runner.report.build_report_prompt({
            "task": "build the brief",
            "checklist": [{
                "id": "c1", "description": "Final artifact", "state": "done",
                "owner": "claude", "verified_by": "agy",
                "evidence": stale + current,
            }],
        }, "complete")

        self.assertIn("897 words", prompt)
        self.assertNotIn("834 words", prompt)

    def test_preallocated_run_directory_is_never_overwritten(self):
        run_id = "r-20260831-existing"
        run_dir = os.path.join(self.runs, run_id)
        os.mkdir(run_dir)
        sentinel = os.path.join(run_dir, "keep.txt")
        with open(sentinel, "w") as handle:
            handle.write("original")

        with self.assertRaises(FileExistsError):
            runner.Run.create("replacement", ".", {}, run_id=run_id)

        with open(sentinel) as handle:
            self.assertEqual(handle.read(), "original")

    def test_initial_state_failure_never_publishes_an_orphan_run_directory(self):
        run_id = "r-20260831-state-crash"
        with mock.patch.object(
            runner.Run, "save", side_effect=OSError("state persistence failed")
        ):
            with self.assertRaises(OSError):
                runner.Run.create("ship it", ".", {}, run_id=run_id)

        self.assertFalse(os.path.lexists(os.path.join(self.runs, run_id)))
        self.assertFalse(any(
            name.startswith(".%s.create-" % run_id)
            for name in os.listdir(self.runs)
        ))
        recovered = runner.Run.create("ship it", ".", {}, run_id=run_id)
        self.assertEqual(recovered.s["run_id"], run_id)

    def test_stranded_staging_state_does_not_deadlock_preallocated_retry(self):
        run_id = "r-20260831-stranded-stage"
        staging = tempfile.mkdtemp(
            prefix=".%s.create-" % run_id, dir=self.runs
        )
        with open(os.path.join(staging, "state.json"), "w") as handle:
            json.dump({
                "run_id": run_id,
                "commission_request_key": "queue-atomic",
                "created": "2026-08-31T12:00:00Z",
            }, handle)

        self.assertIsNone(runner.Run.find_commission("queue-atomic"))
        recovered = runner.Run.create(
            "ship it",
            ".",
            {},
            run_id=run_id,
            commissioned_by="owner@example.com",
            commission_request_key="queue-atomic",
        )
        self.assertEqual(recovered.s["commission_request_key"], "queue-atomic")
        self.assertTrue(os.path.isfile(os.path.join(self.runs, run_id, "state.json")))

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

    def test_dashboard_commission_uses_preallocated_run_identity_and_policy(self):
        cfg = runtime_config(second_wind=False)
        run_id = "r-20260831-123e4567-e89b-42d3-a456-426614174000"
        with mock.patch.object(runner, "new_workspace", return_value=self.tmp.name), \
                mock.patch.object(runner, "attach_cloud_coordination", return_value=True), \
                mock.patch.object(runner, "sync_console", return_value=True), \
                mock.patch.object(runner, "loop", return_value="complete"), \
                mock.patch.object(runner, "write_report", return_value="verified"), \
                mock.patch.object(runner, "mail_report"):
            accepted_id = runner.handle_commission(
                cfg,
                "Prove the workflow\n\nGoal:\nProduce evidence.",
                "owner@example.com",
                request_key=run_id,
                run_id=run_id,
                source_run_id="r-20260830-source",
                second_wind=True,
                workspace_id="workspace-one",
            )

        self.assertEqual(accepted_id, run_id)
        saved = runner.Run.load(run_id).s
        self.assertEqual(saved["commission_request_key"], run_id)
        self.assertEqual(saved["source_run_id"], "r-20260830-source")
        self.assertEqual(saved["commissioned_by"], "owner@example.com")
        self.assertEqual(saved["workspace_id"], "workspace-one")
        self.assertTrue(saved["continuity"]["second_wind"])
        self.assertEqual(saved["continuity"]["mode"], "second_wind")

    def test_serve_passes_dashboard_metadata_without_changing_queue_ack_id(self):
        cfg = {
            "ingress": {
                "commission_address": "rally@example.com",
                "worker_url": "https://worker.example",
                "poll_interval_sec": 1,
            }
        }
        queue_id = "00000000-0000-4000-8000-000000000001"
        run_id = "r-20260831-123e4567-e89b-42d3-a456-426614174000"
        message = {
            "id": queue_id,
            "kind": "commission",
            "detail": {
                "task": "ship it",
                "sender": "owner@example.com",
                "run_id": run_id,
                "request_key": run_id,
                "source_run_id": "r-20260830-source",
                "second_wind": False,
                "workspace_id": "workspace-one",
            },
        }
        with mock.patch("ingress.collect", return_value=[message]), \
                mock.patch("ingress.ack") as ack, \
                mock.patch.object(runner, "handle_commission", return_value=run_id) as handle:
            self.assertEqual(runner.serve(cfg, once=True), 0)

        handle.assert_called_once_with(
            cfg,
            "ship it",
            "owner@example.com",
            None,
            request_key=run_id,
            run_id=run_id,
            source_run_id="r-20260830-source",
            second_wind=False,
            workspace_id="workspace-one",
        )
        ack.assert_called_once_with(cfg, [queue_id])

    def test_failed_report_delivery_stays_queued_and_replay_skips_agents(self):
        cfg = runtime_config()
        cfg["mail"] = {"enabled": True}
        cfg["limits"]["sends_per_run"] = 1
        cfg["ingress"] = {
            "commission_address": "rally@example.com",
            "worker_url": "https://worker.example",
            "poll_interval_sec": 1,
        }
        queue_id = "00000000-0000-4000-8000-000000000009"
        message = {
            "id": queue_id,
            "kind": "commission",
            "detail": {"task": "ship it", "sender": "owner@example.com"},
        }
        workspace = os.path.join(self.runs, "work")
        with mock.patch("ingress.collect", return_value=[message]), \
                mock.patch("ingress.ack") as ack, \
                mock.patch.object(runner, "new_workspace", return_value=workspace), \
                mock.patch.object(runner, "attach_cloud_coordination", return_value=True), \
                mock.patch.object(runner, "sync_console", return_value=True), \
                mock.patch.object(runner, "loop", return_value="complete") as loop, \
                mock.patch.object(runner, "write_report", return_value="verified report"), \
                mock.patch.object(runner.transport, "get_key", return_value="secret"), \
                mock.patch.object(
                    runner.transport,
                    "send",
                    side_effect=[runner.transport.SendBlocked("resend unavailable"), "mail-1"],
                ) as send:
            self.assertEqual(runner.serve(cfg, once=True), 0)
            self.assertEqual(runner.serve(cfg, once=True), 0)

        self.assertEqual(ack.call_args_list, [mock.call(cfg, []), mock.call(cfg, [queue_id])])
        loop.assert_called_once()
        self.assertEqual(send.call_count, 2)
        keys = [call.kwargs["idempotency_key"] for call in send.call_args_list]
        self.assertEqual(keys[0], keys[1])
        run = runner.Run.find_commission(queue_id)
        self.assertIsNotNone(run)
        self.assertEqual(run.s["report"], "verified report")
        self.assertEqual(run.s["report_delivery"]["status"], "delivered")
        self.assertEqual(run.s["report_delivery"]["provider_message_id"], "mail-1")
        with open(runner.LEDGER) as handle:
            self.assertEqual(len(json.load(handle)["sends"]), 1)

    def test_stop_delivery_failure_stays_queued_and_reuses_saved_report(self):
        cfg = runtime_config()
        cfg["mail"] = {"enabled": True}
        cfg["limits"]["sends_per_run"] = 1
        cfg["ingress"] = {
            "commission_address": "rally@example.com",
            "worker_url": "https://worker.example",
            "poll_interval_sec": 1,
        }
        run = runner.Run.create(
            "ship it", ".", cfg, commissioned_by="owner@example.com"
        )
        queue_id = "00000000-0000-4000-8000-000000000010"
        message = {
            "id": queue_id,
            "kind": "note",
            "detail": {
                "run_id": run.s["run_id"],
                "text": "STOP now",
                "sender": "owner@example.com",
                "message_id": "<note-1@example>",
            },
        }
        with mock.patch("ingress.collect", return_value=[message]), \
                mock.patch("ingress.ack") as ack, \
                mock.patch.object(runner, "sync_console", return_value=True), \
                mock.patch.object(runner.transport, "get_key", return_value="secret"), \
                mock.patch.object(
                    runner.transport,
                    "send",
                    side_effect=[runner.transport.SendBlocked("resend unavailable"), "mail-1"],
                ) as send:
            self.assertEqual(runner.serve(cfg, once=True), 0)
            pending = runner.Run.load(run.s["run_id"])
            self.assertEqual(pending.s["report_delivery"]["status"], "pending")
            self.assertEqual(pending.s["report_generation"], 1)
            self.assertEqual(runner.serve(cfg, once=True), 0)

        self.assertEqual(ack.call_args_list, [mock.call(cfg, []), mock.call(cfg, [queue_id])])
        self.assertEqual(send.call_count, 2)
        self.assertEqual(
            send.call_args_list[0].kwargs["idempotency_key"],
            send.call_args_list[1].kwargs["idempotency_key"],
        )
        delivered = runner.Run.load(run.s["run_id"])
        self.assertEqual(delivered.s["report_generation"], 1)
        self.assertEqual(delivered.s["report_delivery"]["status"], "delivered")
        with open(runner.LEDGER) as handle:
            self.assertEqual(len(json.load(handle)["sends"]), 1)

    def test_regular_note_delivery_failure_is_not_acknowledged(self):
        cfg = runtime_config()
        cfg["mail"] = {"enabled": True}
        cfg["ingress"] = {
            "commission_address": "rally@example.com",
            "worker_url": "https://worker.example",
            "poll_interval_sec": 1,
        }
        run = runner.Run.create(
            "ship it", ".", cfg, commissioned_by="owner@example.com"
        )
        queue_id = "00000000-0000-4000-8000-000000000011"
        message = {
            "id": queue_id,
            "kind": "note",
            "detail": {
                "run_id": run.s["run_id"],
                "text": "Add one more check",
                "sender": "owner@example.com",
                "message_id": "<note-2@example>",
            },
        }
        with mock.patch("ingress.collect", return_value=[message]), \
                mock.patch("ingress.ack") as ack, \
                mock.patch.object(runner, "loop", return_value="complete"), \
                mock.patch.object(runner, "write_report", return_value="updated report"), \
                mock.patch.object(runner, "sync_console", return_value=True), \
                mock.patch.object(runner.transport, "get_key", return_value="secret"), \
                mock.patch.object(
                    runner.transport,
                    "send",
                    side_effect=runner.transport.SendBlocked("resend unavailable"),
                ):
            self.assertEqual(runner.serve(cfg, once=True), 0)

        ack.assert_called_once_with(cfg, [])
        self.assertEqual(
            runner.Run.load(run.s["run_id"]).s["report_delivery"]["status"],
            "pending",
        )

    def test_human_reply_resumes_exact_run_and_replies_in_same_rally_thread(self):
        cfg = runtime_config()
        cfg["mail"] = {"enabled": True}
        run = runner.Run.create(
            "Produce the launch brief", ".", cfg,
            commissioned_by="owner@example.com",
            commission_message_id="<commission-1@agent9.dev>",
        )
        run.s["halt"] = {"reason": "blocked: c1", "detail": "needs direction"}
        run.s["checklist"] = [{
            "id": "c1", "description": "Revise the brief", "state": "blocked",
            "owner": None, "verified_by": None, "evidence": "draft.html",
            "rejections": 0,
        }]
        run.save()
        observed = {}

        def resumed_loop(resumed, _cfg):
            observed["run_id"] = resumed.s["run_id"]
            observed["instruction"] = resumed.s["human_note"]
            observed["state"] = resumed.s["checklist"][0]["state"]
            return "complete"

        with mock.patch.object(runner, "loop", side_effect=resumed_loop), \
                mock.patch.object(runner, "write_report", return_value="Revised and verified."), \
                mock.patch.object(runner, "sync_console", return_value=True), \
                mock.patch.object(runner.transport.Ledger, "check_and_reserve"), \
                mock.patch.object(runner.transport, "get_key", return_value="secret"), \
                mock.patch.object(runner.transport, "send", return_value="mail-2") as send:
            runner.handle_note(
                cfg,
                run.s["run_id"],
                "Make the recommendation more direct and revise the final slide.",
                message_id="<reply-2@agent9.dev>",
                sender="owner@example.com",
                request_key="queue-event-2",
            )

        self.assertEqual(observed, {
            "run_id": run.s["run_id"],
            "instruction": (
                "Make the recommendation more direct and revise the final slide."
            ),
            "state": "open",
        })
        message = send.call_args.kwargs
        self.assertEqual(message["sender"], "Rally <rally@updates.agent9.dev>")
        self.assertEqual(message["to"], "owner@example.com")
        self.assertNotIn("cc", message)
        self.assertEqual(message["headers"]["In-Reply-To"], "<reply-2@agent9.dev>")
        self.assertEqual(
            message["headers"]["References"],
            "<commission-1@agent9.dev> <reply-2@agent9.dev>",
        )
        self.assertNotIn("c@example.com", message["text"])
        self.assertNotIn("g@example.com", message["text"])

    def test_note_sender_must_match_the_original_commissioner(self):
        cfg = runtime_config()
        cfg["ingress"] = {
            "commission_address": "rally@example.com",
            "worker_url": "https://worker.example",
            "poll_interval_sec": 1,
        }
        run = runner.Run.create(
            "ship it", ".", cfg, commissioned_by="owner-a@example.com"
        )
        queue_id = "00000000-0000-4000-8000-000000000012"
        message = {
            "id": queue_id,
            "kind": "note",
            "detail": {
                "run_id": run.s["run_id"],
                "text": "STOP",
                "sender": "owner-b@example.com",
                "message_id": "<hostile-note@example>",
            },
        }
        with mock.patch("ingress.collect", return_value=[message]), \
                mock.patch("ingress.ack") as ack:
            self.assertEqual(runner.serve(cfg, once=True), 0)

        ack.assert_called_once_with(cfg, [queue_id])
        unchanged = runner.Run.load(run.s["run_id"])
        self.assertIsNone(unchanged.s["human_note"])
        self.assertNotIn("report", unchanged.s)
        with open(runner.QUARANTINE) as handle:
            self.assertIn("note sender is not the run commissioner", handle.read())

    def test_authenticated_human_resume_reopens_block_without_approving_it(self):
        run = runner.Run.create(
            "ship it", ".", runtime_config(),
            commissioned_by="owner@example.com",
        )
        run.s["halt"] = {"reason": "blocked: c1", "detail": ""}
        run.s["checklist"] = [{
            "id": "c1", "description": "Audit the result", "state": "blocked",
            "owner": None, "verified_by": None, "evidence": "artifact missing",
            "rejections": 0,
        }]

        reopened = runner.apply_human_note(
            run, "The artifact now exists. Resume the independent audit."
        )

        self.assertEqual(reopened, ["c1"])
        self.assertIsNone(run.s["halt"])
        self.assertEqual(run.s["checklist"][0]["state"], "open")
        self.assertIsNone(run.s["checklist"][0]["owner"])
        self.assertIsNone(run.s["checklist"][0]["verified_by"])
        self.assertEqual(run.s["checklist"][0]["evidence"], "artifact missing")
        self.assertIn("HUMAN RESUME", run.s["log"][-1])

    def test_stop_note_does_not_reopen_blocked_work(self):
        run = runner.Run.create("ship it", ".", runtime_config())
        run.s["checklist"] = [{
            "id": "c1", "description": "Audit", "state": "blocked",
            "owner": None, "verified_by": None, "evidence": "needs owner",
            "rejections": 0,
        }]

        self.assertEqual(runner.apply_human_note(run, "STOP now"), [])
        self.assertEqual(run.s["checklist"][0]["state"], "blocked")

    def test_provider_acceptance_before_state_save_reuses_idempotency_key(self):
        cfg = runtime_config()
        cfg["mail"] = {"enabled": True}
        run = runner.Run.create(
            "ship it", ".", cfg, commissioned_by="owner@example.com"
        )
        runner.record_report(run, "verified report", "complete")

        with mock.patch.object(runner.transport.Ledger, "check_and_reserve"), \
                mock.patch.object(runner.transport, "get_key", return_value="secret"), \
                mock.patch.object(runner.transport, "send", return_value="mail-1") as send, \
                mock.patch.object(run, "save", side_effect=OSError("crash after acceptance")):
            with self.assertRaises(OSError):
                runner.mail_report(run, cfg, run.s["report"], "complete")

        pending = runner.Run.load(run.s["run_id"])
        self.assertEqual(pending.s["report_delivery"]["status"], "pending")
        with mock.patch.object(runner.transport.Ledger, "check_and_reserve"), \
                mock.patch.object(runner.transport, "get_key", return_value="secret"), \
                mock.patch.object(runner.transport, "send", return_value="mail-1") as replay_send:
            runner.mail_report(pending, cfg, pending.s["report"], "complete")

        first_key = send.call_args.kwargs["idempotency_key"]
        self.assertEqual(replay_send.call_args.kwargs["idempotency_key"], first_key)
        self.assertEqual(
            runner.Run.load(run.s["run_id"]).s["report_delivery"]["status"],
            "delivered",
        )

    def test_no_mail_marks_delivery_not_required_without_sending(self):
        cfg = runtime_config()
        run = runner.Run.create("ship it", ".", cfg)
        runner.record_report(run, "verified report", "complete")

        with mock.patch.object(runner.transport, "send") as send:
            runner.mail_report(run, cfg, run.s["report"], "complete")

        send.assert_not_called()
        self.assertEqual(run.s["report_delivery"]["status"], "not_required")

    def test_turn_update_is_one_rally_to_commissioner_thread(self):
        cfg = runtime_config()
        cfg["mail"] = {"enabled": True}
        run = runner.Run.create(
            "Create a picture of a beagle\n\nI like beagles.", ".", cfg,
            commissioned_by="owner@example.com",
        )

        with mock.patch.object(runner.transport.Ledger, "check_and_reserve"), \
                mock.patch.object(runner.transport, "get_key", return_value="secret"), \
                mock.patch.object(runner.transport, "send", return_value="mail-1") as send:
            runner.mail_turn(run, cfg, "claude", "The image is being prepared.", None)

        message = send.call_args.kwargs
        self.assertEqual(message["sender"], "Rally <rally@updates.agent9.dev>")
        self.assertEqual(message["to"], "owner@example.com")
        self.assertNotIn("cc", message)
        self.assertNotIn("c@example.com", message["text"])
        self.assertNotIn("g@example.com", message["text"])

    def test_final_report_is_sent_by_rally_without_worker_mailbox(self):
        cfg = runtime_config()
        cfg["mail"] = {"enabled": True}
        run = runner.Run.create(
            "Create a picture of a beagle", ".", cfg,
            commissioned_by="owner@example.com",
        )
        runner.record_report(run, "The verified image is ready.", "complete")

        with mock.patch.object(runner.transport.Ledger, "check_and_reserve"), \
                mock.patch.object(runner.transport, "get_key", return_value="secret"), \
                mock.patch.object(runner.transport, "send", return_value="mail-1") as send:
            runner.mail_report(run, cfg, run.s["report"], "complete")

        message = send.call_args.kwargs
        self.assertEqual(message["sender"], "Rally <rally@updates.agent9.dev>")
        self.assertEqual(message["to"], "owner@example.com")
        self.assertNotIn("c@example.com", message["text"])
        self.assertEqual(message["headers"]["X-Rally-From"], "claude")

    def test_transport_sends_idempotency_as_http_header(self):
        response = io.BytesIO(b'{"id":"mail-1"}')
        with mock.patch.object(
            runner.transport.urllib.request, "urlopen", return_value=response
        ) as urlopen:
            result = runner.transport.send(
                key="secret",
                sender="Rally <rally@example.com>",
                to="owner@example.com",
                subject="done",
                text="report",
                headers={"X-Rally-Run": "r-one"},
                idempotency_key="rally-final-report-r-one-1",
            )

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(result, "mail-1")
        self.assertEqual(
            request.headers["Idempotency-key"], "rally-final-report-r-one-1"
        )
        self.assertEqual(payload["headers"], {"X-Rally-Run": "r-one"})

    def test_idempotent_ledger_retry_reuses_one_reservation_without_weakening_caps(self):
        ledger = runner.transport.Ledger(runner.LEDGER)
        for _ in range(20):
            ledger.check_and_reserve(
                "r-one", 1, reservation_key="rally-final-report-r-one-1"
            )

        with self.assertRaises(runner.transport.SendBlocked):
            ledger.check_and_reserve(
                "r-one", 1, reservation_key="rally-final-report-r-one-2"
            )
        with open(runner.LEDGER) as handle:
            sends = json.load(handle)["sends"]
        self.assertEqual(len(sends), 1)
        self.assertEqual(
            sends[0]["reservation_key"], "rally-final-report-r-one-1"
        )

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

    def test_authenticated_followup_after_completion_adds_revision_without_erasing_proof(self):
        run = runner.Run.create("Create a song", self.tmp.name, runtime_config())
        run.s["checklist"] = [{
            "id": "c1", "description": "Create original song", "state": "done",
            "owner": "claude", "verified_by": "agy", "evidence": "audio checked",
            "rejections": 0,
        }]
        run.s["halt"] = {"reason": "complete"}

        reopened = runner.apply_human_note(run, "Make the chorus funnier")

        self.assertEqual(reopened, ["c2"])
        self.assertEqual(run.s["checklist"][0]["state"], "done")
        self.assertEqual(run.s["checklist"][0]["verified_by"], "agy")
        self.assertEqual(run.s["checklist"][1]["state"], "open")
        self.assertIn("Make the chorus funnier", run.s["checklist"][1]["description"])
        self.assertIsNone(run.s["halt"])

    def test_media_receipt_is_context_not_self_approval(self):
        cfg = runtime_config()
        run = runner.Run.create("Picture of a beagle", self.tmp.name, cfg)
        run.s["media_generations"] = [{
            "kind": "image", "status": "ready", "model": "gemini-2.5-flash-image",
            "filename": "deliverable-image.png", "sha256": "a" * 64,
        }]

        prompt = runner.build_prompt(run, "claude", cfg)

        self.assertIn("GOOGLE MEDIA TOOL RECEIPT", prompt)
        self.assertIn("not completion proof", prompt)
        self.assertIn("different model family must still verify", prompt)


if __name__ == "__main__":
    unittest.main()
