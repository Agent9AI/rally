"""Rally runner: holds authoritative state, dispatches turns, enforces the limits.

The runner is the authority. An envelope is evidence (SPEC section 5), so every
proposed checklist change is reconciled against local state before it is kept.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import uuid
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import agents  # noqa: E402
import envelope as E  # noqa: E402
import transport  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config", "rally.json")
SCHEMA = os.path.join(ROOT, "schema", "envelope.json")
RUNS = os.path.join(ROOT, "runs")
LEDGER = os.path.join(RUNS, "send-ledger.json")

RULES = """You are one of two agents in a Rally run. The other agent is from a
different model family. You correspond by email and share one checklist.

The rules, which the runner enforces whether or not you follow them:
1. An item reaches "done" ONLY when the agent that does NOT own it verifies it.
   You cannot mark your own work done. Attempting it is reverted.
2. On your turn: FIRST verify every item in "awaiting-verification" that you do
   not own, THEN advance your own items.
3. To verify, set the item to "done" and put your evidence in the evidence field.
   To reject, set it back to "claimed" and say precisely what failed.
4. Never remove an item from the checklist. It may only grow.
5. Evidence means something checkable: a command that passes, a file and line,
   an observed output. Not "looks good".

Reply with a short paragraph to your counterpart, then a single fenced json block
containing the FULL updated checklist. Nothing after the block.

The envelope:
```json
{"rally_version":1,"run_id":"<RUN_ID>","turn":<TURN>,"from_agent":"<ME>",
 "narrative":"one paragraph to your counterpart",
 "checklist":[{"id":"c1","description":"...","state":"open|claimed|awaiting-verification|done|blocked|disputed",
 "owner":"claude|agy|null","verified_by":null,"evidence":"...","rejections":0}]}
```"""


def load_config(path: str = CONFIG) -> Dict:
    with open(path) as fh:
        return json.load(fh)


def now() -> str:
    return dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


class Run:
    def __init__(self, state: Dict, path: str):
        self.s = state
        self.path = path

    @classmethod
    def create(cls, task: str, workdir: str, cfg: Dict) -> "Run":
        rid = "r-%s-%s" % (dt.datetime.utcnow().strftime("%Y%m%d"), uuid.uuid4().hex[:6])
        d = os.path.join(RUNS, rid)
        os.makedirs(d, exist_ok=True)
        state = {
            "run_id": rid, "task": task, "workdir": os.path.abspath(workdir),
            "turn": 0, "actor": "claude", "checklist": [], "halt": None,
            "violations": [], "human_note": None, "digest_streak": 0,
            "last_digest": "", "created": now(), "log": [],
        }
        r = cls(state, os.path.join(d, "state.json"))
        r.save()
        return r

    @classmethod
    def load(cls, rid: str) -> "Run":
        p = os.path.join(RUNS, rid, "state.json")
        with open(p) as fh:
            return cls(json.load(fh), p)

    def save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(self.s, fh, indent=2)
        os.replace(tmp, self.path)

    def note(self, msg: str) -> None:
        self.s["log"].append("%s %s" % (now(), msg))
        print("  %s" % msg, flush=True)


def build_prompt(run: Run, actor: str, cfg: Dict) -> str:
    s = run.s
    other = "agy" if actor == "claude" else "claude"
    parts = [RULES.replace("<RUN_ID>", s["run_id"])
                  .replace("<TURN>", str(s["turn"]))
                  .replace("<ME>", actor)]
    parts.append("\nRUN: %s   TURN: %s   YOU ARE: %s   COUNTERPART: %s"
                 % (s["run_id"], s["turn"], actor, other))
    parts.append("WORKING DIRECTORY: %s (you may read and edit files here)" % s["workdir"])
    parts.append("\nTHE TASK AS COMMISSIONED:\n%s" % s["task"])

    if not s["checklist"]:
        parts.append(
            "\nThis is the scoping turn. There is no checklist yet. Do NOT start "
            "work. Produce a checklist of 3 to 6 concrete, independently "
            "verifiable items, each written so a third party could tell whether "
            "it is satisfied. Leave every item state 'open' and owner null. Your "
            "counterpart will review the scope before any work begins.")
    else:
        parts.append("\nCURRENT CHECKLIST (authoritative, from the runner):\n%s"
                     % json.dumps(s["checklist"], indent=2))
        mine = [i for i in s["checklist"]
                if i["state"] == "awaiting-verification" and i.get("owner") != actor]
        if mine:
            parts.append("\nITEMS AWAITING YOUR VERIFICATION: %s\nVerify these first."
                         % ", ".join(i["id"] for i in mine))

    if s.get("violations"):
        parts.append("\nTHE RUNNER REJECTED THESE CHANGES FROM THE LAST TURN:\n- %s\n"
                     "They were reverted. Do not repeat them."
                     % "\n- ".join(s["violations"]))
    if s.get("human_note"):
        parts.append("\nA MESSAGE FROM THE HUMAN, which takes precedence:\n%s"
                     % s["human_note"])
    return "\n".join(parts)


def git_commit(workdir: str, message: str) -> Optional[str]:
    """Best effort. A run without a git workdir still works, it just has no SHA."""
    try:
        if not os.path.isdir(os.path.join(workdir, ".git")):
            return None
        subprocess.run(["git", "add", "-A"], cwd=workdir, timeout=30,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "commit", "-m", message], cwd=workdir, timeout=30,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        p = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=workdir,
                           timeout=15, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        return p.stdout.decode().strip() or None
    except Exception:
        return None


def mail_turn(run: Run, cfg: Dict, actor: str, narrative: str, commit: Optional[str]) -> None:
    mail = cfg.get("mail", {})
    if not mail.get("enabled", True):
        return
    s = run.s
    other = "agy" if actor == "claude" else "claude"
    addrs = {k: v["address"] for k, v in cfg["agents"].items()}
    limits = cfg["limits"]
    ledger = transport.Ledger(LEDGER)
    ledger.check_and_reserve(s["run_id"], limits["sends_per_run"])
    key = transport.get_key(mail.get("keychain_service", "rally-resend"))
    body = "%s\n\n---\ncommit: %s\n\n```json\n%s\n```\n" % (
        narrative, commit or "none",
        json.dumps({"rally_version": 1, "run_id": s["run_id"], "turn": s["turn"],
                    "from_agent": actor, "commit": commit,
                    "checklist": s["checklist"]}, indent=2))
    transport.send(
        key=key, sender="Rally %s <%s>" % (actor, addrs[actor]),
        to=addrs[other], cc=mail.get("cc_human"),
        subject="[rally #%s t%s] %s" % (s["run_id"], s["turn"], s["task"][:60]),
        text=body,
        headers={"X-Rally-Run": s["run_id"], "X-Rally-Turn": str(s["turn"]),
                 "X-Rally-From": actor, "Auto-Submitted": "auto-generated"},
    )
    run.note("mailed turn %s to %s" % (s["turn"], other))


def take_turn(run: Run, cfg: Dict, dry: bool = False) -> Optional[str]:
    """One turn. Returns a halt reason, or None to continue."""
    s = run.s
    actor = s["actor"]
    limits = cfg["limits"]
    prompt = build_prompt(run, actor, cfg)
    run.note("turn %s: %s thinking (%s)" % (s["turn"], actor, cfg["agents"][actor]["model"]))

    if dry:
        raw = _stub_reply(run, actor)
    else:
        raw = agents.run_agent(actor, prompt, s["workdir"], cfg["agents"][actor],
                               limits["turn_timeout_sec"], SCHEMA)

    env = E.extract(raw)
    if env is None:
        s["violations"] = ["your last reply contained no parseable json envelope; "
                           "reply with prose then ONE fenced json block"]
        run.save()
        run.note("no envelope from %s, reprompting" % actor)
        return None

    problems = E.validate_shape(env)
    accepted, violations = E.reconcile(
        s["checklist"], env.get("checklist", []), actor, limits["rejections_max"])
    s["checklist"] = accepted
    s["violations"] = problems + violations
    if violations:
        run.note("%d illegal change(s) reverted" % len(violations))

    commit = git_commit(s["workdir"], "rally %s t%s (%s)" % (s["run_id"], s["turn"], actor))
    try:
        mail_turn(run, cfg, actor, env.get("narrative", "")[:4000], commit)
    except transport.SendBlocked as exc:
        run.note("SEND BLOCKED: %s" % exc)
        s["halt"] = {"reason": "turn_budget", "detail": str(exc)}
        run.save()
        return "send ceiling: %s" % exc

    # --- guards ------------------------------------------------------------
    d = E.digest(s["checklist"])
    s["digest_streak"] = s["digest_streak"] + 1 if d == s["last_digest"] else 0
    s["last_digest"] = d
    s["turn"] += 1
    s["actor"] = "agy" if actor == "claude" else "claude"
    run.save()

    if E.is_complete(s["checklist"]):
        return "complete"
    stuck = E.blocking(s["checklist"])
    if stuck:
        return "%s: %s" % (stuck[0]["state"], ", ".join(i["id"] for i in stuck))
    if s["turn"] >= limits["turns_max"]:
        return "turn_budget"
    if s["digest_streak"] >= limits["no_progress_halt"]:
        return "no_progress"
    return None


def _stub_reply(run: Run, actor: str) -> str:
    """Deterministic fake agent, for exercising the loop without spending tokens."""
    s = run.s
    items = list(s["checklist"])
    if not items:
        items = [{"id": "c%d" % i, "description": "stub item %d" % i, "state": "open",
                  "owner": None, "verified_by": None, "evidence": None, "rejections": 0}
                 for i in (1, 2)]
    else:
        for it in items:
            if it["state"] == "awaiting-verification" and it.get("owner") != actor:
                it["state"] = "done"
                it["evidence"] = "stub verification"
                break
            if it["state"] == "open":
                it["state"] = "claimed"
                it["owner"] = actor
                break
            if it["state"] == "claimed" and it.get("owner") == actor:
                it["state"] = "awaiting-verification"
                it["evidence"] = "stub work"
                break
    return "stub turn.\n```json\n%s\n```" % json.dumps(
        {"rally_version": 1, "run_id": s["run_id"], "turn": s["turn"],
         "from_agent": actor, "narrative": "stub", "checklist": items})


def loop(run: Run, cfg: Dict, dry: bool = False, max_turns: int = 0) -> str:
    limit = max_turns or cfg["limits"]["turns_max"]
    while run.s["turn"] < limit:
        halt = take_turn(run, cfg, dry)
        if halt:
            run.s["halt"] = run.s.get("halt") or {"reason": halt, "detail": ""}
            run.save()
            return halt
    return "turn_budget"


def cmd_check(cfg: Dict) -> int:
    print("Rally preflight")
    ok = True
    try:
        agents.assert_pins(cfg["agents"])
        for n, a in cfg["agents"].items():
            print("  %-7s %-22s family=%s" % (n, a["model"], a["family"]))
        print("  model pins: OK, two distinct families")
    except agents.AgentError as exc:
        print("  model pins: FAIL %s" % exc)
        ok = False
    for n, a in cfg["agents"].items():
        found = subprocess.run(["which", a.get("bin", n)], stdout=subprocess.PIPE)
        path = found.stdout.decode().strip()
        print("  %-7s binary: %s" % (n, path or "MISSING"))
        ok = ok and bool(path)
    try:
        transport.get_key(cfg["mail"].get("keychain_service", "rally-resend"))
        print("  resend key: present")
    except transport.SendBlocked as exc:
        print("  resend key: MISSING (%s)" % str(exc)[:70])
        print("              mail is optional; run with --no-mail to loop without it")
    print("  limits: %s" % json.dumps(cfg["limits"]))
    return 0 if ok else 1


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(prog="rally")
    ap.add_argument("--check", action="store_true", help="preflight and exit")
    ap.add_argument("--run", metavar="TASK", help="commission a run")
    ap.add_argument("--resume", metavar="RUN_ID")
    ap.add_argument("--workdir", default=".", help="where the agents work")
    ap.add_argument("--dry", action="store_true", help="stub agents, no tokens spent")
    ap.add_argument("--no-mail", action="store_true")
    ap.add_argument("--max-turns", type=int, default=0)
    a = ap.parse_args(argv)

    cfg = load_config()
    if a.no_mail:
        cfg["mail"]["enabled"] = False
    if a.check:
        return cmd_check(cfg)
    if not (a.run or a.resume):
        ap.print_help()
        return 2

    agents.assert_pins(cfg["agents"])
    os.makedirs(RUNS, exist_ok=True)
    run = Run.load(a.resume) if a.resume else Run.create(a.run, a.workdir, cfg)
    print("run %s  workdir %s" % (run.s["run_id"], run.s["workdir"]))
    halt = loop(run, cfg, a.dry, a.max_turns)
    print("\nHALT: %s after %d turns" % (halt, run.s["turn"]))
    done = sum(1 for i in run.s["checklist"] if i["state"] == "done")
    print("checklist: %d/%d done" % (done, len(run.s["checklist"])))
    for i in run.s["checklist"]:
        print("  [%s] %-22s %s" % ("x" if i["state"] == "done" else " ",
                                   i["state"], i["description"][:60]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
