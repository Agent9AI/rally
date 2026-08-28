"""The two CLI connections.

Both adapters do the same three things: build a command, run it with a hard
timeout, return stdout. Everything model-specific is a flag, which is why adding
a third family later is a function rather than an architecture.
"""
from __future__ import annotations

import subprocess
from typing import Dict, List, Tuple


class AgentError(RuntimeError):
    pass


def assert_pins(agents: Dict[str, Dict]) -> None:
    """Refuse to run two agents from the same model family.

    The Antigravity CLI also serves Claude models, so an unpinned run can quietly
    become one family reviewing itself while every log line still looks healthy.
    That failure invalidates the premise of the whole system, so it is checked
    before a run starts rather than trusted to configuration.
    """
    fams = [(name, a.get("family"), a.get("model")) for name, a in agents.items()]
    seen: Dict[str, str] = {}
    for name, fam, model in fams:
        if not fam:
            raise AgentError("agent %s has no declared family" % name)
        if fam in seen:
            raise AgentError(
                "same-family pair: %s (%s) and %s (%s) are both %s. "
                "Rally needs two different model families." % (name, model, seen[fam], fams, fam)
            )
        seen[fam] = name
    # Execution symmetry. Discovered on the first live run: agy carried
    # --dangerously-skip-permissions and claude carried nothing, so claude could
    # only read source. It still recorded items as "done", which makes the
    # verification invariant a fiction rather than a check. Neither agent may be
    # the privileged one.
    caps = {n: bool(a.get("exec_flags")) for n, a in agents.items()}
    if len(set(caps.values())) > 1:
        able = [n for n, v in caps.items() if v]
        unable = [n for n, v in caps.items() if not v]
        raise AgentError(
            "execution asymmetry: %s can run commands, %s cannot. The agent that "
            "cannot execute can only read source, so its verification is a weaker "
            "claim than the one recorded. Give both agents exec_flags, or neither."
            % (", ".join(able), ", ".join(unable)))

    agy = agents.get("agy", {})
    if agy and not str(agy.get("model", "")).startswith("gemini-"):
        raise AgentError(
            "agy model %r is not a gemini model. The Antigravity CLI also serves "
            "Claude models; pin it to gemini-* or the run is single-family."
            % agy.get("model")
        )


def _run(cmd: List[str], workdir: str, timeout: int) -> str:
    try:
        p = subprocess.run(
            cmd, cwd=workdir, timeout=timeout, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
    except subprocess.TimeoutExpired:
        raise AgentError("turn exceeded %ds" % timeout)
    out = p.stdout.decode("utf-8", errors="replace")
    if p.returncode != 0:
        raise AgentError("exit %d: %s" % (p.returncode, out[-800:]))
    return out


def run_claude(prompt: str, workdir: str, cfg: Dict, timeout: int) -> str:
    """Note the permission flag, which is load-bearing rather than convenience.

    Without it every command claude tries is approval-gated, and since nobody is
    at a terminal to approve, claude can read source but can never *run* anything.
    It can therefore never produce the second, independent execution that rule 1
    requires, so agy's work could only ever be verified by reading. The first live
    run stalled precisely there and the agents wrote the diagnosis into the
    checklist themselves (r-20260828-cf40c3, item c8).

    `agy` has carried `--dangerously-skip-permissions` from the start. Matching it
    here is what makes the two sides equally capable; the asymmetry, not the
    permission, was the bug. Both agents are pointed at a scratch workdir.
    """
    if cfg.get("adapter") == "agy":
        agy_cfg = dict(cfg)
        agy_cfg.pop("effort", None)
        return run_agy(prompt, workdir, agy_cfg, timeout)
    cmd = [cfg.get("bin", "claude"), "-p",
           "--model", cfg["model"],
           "--effort", cfg.get("effort", "high")]
    # Read from config exactly as run_agy does. Hardcoding the flag here made
    # config/rally.json able to lie: assert_pins decides symmetry from exec_flags,
    # so removing claude's entry would abort the run as "asymmetric" while this
    # function still passed the flag. One source, and the assertion means what it says.
    cmd += list(cfg.get("exec_flags") or [])
    cmd.append(prompt)
    return _run(cmd, workdir, timeout)


def run_agy(prompt: str, workdir: str, cfg: Dict, timeout: int, schema_path: str = "") -> str:
    """Note the flag order.

    `agy` parses flags Go style, so a bare `-p` swallows the next token: written
    as `agy -p --model X "prompt"` the CLI takes `--model` as the prompt and
    silently discards the real one. The prompt must be attached as -p=... and
    must come last. Verified 2026-08-28.
    """
    cmd = [cfg.get("bin", "agy"), "--model", cfg["model"]]
    effort = cfg.get("effort")
    if effort in ("low", "medium", "high"):
        cmd += ["--effort", effort]
    cmd += ["--print-timeout", "%ds" % max(60, timeout - 30)]
    cmd += list(cfg.get("exec_flags") or [])
    # `--json-schema` is refused unless --output-format is json/stream-json, which
    # changes the whole reply shape. The runner's reconcile() is the real
    # enforcement, so the schema stays opt-in rather than on by default.
    if schema_path:
        cmd += ["--output-format", "json", "--json-schema", schema_path]
    cmd.append("-p=" + prompt)
    return _run(cmd, workdir, timeout)


DISPATCH = {"claude": run_claude, "agy": run_agy}


def run_agent(name: str, prompt: str, workdir: str, cfg: Dict, timeout: int,
              schema_path: str = "") -> str:
    if name == "agy":
        return run_agy(prompt, workdir, cfg, timeout, schema_path)
    return run_claude(prompt, workdir, cfg, timeout)
