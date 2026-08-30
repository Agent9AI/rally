import json
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).parents[1]


class TestGoogleCloudContract(unittest.TestCase):
    def test_cloud_path_contains_required_submission_components(self):
        requirements = (ROOT / "cloud" / "requirements.txt").read_text()
        self.assertIn("google-adk", requirements)
        self.assertIn("google-cloud-firestore", requirements)
        self.assertTrue((ROOT / "cloud" / "Dockerfile").exists())
        self.assertTrue((ROOT / "cloud" / "cloudbuild.yaml").exists())

    def test_handoff_is_bounded_and_policy_preserving(self):
        import importlib.util

        path = ROOT / "cloud" / "rally_adk" / "handoff.py"
        spec = importlib.util.spec_from_file_location("rally_handoff", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        handoff = module.build_handoff("  Add   rate limiting  ")
        self.assertEqual(handoff["task"], "Add rate limiting")
        self.assertTrue(handoff["policy"]["requires_independent_verification"])

    def test_existing_profiles_keep_distinct_model_families(self):
        for name in ("rally.json", "rally.demo.json"):
            cfg = json.loads((ROOT / "config" / name).read_text())
            self.assertEqual(cfg["agents"]["claude"]["family"], "anthropic")
            self.assertEqual(cfg["agents"]["agy"]["family"], "google")
            self.assertEqual(cfg["agents"]["codex"]["family"], "openai")

    def test_build_and_runtime_use_the_same_region(self):
        cloudbuild = (ROOT / "cloud" / "cloudbuild.yaml").read_text()
        variables = (ROOT / "cloud" / "infra" / "variables.tf").read_text()
        region = re.search(
            r'variable "region".*?default\s*=\s*"([^"]+)"',
            variables,
            re.DOTALL,
        ).group(1)
        self.assertIn(f"{region}-docker.pkg.dev", cloudbuild)

    def test_fleet_catalog_is_packaged_into_the_container(self):
        dockerfile = (ROOT / "cloud" / "Dockerfile").read_text()
        catalog = json.loads((ROOT / "cloud" / "agent_catalog.json").read_text())
        self.assertIn("agent_catalog.json", dockerfile)
        self.assertGreaterEqual(len(catalog["agents"]), 3)

    def test_private_invocation_uses_a_dedicated_audience_bound_identity(self):
        terraform = (ROOT / "cloud" / "infra" / "main.tf").read_text()
        bridge = (ROOT / "src" / "cloud_coordinator.py").read_text()
        self.assertIn("iamcredentials.googleapis.com", terraform)
        self.assertIn("rally-local-invoker", terraform)
        self.assertIn("roles/iam.serviceAccountTokenCreator", terraform)
        self.assertIn('"--audiences"', bridge)
        self.assertIn('"--impersonate-service-account"', bridge)

    def test_customer_control_plane_is_separate_and_kms_encrypted(self):
        terraform = (ROOT / "cloud" / "infra" / "main.tf").read_text()
        control_plane = (ROOT / "cloud" / "control_plane.py").read_text()
        vault = (ROOT / "cloud" / "credential_vault.py").read_text()
        identity = (ROOT / "cloud" / "user_auth.py").read_text()

        self.assertIn('resource "google_cloud_run_v2_service" "control_plane"', terraform)
        self.assertIn('resource "google_kms_crypto_key" "connector_credentials"', terraform)
        self.assertIn('role     = "roles/run.invoker"', terraform)
        self.assertIn('member   = "allUsers"', terraform)
        self.assertIn("Depends(require_user)", control_plane)
        self.assertIn("verify_oauth2_token", identity)
        self.assertIn("AESGCM", vault)
        self.assertIn("wrapped_dek", vault)


if __name__ == "__main__":
    unittest.main()
