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
    cmd = [cfg.get("bin", "claude"), "-p",
           "--model", cfg["model"],
           "--effort", cfg.get("effort", "high"),
           prompt]
    return _run(cmd, workdir, timeout)


def run_agy(prompt: str, workdir: str, cfg: Dict, timeout: int, schema_path: str = "") -> str:
    """Note the flag order.

    `agy` parses flags Go style, so a bare `-p` swallows the next token: written
    as `agy -p --model X "prompt"` the CLI takes `--model` as the prompt and
    silently discards the real one. The prompt must be attached as -p=... and
    must come last. Verified 2026-08-28.
    """
    effort = cfg.get("effort", "high")
    if effort not in ("low", "medium", "high"):
        effort = "high"  # agy has no rungs above high
    cmd = [cfg.get("bin", "agy"),
           "--model", cfg["model"],
           "--effort", effort,
           "--print-timeout", "%ds" % max(60, timeout - 30),
           "--dangerously-skip-permissions"]
    if schema_path:
        cmd += ["--json-schema", schema_path]
    cmd.append("-p=" + prompt)
    return _run(cmd, workdir, timeout)


DISPATCH = {"claude": run_claude, "agy": run_agy}


def run_agent(name: str, prompt: str, workdir: str, cfg: Dict, timeout: int,
              schema_path: str = "") -> str:
    if name == "agy":
        return run_agy(prompt, workdir, cfg, timeout, schema_path)
    return run_claude(prompt, workdir, cfg, timeout)
