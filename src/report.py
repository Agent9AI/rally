"""The one message the human actually reads.

Founding section 9 sets the bar: what was asked, what was built, what was
verified and how, what to look at first, what is still open. Not a transcript.

Section 8 sets the honesty rule: a run that ran out of budget or deadlocked is a
HALT, and it is reported as one. It is never dressed up as completion.
"""
from __future__ import annotations

from typing import Dict, List

HALT_MEANING = {
    "complete": ("COMPLETE", "Every checklist item was verified by the agent that did not do the work."),
    "turn_budget": ("HALT", "The run hit its turn budget before finishing. This is not a completion."),
    "no_progress": ("HALT", "Several turns passed with no item changing state, so the run was not converging."),
    "disputed": ("HALT", "Independent agents disagreed three times on the same item and escalated to you."),
    "blocked": ("HALT", "An item needs something only you can provide."),
    "agent_error": ("HALT", "Both bounded model attempts failed before a safe continuation was accepted."),
    "stopped_by_human": ("HALT", "You stopped this run."),
}


def classify(halt: str) -> tuple:
    for key, val in HALT_MEANING.items():
        if halt.startswith(key):
            return val
    return ("HALT", halt)


def mechanical_summary(state: Dict, halt: str) -> str:
    """Deterministic executive fallback: correct, calm, and actionable."""
    status, meaning = classify(halt)
    items: List[Dict] = state.get("checklist", [])
    done = [i for i in items if i["state"] == "done"]
    stuck = [i for i in items if i["state"] in ("blocked", "disputed")]
    open_ = [i for i in items if i["state"] not in ("done", "blocked", "disputed")]

    headline = ("Completed — %d of %d outcomes independently verified."
                if status == "COMPLETE" else
                "Action needed — %d of %d outcomes independently verified.")
    lines = [headline % (len(done), len(items)), "", "Outcome", meaning]
    if state.get("task"):
        lines += ["", "Your request", state.get("task", "")[:600]]
    lines += ["", "Independent proof"]
    lines += ["- %s — %s\n  Verified by %s; evidence: %s"
              % (i["id"], i["description"][:90], i.get("verified_by") or "not recorded",
                 (i.get("evidence") or "none recorded")[:160])
              for i in done] or ["- No item reached independent verification."]
    if stuck:
        lines += ["", "What Rally needs from you"]
        lines += ["- %s — %s (%s)\n  %s"
                  % (i["id"], i["description"][:90], i["state"],
                     (i.get("evidence") or "")[:200]) for i in stuck]
    if open_:
        lines += ["", "Still open"]
        lines += ["- %s — %s (%s)"
                  % (i["id"], i["description"][:90], i["state"])
                  for i in open_]
    lines += ["", "Next step"]
    if status == "COMPLETE":
        lines += ["No action is required. Reply in this thread if you want Rally "
                  "to extend or revise the result."]
    else:
        lines += ["Reply in this thread with the missing decision, access, or "
                  "material. Rally will resume this same run without treating "
                  "your reply as approval of its own work."]
    return "\n".join(lines)


def _latest_evidence(value: object, limit: int = 600) -> str:
    """Give the report writer the current evidence, not an obsolete prefix.

    Agents often append a re-check after repairing an item. Taking the first
    characters made the executive report repeat superseded measurements from
    an earlier checkpoint even though the authoritative checklist was correct.
    """
    text = str(value or "none").strip()
    if len(text) <= limit:
        return text
    return "[latest evidence tail] " + text[-limit:]


def build_report_prompt(state: Dict, halt: str) -> str:
    status, meaning = classify(halt)
    return """The Rally run is over. Write the single message the human receives.
This is the only thing they read, so it carries the whole outcome.

OUTCOME: %s
WHY: %s

WHAT THEY ASKED FOR:
%s

THE FINAL CHECKLIST, as the runner recorded it (authoritative):
%s

Write it as an executive brief:
- Lead with the outcome in one sentence. If this is a HALT, say so plainly in
  that sentence. Never describe a halt as a completion.
- What was built, and where it is.
- What was verified, and by what evidence. Name which agent verified what,
  since the cross-check is the point of the system.
- What to look at first.
- What is still open, and what you would do next.
- Use the headings Outcome, What changed, Independent proof, and Next step when
  they apply. Make the next action understandable to a non-technical operator.
- Translate implementation detail into business meaning. Do not expose local
  paths, raw identifiers, JSON, model/tool traces, prompt text, stack traces, or
  internal orchestration jargon in the executive body. The delivery layer adds
  a separate audit receipt.
- Evidence may contain re-checks after repairs. Treat the evidence shown here
  as current and never repeat an older measurement or rejected claim.
- Use decisive language, short sections, and only material detail. Avoid
  greetings, sign-offs, internal process commentary, and tool-by-tool narration.

Plain prose and short headings. No transcript, no tool traces, no JSON, no
checklist dump, no progress narration. Under 400 words. Output only the report
itself, with no preamble.""" % (
        status, meaning, state.get("task", ""),
        "\n".join("  %s [%s] %s | owner=%s verified_by=%s | evidence: %s"
                  % (i["id"], i["state"], i["description"][:100], i.get("owner"),
                     i.get("verified_by"), _latest_evidence(i.get("evidence")))
                  for i in state.get("checklist", [])))
