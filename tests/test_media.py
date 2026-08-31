import base64
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import media  # noqa: E402


class MediaIntentTests(unittest.TestCase):
    def test_subject_only_picture_request_is_generation_intent(self):
        request = media.detect_request("Picture of a beagle\n\nI like beagles.")

        self.assertEqual(request["kind"], "image")
        self.assertIn("Picture of a beagle", request["prompt"])

    def test_subject_only_hackathon_song_gets_requested_shoutouts(self):
        request = media.detect_request("All Things Agentic Hackathon Song")

        self.assertEqual(request["kind"], "song")
        self.assertIn("Annie brought the blueprint", request["prompt"])
        self.assertIn("Christina brought the glow", request["prompt"])
        self.assertIn("Shawni", request["prompt"])
        self.assertIn("Second Wind", request["prompt"])

    def test_analysis_request_does_not_mutate_into_generation(self):
        self.assertIsNone(media.detect_request("Analyze this image for accessibility"))

    def test_media_followup_can_inherit_prior_kind(self):
        request = media.detect_request("Make the chorus funnier", previous_kind="song")
        self.assertEqual(request["kind"], "song")


class VertexMediaTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

    def test_image_generation_writes_bounded_google_artifact(self):
        image = b"\x89PNG\r\nactual-image"
        response = io.BytesIO(json.dumps({
            "candidates": [{"content": {"parts": [{"inlineData": {
                "mimeType": "image/png",
                "data": base64.b64encode(image).decode("ascii"),
            }}]}}],
        }).encode("utf-8"))
        with mock.patch.object(media, "_access_token", return_value="token"), \
                mock.patch.object(media.urllib.request, "urlopen", return_value=response) as open_url:
            receipt = media.generate(
                media.detect_request("Picture of a beagle"), self.temporary.name, {}
            )

        self.assertEqual(receipt["model"], "gemini-2.5-flash-image")
        self.assertEqual(receipt["mime_type"], "image/png")
        with open(os.path.join(self.temporary.name, "deliverable-image.png"), "rb") as handle:
            self.assertEqual(handle.read(), image)
        request = open_url.call_args.args[0]
        self.assertIn("gemini-2.5-flash-image:generateContent", request.full_url)
        payload = json.loads(request.data)
        self.assertEqual(payload["generationConfig"]["responseModalities"], ["TEXT", "IMAGE"])

    def test_lyria_generation_writes_playable_mp3_artifact(self):
        audio = b"ID3\x04\x00\x00original-song"
        response = io.BytesIO(json.dumps({
            "status": "completed",
            "outputs": [{
                "type": "audio",
                "mime_type": "audio/mpeg",
                "data": base64.b64encode(audio).decode("ascii"),
            }],
        }).encode("utf-8"))
        with mock.patch.object(media, "_access_token", return_value="token"), \
                mock.patch.object(media.urllib.request, "urlopen", return_value=response) as open_url:
            receipt = media.generate(
                media.detect_request("All Things Agentic Hackathon Song"),
                self.temporary.name,
                {},
            )

        self.assertEqual(receipt["model"], "lyria-3-pro-preview")
        self.assertEqual(receipt["mime_type"], "audio/mpeg")
        with open(os.path.join(self.temporary.name, "deliverable-song.mp3"), "rb") as handle:
            self.assertEqual(handle.read(), audio)
        payload = json.loads(open_url.call_args.args[0].data)
        self.assertEqual(payload["model"], "lyria-3-pro-preview")
        self.assertIn("Rally, Rally", payload["input"][0]["text"])


if __name__ == "__main__":
    unittest.main()
