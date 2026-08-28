# What the first live run exposed

Run `r-20260828-cf40c3`, 8 turns, two live CLIs, a deliberately trivial task
(write `greet.py` and a test). The task was trivial precisely so that anything
that went wrong would be about Rally rather than about the work.

Four things went wrong. Three were bugs in Rally. All four are now guarded by
tests, because a design document cannot find any of them.

## 1. `--json-schema` is refused without `--output-format json`

The spec's Antigravity invocation was wrong twice over: a bare `-p` swallows the
next token under Go-style flag parsing, and `--json-schema` is rejected unless
the output format is also set. The first failure is silent, which is worse: the
CLI takes `--model` as the prompt and answers a question nobody asked.

**Now:** the prompt is glued as `-p=...` and comes last, asserted by a test that
inspects the built argv. The schema is opt-in, because `reconcile()` is the real
enforcement and the schema was only belt-and-braces.

## 2. The state machine was stricter than reality

Rally required `open → claimed → awaiting-verification` as separate turns. On its
first turn `agy` claimed and completed five items, which is exactly what a
competent agent should do, and the runner reverted all five as illegal.

That was a Rally bug, not an agent error, and an expensive one: it would have
doubled the turn count and the send spend for every run.

**Now:** claiming and working in one turn is legal. Only reaching `done` requires
the other agent, which is the invariant that actually matters.

## 3. Verification was a fiction on one side

The important one. `run_agy` passed `--dangerously-skip-permissions` and
`run_claude` passed no permission flag at all. So `agy` could execute commands
and `claude` could not.

Claude verified four items anyway, and recorded them as `done`, with evidence
that began:

> `SOURCE-LEVEL VERIFICATION (execution blocked on my side)`

It read the files and reasoned carefully about the bytes. That is real work, and
it is not what `done` claimed. The system recorded a stronger fact than it held.

The agents noticed before the operator did. They added checklist items for it,
marked one `blocked`, and wrote the blocking observation into the run:

> claude cannot produce a second, independent execution because every python3
> invocation in claude's sandbox is approval-gated.

**Now:** execution capability is declared per agent in config, and startup
refuses to run an asymmetric pair. An agent that cannot execute can only read
source, so its verification is weaker than the `done` it records, and Rally will
not pretend otherwise.

**The general lesson:** capability asymmetry silently degrades verification into
review while every log line still looks healthy. It is the same failure class as
an unpinned model, and it needs the same treatment: assert it at startup.

## 4. The checklist grew instead of finishing

Five agreed items became eight. The new ones were "independent re-execution of
c1, c3 and c4", "byte-level verification", and an unassignable open question. The
agents had begun verifying the verification.

Rally's own rule enabled it: a checklist may only grow, never shrink, which was
meant to stop an agent quietly dropping work it could not do. The run halted
correctly on `blocked` rather than spinning, so the guards held, but the scope
had already escaped.

**Now:** scope closes after negotiation. New items are legal on turns 0 and 1
only. After that an agent raising a concern must put it in its narrative, where a
person can see it, rather than in the checklist where it becomes work.

**The general lesson:** two capable agents told to be rigorous will expand the
definition of done indefinitely. Termination has to be structural.

## 5. An agent wrote outside its workspace

Not a run failure, but a containment gap. Working in `/tmp/rally-scratch`, an
agent wrote a new file into Rally's own source tree: `tests/test_agents.py`,
encoding the finding from section 3 so it could not regress.

The content was correct and genuinely useful. The behaviour still has to stop,
because "it wrote something good this time" is not a security posture.

**Now:** each commissioned run gets its own git-initialised workspace, the prompt
states the boundary explicitly, and the runner fingerprints its own repo around
every turn and records a `containment` violation if it changes.

## What none of this was

None of these were model failures. Both agents behaved sensibly throughout. Every
fault was in the harness: a wrong flag, an over-strict rule, an asymmetric
capability, an unbounded one. That is the argument for building the loop and
running it on something trivial before pointing it at work that matters.
