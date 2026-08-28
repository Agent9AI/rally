"""Rally runner: holds authoritative state, dispatches turns, enforces the limits.

The runner is the authority. An envelope is evidence (SPEC section 5), so every
proposed checklist change is reconciled against local state before it is kept.
"""
from __future__ import annotations

import argparse
import datetime as dt
import time
import json
import os
import subprocess
import sys
import uuid
import html as html_lib
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import agents  # noqa: E402
import envelope as E  # noqa: E402
import report  # noqa: E402
import transport  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config", "rally.json")
SCHEMA = os.path.join(ROOT, "schema", "envelope.json")
RUNS = os.path.join(ROOT, "runs")
LEDGER = os.path.join(RUNS, "send-ledger.json")
MAIL_DOMAIN = "updates.agent9.dev"

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

Write a concise, executive-quality update: lead with the outcome, then state
evidence, risk or decision needed, and the next action. Use short paragraphs or
labeled lines, no greeting, sign-off, filler, tool trace, or speculation. Address
the counterpart as a senior operator who needs a clear decision record. Then a
single fenced json block
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


def watermark(run_id: str, turn: str, sender: str, recipient: str) -> str:
    return ("RALLY WATERMARK | run %s | turn %s | %s -> %s"
            % (run_id, turn, sender, recipient))


def subject_fragment(task: str) -> str:
    return " ".join((task or "").split())[:60]


def executive_html(title: str, run_id: str, turn: str, sender: str,
                   recipient: str, status: str, prose: str,
                   technical: str = "") -> str:
    esc = html_lib.escape
    paragraphs = "".join(
        "<p>%s</p>" % esc(part.strip()).replace("\n", "<br>")
        for part in prose.split("\n\n") if part.strip()
    )
    record = ("<details style=\"margin-top:24px\"><summary style=\"color:#5b6470;"
              "cursor:pointer;font-size:12px;letter-spacing:.04em;text-transform:uppercase\">"
              "Technical record</summary><pre style=\"white-space:pre-wrap;overflow-wrap:anywhere;"
              "background:#f3f1ee;border:1px solid #e4e2df;border-radius:8px;padding:14px;"
              "font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;color:#1f2328\">%s</pre></details>"
              % esc(technical)) if technical else ""
    return """<!doctype html><html><body style="margin:0;background:#f5f4f2;color:#1f2328;
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
<div style="padding:32px 14px"><div style="max-width:600px;margin:auto;background:#fffefc;
border:1px solid #e4e2df;border-radius:12px;overflow:hidden;box-shadow:0 3px 14px rgba(31,35,40,.06)">
<div style="padding:24px 28px 18px;border-bottom:1px solid #e4e2df">
<div style="font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:#0b57d0;font-weight:700">Rally</div>
<div style="font-size:24px;line-height:1.25;font-weight:650;margin-top:8px">%s</div>
<div style="display:inline-block;margin-top:14px;padding:5px 10px;border-radius:999px;background:#e9f2ff;color:#0b57d0;font-size:12px;font-weight:650">%s</div>
</div><div style="padding:24px 28px"><table style="width:100%%;font-size:12px;color:#5b6470;border-collapse:collapse">
<tr><td style="padding:0 0 8px">RUN</td><td style="padding:0 0 8px;text-align:right;color:#1f2328">%s</td></tr>
<tr><td style="padding:0 0 8px">TURN</td><td style="padding:0 0 8px;text-align:right;color:#1f2328">%s</td></tr>
<tr><td style="padding:0">FROM</td><td style="padding:0;text-align:right;color:#1f2328">%s</td></tr>
<tr><td style="padding:8px 0 0">TO</td><td style="padding:8px 0 0;text-align:right;color:#1f2328">%s</td></tr>
</table><div style="height:1px;background:#e4e2df;margin:22px 0"> </div>
<div style="font-size:15px;line-height:1.7">%s</div>%s</div>
<div style="padding:16px 28px;background:#f8f7f5;color:#8b949e;font-size:11px;line-height:1.5">
%s</div></div></div></body></html>""" % (
        esc(title), esc(status), esc(run_id), esc(turn), esc(sender), esc(recipient),
        paragraphs, record, esc(watermark(run_id, turn, sender, recipient)))


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
            "thread_message_id": None, "thread_references": [],
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
    parts.append(
        "WORKING DIRECTORY: %s\n"
        "Create and edit files ONLY inside that directory. Do not write anywhere "
        "else on this machine, and never into Rally's own source tree. If the task "
        "seems to need a change outside the working directory, do not make it: say "
        "so in your narrative and mark the item blocked." % s["workdir"])
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


def repo_fingerprint(path: str = ROOT) -> str:
    """Cheap snapshot of a tree, for detecting writes outside the workdir.

    Observed on the first live run: an agent working in /tmp wrote a new test file
    into the Rally source repo. The runner sets cwd but does not sandbox, so the
    only honest posture is to detect the escape and say so.
    """
    try:
        p = subprocess.run(["git", "status", "--porcelain"], cwd=path, timeout=20,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        return p.stdout.decode(errors="replace")
    except Exception:
        return ""


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
    human = s.get("commissioned_by") or mail.get("cc_human")
    limits = cfg["limits"]
    ledger = transport.Ledger(LEDGER)
    ledger.check_and_reserve(s["run_id"], limits["sends_per_run"])
    key = transport.get_key(mail.get("keychain_service", "rally-resend"))
    body = "%s\n\n---\ncommit: %s\n\n```json\n%s\n```\n" % (
        narrative, commit or "none",
        json.dumps({"rally_version": 1, "run_id": s["run_id"], "turn": s["turn"],
                    "from_agent": actor, "commit": commit,
                    "checklist": s["checklist"]}, indent=2))
    sender_address = addrs[actor]
    recipient_address = addrs[other]
    body = ("RALLY EXECUTIVE UPDATE\n"
            "Run: %s\nTurn: %s\nFrom: %s\nTo: %s\nStatus: In progress\n\n"
            "%s\n\n"
            "TECHNICAL RECORD\n%s\n\n%s\n" %
            (s["run_id"], s["turn"], sender_address, recipient_address,
             narrative.strip(), body, watermark(s["run_id"], str(s["turn"]),
                                                 sender_address, recipient_address)))
    html = executive_html("Executive update", s["run_id"], str(s["turn"]),
                          sender_address, recipient_address, "In progress",
                          narrative.strip(), body)
    message_id = "<%s-%s-%s@%s>" % (s["run_id"], s["turn"], actor, MAIL_DOMAIN)
    prior = s.get("thread_message_id")
    references = list(s.get("thread_references") or [])
    if prior and prior not in references:
        references.append(prior)
    headers = {"X-Rally-Run": s["run_id"], "X-Rally-Turn": str(s["turn"]),
               "X-Rally-From": actor, "Auto-Submitted": "auto-generated",
               "Message-ID": message_id}
    if prior:
        headers["In-Reply-To"] = prior
    if references:
        headers["References"] = " ".join(references)
    transport.send(
        key=key, sender="Rally %s <%s>" % (actor, sender_address),
        to=recipient_address, cc=human,
        subject="[rally #%s] %s" % (s["run_id"], subject_fragment(s["task"])),
        text=body,
        html=html,
        headers=headers,
    )
    s["thread_message_id"] = message_id
    s["thread_references"] = references + [message_id]
    run.note("mailed turn %s to %s" % (s["turn"], other))


def write_report(run: Run, cfg: Dict, halt: str, dry: bool = False) -> str:
    """The agent holding the turn writes it. The runner keeps a correct fallback."""
    s = run.s
    if dry:
        return report.mechanical_summary(s, halt)
    actor = s["actor"]
    try:
        raw = agents.run_agent(actor, report.build_report_prompt(s, halt), s["workdir"],
                               cfg["agents"][actor], 420, "")
        text = raw.strip()
        if len(text) < 80:
            raise agents.AgentError("report too short to be real")
        run.note("report written by %s" % actor)
        return text
    except agents.AgentError as exc:
        run.note("report generation failed (%s), sending the mechanical summary" % exc)
        return report.mechanical_summary(s, halt)


def mail_report(run: Run, cfg: Dict, text: str, halt: str) -> None:
    mail = cfg.get("mail", {})
    human = run.s.get("commissioned_by") or mail.get("cc_human")
    if not mail.get("enabled", True) or not human:
        return
    s = run.s
    actor = s["actor"]
    status = report.classify(halt)[0]
    ledger = transport.Ledger(LEDGER)
    ledger.check_and_reserve(s["run_id"], cfg["limits"]["sends_per_run"])
    key = transport.get_key(mail.get("keychain_service", "rally-resend"))
    message_id = "<%s-report@%s>" % (s["run_id"], MAIL_DOMAIN)
    prior = s.get("thread_message_id")
    references = list(s.get("thread_references") or [])
    if prior and prior not in references:
        references.append(prior)
    headers = {"X-Rally-Run": s["run_id"], "X-Rally-Report": status,
               "Auto-Submitted": "auto-generated", "Message-ID": message_id}
    if prior:
        headers["In-Reply-To"] = prior
    if references:
        headers["References"] = " ".join(references)
    transport.send(
        key=key,
        sender="Rally %s <%s>" % (actor, cfg["agents"][actor]["address"]),
        to=human,
        subject="[rally #%s] %s" % (s["run_id"], subject_fragment(s["task"])),
        text=("RALLY EXECUTIVE REPORT\n"
              "Run: %s\nFrom: %s\nStatus: %s\n\n%s\n\n%s\n"
              "Workdir: %s\n" %
              (s["run_id"], cfg["agents"][actor]["address"], status,
               text.strip(), watermark(s["run_id"], "report",
                                       cfg["agents"][actor]["address"], human),
               s["workdir"])),
        html=executive_html("Executive report", s["run_id"], "report",
                            cfg["agents"][actor]["address"], human, status,
                            text.strip()),
        headers=headers,
    )
    s["thread_message_id"] = message_id
    s["thread_references"] = references + [message_id]
    run.save()
    run.note("report mailed to %s" % human)


def take_turn(run: Run, cfg: Dict, dry: bool = False) -> Optional[str]:
    """One turn. Returns a halt reason, or None to continue."""
    s = run.s
    actor = s["actor"]
    limits = cfg["limits"]
    note = (s.get("human_note") or "").strip()
    if note.upper().startswith("STOP"):
        # The kill switch must not require the agents to cooperate, so it is
        # checked by the runner before a turn is dispatched.
        s["halt"] = {"reason": "stopped_by_human", "detail": note}
        run.save()
        return "stopped_by_human"
    prompt = build_prompt(run, actor, cfg)
    run.note("turn %s: %s thinking (%s)" % (s["turn"], actor, cfg["agents"][actor]["model"]))

    before = "" if dry else repo_fingerprint()
    if dry:
        raw = _stub_reply(run, actor)
    else:
        schema = SCHEMA if cfg["agents"][actor].get("use_schema") else ""
        try:
            raw = agents.run_agent(actor, prompt, s["workdir"], cfg["agents"][actor],
                                   limits["turn_timeout_sec"], schema)
        except agents.AgentError as exc:
            detail = "%s turn failed: %s" % (actor, exc)
            s["halt"] = {"reason": "agent_error", "detail": detail}
            run.note("AGENT FAILED: %s" % detail)
            run.save()
            return "agent_error"

    if not dry and os.path.abspath(s["workdir"]) != ROOT:
        after = repo_fingerprint()
        if after != before:
            # Report the paths, not just "something changed". This check cannot
            # distinguish an agent's write from an operator editing the repo in
            # another window during the same turn, so the paths are what make it
            # actionable rather than alarming. Advisory, not authoritative.
            changed = sorted(set(after.splitlines()) - set(before.splitlines()))
            paths = [ln[3:] for ln in changed] or ["(unknown)"]
            msg = ("containment: repo tree changed during %s's turn: %s. "
                   "If that was not you editing, the agent wrote outside %s."
                   % (actor, ", ".join(paths[:6]), s["workdir"]))
            run.note(msg)
            s.setdefault("containment", []).append(
                {"turn": s["turn"], "actor": actor, "paths": paths})
            s["violations"] = (s.get("violations") or []) + [msg]

    env = E.extract(raw)
    if env is None:
        s["violations"] = ["your last reply contained no parseable json envelope; "
                           "reply with prose then ONE fenced json block"]
        run.save()
        run.note("no envelope from %s, reprompting" % actor)
        return None

    problems = E.validate_shape(env)
    # Scope closes after negotiation: turn 0 scopes, turn 1 negotiates.
    accepted, violations = E.reconcile(
        s["checklist"], env.get("checklist", []), actor, limits["rejections_max"],
        allow_new=(s["turn"] <= 1))
    s["checklist"] = accepted
    carried = [v for v in (s.get("violations") or []) if v.startswith("containment:")]
    s["violations"] = carried + problems + violations
    if violations:
        run.note("%d illegal change(s) reverted" % len(violations))

    s["human_note"] = None  # delivered with this turn's prompt, do not repeat it
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
    # Deep copy. list() aliases the dicts, so the stub would mutate authoritative
    # state in place and reconcile would see done -> done and pass it straight
    # through, leaving verified_by unset. The offline demo then displays finished
    # items with no verifier, which is the opposite of what it exists to show.
    items = json.loads(json.dumps(s["checklist"]))
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


def new_workspace(run_id: str) -> str:
    """Every commissioned run gets its own git-initialised tree.

    Isolation is what makes the containment check meaningful, and the branch is
    what makes figure 1's commit SHA real.
    """
    ws = os.path.join(RUNS, run_id, "workspace")
    os.makedirs(ws, exist_ok=True)
    if not os.path.isdir(os.path.join(ws, ".git")):
        for cmd in (["git", "init", "-q"],
                    ["git", "commit", "-q", "--allow-empty", "-m", "rally: %s" % run_id]):
            subprocess.run(cmd, cwd=ws, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=30)
    return ws


def handle_commission(cfg: Dict, task: str, sender: str, message_id: Optional[str] = None) -> str:
    run = Run.create(task, ".", cfg)
    run.s["workdir"] = new_workspace(run.s["run_id"])
    run.s["commissioned_by"] = sender
    if message_id:
        run.s["thread_message_id"] = message_id
        run.s["thread_references"] = [message_id]
    run.save()
    print("commissioned %s by %s" % (run.s["run_id"], sender))
    halt = loop(run, cfg)
    text = write_report(run, cfg, halt)
    run.s["report"] = text
    run.save()
    try:
        mail_report(run, cfg, text, halt)
    except transport.SendBlocked as exc:
        run.note("report not mailed: %s" % exc)
    return run.s["run_id"]


def handle_note(cfg: Dict, run_id: str, text: str, message_id: Optional[str] = None) -> None:
    try:
        run = Run.load(run_id)
    except IOError:
        print("note for unknown run %s, dropped" % run_id)
        return
    run.s["human_note"] = text
    if message_id:
        prior = run.s.get("thread_message_id")
        refs = list(run.s.get("thread_references") or [])
        if prior and prior not in refs:
            refs.append(prior)
        run.s["thread_message_id"] = message_id
        run.s["thread_references"] = refs + [message_id]
    run.save()
    if text.strip().upper().startswith("STOP"):
        run.s["halt"] = {"reason": "stopped_by_human", "detail": text}
        run.save()
        print("run %s stopped by human" % run_id)
        report_text = report.mechanical_summary(run.s, "stopped_by_human")
        try:
            mail_report(run, cfg, report_text, "stopped_by_human")
        except transport.SendBlocked:
            pass
        return
    print("note delivered to %s, resuming" % run_id)
    halt = loop(run, cfg)
    text_out = write_report(run, cfg, halt)
    run.s["report"] = text_out
    run.save()
    try:
        mail_report(run, cfg, text_out, halt)
    except transport.SendBlocked:
        pass


def serve(cfg: Dict, once: bool = False) -> int:
    """Poll the ingress Worker and act on what arrives."""
    import ingress

    interval = cfg["ingress"].get("poll_interval_sec", 20)
    print("rally serving: commission address %s, polling %s every %ds"
          % (cfg["ingress"]["commission_address"], cfg["ingress"]["worker_url"], interval))
    while True:
        try:
            messages = ingress.collect(cfg)
        except Exception as exc:  # a poll failure must never kill the daemon
            print("poll failed: %s" % exc)
            if once:
                return 1
            time.sleep(interval)
            continue

        handled: List[str] = []
        for m in messages:
            kind = m.get("kind")
            detail = m.get("detail") or {}
            try:
                if kind == "commission":
                    handle_commission(cfg, detail["task"], detail["sender"], detail.get("message_id"))
                elif kind == "note":
                    handle_note(cfg, detail["run_id"], detail["text"], detail.get("message_id"))
                else:
                    print("ignored: %s" % (detail.get("why") or m.get("error")))
            except Exception as exc:
                print("handling %s failed: %s" % (m.get("id"), exc))
            handled.append(m["id"])
        ingress.ack(cfg, handled)
        if once:
            return 0
        time.sleep(interval)


def smoke_agents(cfg: Dict) -> bool:
    """Actually invoke both agents with a trivial prompt.

    A config can name a model the CLI cannot serve, and every static check still
    passes: the binary exists, the pins differ, the families differ. The run then
    dies on turn 0 with "Agent execution terminated due to error." Found the hard
    way when a Claude model routed through the Antigravity CLI stopped being
    served. The only honest preflight is to make each agent answer.
    """
    ok = True
    for name, a in cfg["agents"].items():
        try:
            out = agents.run_agent(name, "Reply with only: OK", "/tmp", a, 120, "")
            good = "OK" in (out or "")
            print("  %-7s live probe: %s (%s)"
                  % (name, "responds" if good else "ODD REPLY", a["model"]))
            ok = ok and good
        except agents.AgentError as exc:
            print("  %-7s live probe: FAILED (%s) %s"
                  % (name, a["model"], str(exc)[:70]))
            ok = False
    return ok


def cmd_check(cfg: Dict, smoke: bool = False) -> int:
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
    ing = cfg.get("ingress", {})
    base = (ing.get("worker_url") or "").rstrip("/")
    print("  commission address: %s" % ing.get("commission_address", "(unset)"))
    print("  owners: %s" % ", ".join(ing.get("owners", [])) or "(none)")
    if base:
        try:
            import urllib.request
            hreq = urllib.request.Request(
                base + "/health", headers={"User-Agent": transport.USER_AGENT})
            with urllib.request.urlopen(hreq, timeout=10) as r:
                json.load(r)
            print("  ingress worker: reachable (%s)" % base)
        except Exception as exc:
            print("  ingress worker: UNREACHABLE %s" % str(exc)[:60])
            ok = False
        try:
            tok = transport.get_key(ing.get("poll_token_keychain", "rally-poll-token"))
            req = urllib.request.Request(
                base + "/pending",
                headers={"Authorization": "Bearer " + tok,
                         "User-Agent": transport.USER_AGENT})
            with urllib.request.urlopen(req, timeout=10) as r:
                n = len(json.load(r).get("messages", []))
            print("  ingress queue: %d message(s) waiting" % n)
            if n == 0:
                print("            if you sent mail and this is 0, Resend is not")
                print("            routing %s to the Worker yet"
                      % ing.get("commission_address"))
        except transport.SendBlocked:
            print("  ingress queue: no poll token in the keychain")
        except Exception as exc:
            print("  ingress queue: %s" % str(exc)[:60])
    print("  limits: %s" % json.dumps(cfg["limits"]))
    if smoke:
        ok = smoke_agents(cfg) and ok
    return 0 if ok else 1


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(prog="rally")
    ap.add_argument("--check", action="store_true", help="preflight and exit")
    ap.add_argument("--smoke", action="store_true",
                    help="with --check, actually invoke both agents (slower, definitive)")
    ap.add_argument("--config", default=CONFIG,
                    help="config file (use config/rally.demo.json for fast live demos)")
    ap.add_argument("--run", metavar="TASK", help="commission a run")
    ap.add_argument("--resume", metavar="RUN_ID")
    ap.add_argument("--workdir", default=None,
                    help="where the agents work (default: an isolated workspace)")
    ap.add_argument("--dry", action="store_true", help="stub agents, no tokens spent")
    ap.add_argument("--no-mail", action="store_true")
    ap.add_argument("--max-turns", type=int, default=0)
    ap.add_argument("--serve", action="store_true",
                    help="poll the ingress Worker and run what arrives")
    ap.add_argument("--once", action="store_true", help="with --serve, one pass only")
    ap.add_argument("--note", metavar="TEXT",
                    help="inject guidance into the next turn; STOP halts the run")
    a = ap.parse_args(argv)

    a.workdir_given = a.workdir is not None
    if a.workdir is None:
        a.workdir = "."
    cfg = load_config(a.config)
    if a.no_mail:
        cfg["mail"]["enabled"] = False
    if a.check:
        return cmd_check(cfg, a.smoke)
    if a.serve:
        agents.assert_pins(cfg["agents"])
        return serve(cfg, a.once)
    if not (a.run or a.resume):
        ap.print_help()
        return 2

    agents.assert_pins(cfg["agents"])
    os.makedirs(RUNS, exist_ok=True)
    if a.resume:
        run = Run.load(a.resume)
    else:
        run = Run.create(a.run, a.workdir, cfg)
        if not a.workdir_given:
            # Default to an isolated, git-initialised workspace. Isolation is what
            # makes the containment check meaningful and the per-turn commit real.
            run.s["workdir"] = new_workspace(run.s["run_id"])
            run.save()
    if a.note:
        run.s["human_note"] = a.note
        run.save()
    print("run %s  workdir %s" % (run.s["run_id"], run.s["workdir"]))
    halt = loop(run, cfg, a.dry, a.max_turns)

    status = report.classify(halt)[0]
    done = sum(1 for i in run.s["checklist"] if i["state"] == "done")
    print("\n%s: %s after %d turns, %d/%d verified"
          % (status, halt, run.s["turn"], done, len(run.s["checklist"])))

    text = write_report(run, cfg, halt, a.dry)
    run.s["report"] = text
    run.save()
    try:
        mail_report(run, cfg, text, halt)
    except transport.SendBlocked as exc:
        run.note("report not mailed: %s" % exc)
    print("\n" + "=" * 62 + "\n" + text + "\n" + "=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
