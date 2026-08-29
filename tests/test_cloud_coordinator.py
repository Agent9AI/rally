import io
import json
import os
import sys
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import cloud_coordinator  # noqa: E402


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return io.BytesIO(json.dumps(self.payload).encode())

    def __exit__(self, *_):
        return None


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "google_cloud": {
                "enabled": True,
                "required": True,
                "url": "https://coordinator.example",
            }
        }

    @mock.patch.dict(os.environ, {
        "RALLY_CLOUD_SERVICE_TOKEN": "secret",
        "RALLY_CLOUD_IDENTITY_TOKEN": "identity",
    }, clear=False)
    @mock.patch("urllib.request.urlopen")
    def test_authenticated_handoff_is_accepted(self, urlopen):
        urlopen.return_value = FakeResponse({
            "accepted": True,
            "status": "ready_for_rally",
            "run_id": "r-test-123",
            "request_key": "mail-1",
            "handoff": {
                "task": "Ship it",
                "policy": {"requires_independent_verification": True},
            },
            "coordinator_record": "Scope accepted; begin independent execution.",
        })
        result = cloud_coordinator.coordinate(
            self.cfg, "Ship it", "r-test-123", "mail-1"
        )
        self.assertEqual(result["status"], "ready_for_rally")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.headers["X-rally-service-token"], "secret")
        self.assertEqual(request.headers["Idempotency-key"], "mail-1")
        self.assertEqual(request.headers["Authorization"], "Bearer identity")

    @mock.patch.dict(os.environ, {
        "RALLY_CLOUD_SERVICE_TOKEN": "secret",
        "RALLY_CLOUD_IDENTITY_TOKEN": "identity",
    }, clear=False)
    @mock.patch("urllib.request.urlopen")
    def test_invalid_policy_fails_closed(self, urlopen):
        urlopen.return_value = FakeResponse({
            "accepted": True,
            "status": "ready_for_rally",
            "run_id": "r-test-123",
            "handoff": {"policy": {"requires_independent_verification": False}},
        })
        with self.assertRaises(cloud_coordinator.CoordinatorError):
            cloud_coordinator.coordinate(self.cfg, "Ship it", "r-test-123", "mail-1")

    def test_disabled_path_is_local(self):
        self.assertIsNone(cloud_coordinator.coordinate(
            {"google_cloud": {"enabled": False}}, "Ship it", "r-test-123", "mail-1"
        ))

    @mock.patch.dict(os.environ, {"RALLY_CLOUD_IDENTITY_TOKEN": ""}, clear=False)
    @mock.patch("cloud_coordinator.subprocess.run")
    def test_identity_token_is_audience_bound_and_least_privilege(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = b"short-lived-token\n"
        token = cloud_coordinator._identity_token({
            "url": "https://coordinator.example/",
            "identity_service_account": "rally-invoker@example.iam.gserviceaccount.com",
        })
        self.assertEqual(token, "short-lived-token")
        self.assertEqual(
            run.call_args.args[0],
            [
                "gcloud",
                "auth",
                "print-identity-token",
                "--impersonate-service-account",
                "rally-invoker@example.iam.gserviceaccount.com",
                "--audiences",
                "https://coordinator.example",
                "--include-email",
            ],
        )


if __name__ == "__main__":
    unittest.main()
