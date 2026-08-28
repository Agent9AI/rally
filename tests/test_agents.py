"""Both agents must be able to *execute*, or the verification invariant is a fiction.

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

_ROOT = os.path.join(os.path.dirname(__file__), "..")
with open(os.path.join(_ROOT, "config", "rally.json")) as _fh:
    CFG = json.load(_fh)["agents"]

# Anything here means "this process may run commands without stopping to ask".
EXEC_FLAGS = ("--dangerously-skip-permissions", "--allow-dangerously-skip-permissions")


def capture(name, cfg=None):
    """Build the argv an adapter would run, without running it."""
    seen = {}

    def fake_run(cmd, workdir, timeout):
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

    def test_both_sides_equally_capable(self):
        """Neither agent may be the privileged one. Asymmetry biases who can verify."""
        c = any(f in capture("claude") for f in EXEC_FLAGS)
        a = any(f in capture("agy") for f in EXEC_FLAGS)
        self.assertEqual(c, a, "one agent can execute and the other cannot")


class TestModelPinning(unittest.TestCase):
    def test_pins_survive_into_argv(self):
        self.assertIn("opus", capture("claude"))
        self.assertIn("gemini-3.1-pro-high", capture("agy"))

    def test_agy_prompt_is_last_and_glued(self):
        """`agy` parses Go style: a bare `-p` swallows the next token, so an
        unglued prompt silently makes `--model` the prompt."""
        cmd = capture("agy")
        self.assertTrue(cmd[-1].startswith("-p="), cmd[-1][:60])
        self.assertNotIn("-p", cmd[:-1], "a bare -p would swallow the next flag")


if __name__ == "__main__":
    unittest.main()
