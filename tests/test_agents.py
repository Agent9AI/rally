"""Every worker must be able to *execute*, or verification is a fiction.

Rule 1 says an item reaches `done` only when the agent that did not do the work
verifies it. Verification that cannot run a command is source reading, which is a
weaker claim and, worse, one the system still records as `done`.

The first live run stalled on exactly this: `agy` carried
`--dangerously-skip-permissions` and `claude` carried no permission flag at all, so
claude could never produce a second execution. The agents noticed and wrote it into
the checklist themselves (run r-20260828-cf40c3, item c8):

    claude cannot produce a second, independent execution because every python3
    invocation in claude's sandbox is approval-gated.

These tests exist so that asymmetry cannot come back silently.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import agents as A


# Assert against the SHIPPED config, not a fixture. A fixture would pass while
# the real configuration was asymmetric, which is exactly the bug these tests exist
# to catch. (Originally written by claude during run r-20260828-cf40c3; rewritten
# to read the real config once exec_flags moved out of the adapters.)
import json
import tempfile

_ROOT = os.path.join(os.path.dirname(__file__), "..")
with open(os.path.join(_ROOT, "config", "rally.json")) as _fh:
    CFG = json.load(_fh)["agents"]

EXEC_FLAGS = (
    "--dangerously-skip-permissions",
    "--allow-dangerously-skip-permissions",
    "--approve-for-me",
)


def capture(name, cfg=None):
    """Build the argv an adapter would run, without running it."""
    seen = {}

    def fake_run(cmd, workdir, timeout, extra_env=None):
        seen["cmd"] = cmd
        return "{}"

    real, A._run = A._run, fake_run
    try:
        A.run_agent(name, "do the thing", "/tmp/rally-scratch",
                    (cfg or CFG)[name], 60)
    finally:
        A._run = real
    return seen["cmd"]


class TestExecutionSymmetry(unittest.TestCase):
    def test_claude_can_execute(self):
        cmd = capture("claude")
        self.assertTrue(
            any(f in cmd for f in EXEC_FLAGS),
            "claude has no execution permission, so it can only review source and "
            "can never independently verify agy's work: %r" % (cmd,))

    def test_agy_can_execute(self):
        cmd = capture("agy")
        self.assertTrue(any(f in cmd for f in EXEC_FLAGS), repr(cmd))

    def test_codex_can_execute_inside_its_workspace(self):
        cmd = capture("codex")
        self.assertIn("--approve-for-me", cmd)

    def test_both_sides_equally_capable(self):
        """Neither agent may be the privileged one. Asymmetry biases who can verify."""
        capabilities = {
            name: any(flag in capture(name) for flag in EXEC_FLAGS)
            for name in CFG
        }
        self.assertEqual(set(capabilities.values()), {True}, capabilities)

    def test_optional_grok_worker_is_headless_and_profile_isolated(self):
        cfg = {
            **CFG,
            "grok": {
                "adapter": "grok",
                "bin": "grok",
                "model": "grok-build",
                "family": "xai",
                "profile_home": "/tmp/rally-grok-profile",
                "exec_flags": ["--always-approve"],
            },
        }
        cmd = capture("grok", cfg)
        for flag in (
            "--no-auto-update", "--no-plan", "--no-subagents",
            "--no-memory", "--disable-web-search", "--always-approve",
        ):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[-2:], ["-p", "do the thing"])
        A.assert_pins(cfg)

    def test_grok_refuses_default_profile_and_unisolated_connectors(self):
        base = {
            "adapter": "grok", "bin": "grok", "model": "grok-build",
            "family": "xai", "exec_flags": ["--always-approve"],
        }
        with self.assertRaisesRegex(A.AgentError, "dedicated profile_home"):
            A.run_agent("grok", "test", "/tmp", base, 60)
        with self.assertRaisesRegex(A.AgentError, "connector isolation"):
            A.run_agent("grok", "test", "/tmp", {
                **base,
                "profile_home": "/tmp/rally-grok-profile",
                "mcp_config_path": "/tmp/rally-mcp.json",
            }, 60)


class TestModelPinning(unittest.TestCase):
    def test_pins_survive_into_argv(self):
        self.assertTrue(any("opus" in arg for arg in capture("claude")))
        self.assertIn("gemini-3.1-pro-high", capture("agy"))
        self.assertIn("gpt-5.4", capture("codex"))

    def test_agy_prompt_is_last_and_glued(self):
        """`agy` parses Go style: a bare `-p` swallows the next token, so an
        unglued prompt silently makes `--model` the prompt."""
        cmd = capture("agy")
        self.assertTrue(cmd[-1].startswith("-p="), cmd[-1][:60])
        self.assertNotIn("-p", cmd[:-1], "a bare -p would swallow the next flag")

    def test_codex_is_ephemeral_and_does_not_load_global_mcp_config(self):
        cmd = capture("codex")
        self.assertIn("--ephemeral", cmd)
        self.assertIn("--ignore-user-config", cmd)
        self.assertIn("--skip-git-repo-check", cmd)
        self.assertIn("--output-last-message", cmd)

        with tempfile.TemporaryDirectory() as directory:
            mcp_path = os.path.join(directory, "mcp.json")
            with open(mcp_path, "w") as handle:
                json.dump({"mcpServers": {"rally-connectors": {
                    "command": "/rally/bin/rally-connectors",
                    "args": [],
                    "env": {"RALLY_CONNECTOR_POLICY": "/private/policy.json"},
                }}}, handle)
            cfg = {name: dict(value) for name, value in CFG.items()}
            cfg["codex"]["mcp_config_path"] = mcp_path
            isolated = capture("codex", cfg)
        override = isolated[isolated.index("-c") + 1]
        self.assertIn("mcp_servers.rally-connectors", override)
        self.assertIn("/private/policy.json", override)

    def test_all_shipped_workers_have_distinct_families(self):
        A.assert_pins(CFG)
        self.assertEqual({cfg["family"] for cfg in CFG.values()}, {
            "anthropic", "google", "openai",
        })


if __name__ == "__main__":
    unittest.main()
