import os
import sys
import tempfile
import unittest
from unittest import mock
import json
import io

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import transport


class CredentialIsolationTests(unittest.TestCase):
    def test_resend_override_cannot_become_the_ingress_bearer(self):
        completed = mock.Mock(returncode=0, stdout=b"poll-from-keychain\n")
        with mock.patch.dict(os.environ, {"RESEND_API_KEY": "resend-only"}, clear=True), \
                mock.patch("transport.subprocess.run", return_value=completed) as run:
            self.assertEqual(transport.get_key("rally-poll-token"), "poll-from-keychain")
        run.assert_called_once()

    def test_each_known_credential_has_its_own_override(self):
        with mock.patch.dict(os.environ, {
            "RESEND_API_KEY": "resend-only",
            "RALLY_POLL_TOKEN": "poll-only",
        }, clear=True), mock.patch("transport.subprocess.run") as run:
            self.assertEqual(transport.get_key("rally-resend"), "resend-only")
            self.assertEqual(transport.get_key("rally-poll-token"), "poll-only")
        run.assert_not_called()


class ExecutiveLifecycleEmailTests(unittest.TestCase):
    def turn_text(self, turn="0"):
        return """RALLY EXECUTIVE UPDATE
Run: r-20260831-demo
Turn: %s
From: agy@updates.agent9.dev
To: claude@updates.agent9.dev
Status: In progress

Outcome
Rally accepted the request and is checking the source material.

TECHNICAL RECORD
commit: abc123

```json
{"run_id":"r-20260831-demo","checklist":[]}
```

RALLY WATERMARK | run r-20260831-demo""" % turn

    def report_text(self):
        return """RALLY EXECUTIVE REPORT
Run: r-20260831-demo
From: agy@updates.agent9.dev
Status: COMPLETE

Outcome
The decision brief is ready.

Independent proof
- Every claim was checked by a different model.

RALLY WATERMARK | run r-20260831-demo | turn report
Workdir: /Users/private/runs/demo"""

    def test_first_update_reads_as_an_acknowledgement_and_keeps_run_tag(self):
        rendered = transport._rally_lifecycle_message(
            "[rally #r-20260831-demo] Build the board brief",
            self.turn_text(),
            {"X-Rally-Run": "r-20260831-demo", "X-Rally-Turn": "0"},
        )

        self.assertEqual(
            rendered["subject"],
            "[rally #r-20260831-demo] Request accepted — Build the board brief",
        )
        self.assertEqual(rendered["reply_to"], "Rally <rally@updates.agent9.dev>")
        self.assertIn("Your request is underway.", rendered["text"])
        self.assertIn("Start your reply with STOP", rendered["text"])
        self.assertLess(rendered["text"].index("Outcome"), rendered["text"].index("AUDIT RECEIPT"))
        self.assertIn("Evidence revision: abc123", rendered["text"])
        self.assertNotIn('"checklist"', rendered["text"])

    def test_html_is_table_based_self_contained_and_hides_machine_noise(self):
        rendered = transport._rally_lifecycle_message(
            "[rally #r-20260831-demo] Build the board brief",
            self.turn_text("2"),
            {"X-Rally-Run": "r-20260831-demo", "X-Rally-Turn": "2"},
        )
        message = rendered["html"]

        self.assertIn('<table role="presentation"', message)
        self.assertIn('role="article"', message)
        self.assertIn('meta name="color-scheme"', message)
        self.assertIn("@media (prefers-color-scheme:dark)", message)
        self.assertIn("AUDIT RECEIPT", message)
        self.assertIn("No model approves its own work.", message)
        self.assertNotIn("<details", message)
        self.assertNotIn("<script", message)
        self.assertNotIn("<img", message)
        self.assertNotIn("http://", message)
        self.assertNotIn("https://", message)
        self.assertNotIn('"checklist"', message)
        self.assertNotIn("Workdir:", message)

    def test_complete_and_halt_have_unambiguous_next_actions(self):
        complete = transport._rally_lifecycle_message(
            "[rally #r-20260831-demo] Build the board brief",
            self.report_text(),
            {"X-Rally-Run": "r-20260831-demo", "X-Rally-Report": "COMPLETE"},
        )
        halted = transport._rally_lifecycle_message(
            "[rally #r-20260831-demo] Build the board brief",
            self.report_text().replace("Status: COMPLETE", "Status: HALT"),
            {"X-Rally-Run": "r-20260831-demo", "X-Rally-Report": "HALT"},
        )

        self.assertIn("] Complete — ", complete["subject"])
        self.assertIn("No action is required.", complete["text"])
        self.assertIn("] Action needed — ", halted["subject"])
        self.assertIn("Reply in this thread with the missing decision", halted["text"])
        self.assertIn("independent-verification rules", halted["text"])
        self.assertNotIn("/Users/private", complete["text"])

    def test_send_applies_renderer_and_reply_route_without_losing_headers(self):
        response = io.BytesIO(b'{"id":"mail-1"}')
        with mock.patch.object(transport.urllib.request, "urlopen", return_value=response) as urlopen:
            result = transport.send(
                key="secret",
                sender="Rally <agy@updates.agent9.dev>",
                to="claude@updates.agent9.dev",
                cc="owner@agent9.dev",
                subject="[rally #r-20260831-demo] Build the board brief",
                text=self.turn_text(),
                html="<p>obsolete rendering</p>",
                headers={"X-Rally-Run": "r-20260831-demo", "X-Rally-Turn": "0"},
            )

        payload = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(result, "mail-1")
        self.assertEqual(payload["reply_to"], "Rally <rally@updates.agent9.dev>")
        self.assertIn("Request accepted", payload["subject"])
        self.assertIn("AUDIT RECEIPT", payload["html"])
        self.assertNotIn("obsolete rendering", payload["html"])
        self.assertEqual(
            payload["headers"],
            {"X-Rally-Run": "r-20260831-demo", "X-Rally-Turn": "0"},
        )


class FinalArtifactAttachmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.runs = self.temporary.name
        self.run_id = "r-20260831-artifacts"
        self.workspace = os.path.join(self.runs, self.run_id, "workspace")
        os.makedirs(self.workspace)
        self.root_patch = mock.patch.object(transport, "RUNS_ROOT", self.runs)
        self.root_patch.start()

    def tearDown(self):
        self.root_patch.stop()
        self.temporary.cleanup()

    def write(self, relative, content):
        path = os.path.join(self.workspace, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(content)
        return path

    def test_selection_is_allowlisted_deterministic_sanitized_and_base64(self):
        self.write("notes.txt", b"internal notes")
        self.write("screens/evidence.png", b"\x89PNG\r\nproof")
        self.write("Presentation FINAL!.html", b"<!doctype html><title>Brief</title>")

        attachments, note = transport.final_artifact_attachments(self.run_id)

        self.assertEqual(
            [item["filename"] for item in attachments],
            ["Presentation-FINAL.html", "evidence.png"],
        )
        self.assertEqual(attachments[0]["content_type"], "text/html")
        self.assertEqual(
            attachments[0]["content"],
            "PCFkb2N0eXBlIGh0bWw+PHRpdGxlPkJyaWVmPC90aXRsZT4=",
        )
        self.assertIn("Attached 2 deliverables", note)
        self.assertNotIn(self.workspace, note)

    def test_symlinks_and_secret_like_files_are_never_attached(self):
        outside = os.path.join(self.temporary.name, "outside.pdf")
        with open(outside, "wb") as handle:
            handle.write(b"private")
        os.symlink(outside, os.path.join(self.workspace, "final.pdf"))
        self.write("api-key.html", b"<p>not actually safe</p>")

        attachments, note = transport.final_artifact_attachments(self.run_id)

        self.assertEqual(attachments, [])
        self.assertIn("failed the outbound safety check", note)
        self.assertNotIn("api-key", note)
        self.assertNotIn("outside", note)

    def test_secret_signature_in_an_allowed_artifact_is_withheld(self):
        self.write(
            "final-report.html",
            b'<p>draft</p><code>client_secret="abcdefghijklmnopqrstuvwxyz"</code>',
        )

        attachments, note = transport.final_artifact_attachments(self.run_id)

        self.assertEqual(attachments, [])
        self.assertIn("withheld", note)

    def test_oversized_artifact_is_omitted_without_blocking_the_report(self):
        self.write("final.pdf", b"123456")
        with mock.patch.object(transport, "MAX_ATTACHMENT_FILE_BYTES", 5):
            attachments, note = transport.final_artifact_attachments(self.run_id)

        self.assertEqual(attachments, [])
        self.assertIn("exceeded the 8 MB safety limit", note)

    def test_completed_send_includes_attachment_and_visible_delivery_note(self):
        self.write("executive-brief.pdf", b"%PDF-1.7\nverified")
        response = io.BytesIO(b'{"id":"mail-with-file"}')
        with mock.patch.object(transport.urllib.request, "urlopen", return_value=response) as urlopen:
            result = transport.send(
                key="secret",
                sender="Rally <agy@updates.agent9.dev>",
                to="owner@agent9.dev",
                subject="[rally #r-20260831-artifacts] Prepare the decision brief",
                text=self._report_text(),
                headers={
                    "X-Rally-Run": self.run_id,
                    "X-Rally-Report": "COMPLETE",
                },
            )

        payload = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(result, "mail-with-file")
        self.assertEqual(payload["attachments"][0]["filename"], "executive-brief.pdf")
        self.assertEqual(payload["attachments"][0]["content_type"], "application/pdf")
        self.assertIn("Attached deliverable: executive-brief.pdf", payload["text"])
        self.assertIn("Attached deliverable: executive-brief.pdf", payload["html"])
        self.assertNotIn(self.workspace, payload["text"])
        self.assertNotIn(self.workspace, payload["html"])

    def test_generated_image_is_inline_and_attached_with_plain_fallback(self):
        self.write("deliverable-image.png", b"\x89PNG\r\nbeagle")
        response = io.BytesIO(b'{"id":"mail-with-inline-image"}')
        with mock.patch.object(transport.urllib.request, "urlopen", return_value=response) as urlopen:
            transport.send(
                key="secret",
                sender="Rally <rally@updates.agent9.dev>",
                to="owner@agent9.dev",
                subject="[rally #r-20260831-artifacts] Picture of a beagle",
                text=self._report_text(),
                headers={
                    "X-Rally-Run": self.run_id,
                    "X-Rally-Report": "COMPLETE",
                },
            )

        payload = json.loads(urlopen.call_args.args[0].data)
        image = payload["attachments"][0]
        self.assertEqual(image["filename"], "deliverable-image.png")
        self.assertEqual(image["content_type"], "image/png")
        self.assertEqual(image["content_id"], "rally-deliverable-image")
        self.assertIn('src="cid:rally-deliverable-image"', payload["html"])
        self.assertIn("Attached deliverable: deliverable-image.png", payload["text"])

    def test_generated_song_is_a_mime_aware_attachment(self):
        self.write("deliverable-song.mp3", b"ID3\x04\x00\x00song")

        attachments, note = transport.final_artifact_attachments(self.run_id)

        self.assertEqual(attachments[0]["filename"], "deliverable-song.mp3")
        self.assertEqual(attachments[0]["content_type"], "audio/mpeg")
        self.assertNotIn("content_id", attachments[0])
        self.assertIn("Attached deliverable", note)

    def test_unsupported_files_produce_an_honest_omission_note(self):
        self.write("research.json", b'{"proof":true}')
        response = io.BytesIO(b'{"id":"mail-without-file"}')
        with mock.patch.object(transport.urllib.request, "urlopen", return_value=response) as urlopen:
            transport.send(
                key="secret",
                sender="Rally <agy@updates.agent9.dev>",
                to="owner@agent9.dev",
                subject="[rally #r-20260831-artifacts] Prepare the decision brief",
                text=self._report_text(),
                headers={
                    "X-Rally-Run": self.run_id,
                    "X-Rally-Report": "COMPLETE",
                },
            )

        payload = json.loads(urlopen.call_args.args[0].data)
        self.assertNotIn("attachments", payload)
        self.assertIn("No supported final artifact was found", payload["text"])
        self.assertIn("No supported final artifact was found", payload["html"])

    def _report_text(self):
        return """RALLY EXECUTIVE REPORT
Run: r-20260831-artifacts
From: agy@updates.agent9.dev
Status: COMPLETE

Outcome
The decision brief is ready and independently verified.

RALLY WATERMARK | run r-20260831-artifacts | turn report
Workdir: /private/run/workspace"""


if __name__ == "__main__":
    unittest.main()
