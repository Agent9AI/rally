import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import report


class ExecutiveReportTests(unittest.TestCase):
    def state(self):
        return {
            "run_id": "r-20260831-demo",
            "task": "Prepare a decision brief for the leadership team.",
            "turn": 4,
            "workdir": "/Users/private/runs/demo",
            "checklist": [{
                "id": "c1",
                "description": "Confirm every material claim",
                "state": "done",
                "owner": "claude",
                "verified_by": "agy",
                "evidence": "13 official sources returned HTTP 200.",
            }],
        }

    def test_fallback_is_executive_first_and_keeps_infrastructure_out(self):
        text = report.mechanical_summary(self.state(), "complete")

        self.assertTrue(text.startswith("Completed — 1 of 1 outcomes independently verified."))
        self.assertIn("Independent proof", text)
        self.assertIn("Verified by agy", text)
        self.assertIn("Next step", text)
        self.assertIn("No action is required.", text)
        self.assertNotIn("Workdir", text)
        self.assertNotIn("/Users/private", text)

    def test_blocked_fallback_tells_a_nontechnical_operator_how_to_resume(self):
        state = self.state()
        state["checklist"].append({
            "id": "c2",
            "description": "Confirm the private revenue figure",
            "state": "blocked",
            "owner": "codex",
            "verified_by": None,
            "evidence": "The approved source did not contain that figure.",
        })

        text = report.mechanical_summary(state, "blocked: c2")

        self.assertTrue(text.startswith("Action needed — 1 of 2 outcomes independently verified."))
        self.assertIn("What Rally needs from you", text)
        self.assertIn("Reply in this thread with the missing decision", text)
        self.assertIn("without treating your reply as approval of its own work", text)

    def test_report_prompt_requires_business_language_and_an_action(self):
        prompt = report.build_report_prompt(self.state(), "complete")

        self.assertIn("Make the next action understandable to a non-technical operator", prompt)
        self.assertIn("Do not expose local", prompt)
        self.assertIn("separate audit receipt", prompt)
        self.assertIn("Outcome, What changed, Independent proof, and Next step", prompt)


if __name__ == "__main__":
    unittest.main()
