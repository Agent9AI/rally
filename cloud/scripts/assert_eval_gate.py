"""Fail when the latest ADK result for any required Rally case did not pass."""
from __future__ import annotations

import json
from pathlib import Path

EXPECTED = {
    "standard_engineering_commission",
    "executive_outcome_request",
    "policy_bypass_attempt",
    "small_business_owner_commission",
    "untrusted_artifact_instruction",
    "multi_system_release_workflow",
}
HISTORY = Path(__file__).parents[1] / "rally_adk" / ".adk" / "eval_history"


def main() -> int:
    latest: dict[str, tuple[float, dict]] = {}
    for path in HISTORY.glob("*.evalset_result.json"):
        with path.open() as handle:
            result = json.load(handle)
        created = float(result.get("creation_timestamp", 0))
        for case in result.get("eval_case_results", []):
            eval_id = case.get("eval_id")
            if eval_id in EXPECTED and created >= latest.get(eval_id, (0, {}))[0]:
                latest[eval_id] = (created, case)

    missing = EXPECTED - latest.keys()
    if missing:
        print("ADK eval gate FAIL: missing " + ", ".join(sorted(missing)))
        return 1

    failed = False
    for eval_id in sorted(EXPECTED):
        case = latest[eval_id][1]
        metrics = {
            item["metric_name"]: item.get("score")
            for item in case.get("overall_eval_metric_results") or []
        }
        passed = case.get("final_eval_status") == 1
        failed = failed or not passed
        print(
            f"{eval_id}: {'PASS' if passed else 'FAIL'} "
            f"trajectory={metrics.get('tool_trajectory_avg_score')} "
            "quality="
            f"{metrics.get('rubric_based_final_response_quality_v1')}"
        )
    if failed:
        print("ADK eval gate FAIL")
        return 1
    print(
        f"ADK eval gate PASS: {len(EXPECTED)}/{len(EXPECTED)} cases met "
        "every configured threshold"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
