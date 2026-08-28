# Rally

Two AI coding agents, from **different model families**, carry one task to
completion by writing email to each other. A person commissions the run. The
checklist decides when it ends.

Agent A is the **Claude CLI** (`claude -p`). Agent B is the **Antigravity CLI**
(`agy -p`), pinned to Gemini. Transport is **Resend**. Inbound mail is held by a
**Cloudflare Worker** so a sleeping runner costs latency, never a lost task.

```
you ──email──▶ rally@updates.agent9.dev
                      │
              Worker holds it durably (D1)
                      │
                 runner collects
                      │
        ┌─────────────┴─────────────┐
   claude -p                     agy -p
   (opus)      ◀── verify ──▶    (gemini-3.1-pro)
        └─────────────┬─────────────┘
                      │
you ◀──── one report, when it is done or stuck
```

## Why

**Give your team one shared, on-demand agent, configured to your stack, at an
address anyone can email.**

Right now every engineer on a team runs their own assistant. Each one is
configured differently, primed with different context, and knows a different
subset of your conventions. The quality of what people get back depends on how
well they personally set their tooling up. None of that work is shared, and none
of it is visible.

Rally is the opposite shape. You configure it **once**, against your repo, your
conventions, your limits. Then it lives at an address:

```
rally@updates.agent9.dev
```

That changes a few things at once.

**No install, no seat, no onboarding.** If you can send an email, you can use it.
Nobody needs a license, a CLI, a plugin, or a laptop that can run any of it. A
product manager on a phone has exactly the same access as the staff engineer who
set it up.

**It is configured once and correct for everyone.** The stack, the conventions,
the model pins, the spend limits, the repo it works in. One person gets that
right and the whole team inherits it, instead of fifteen people each half-solving
it.

**The work is checked before you see it.** Two different model families work the
same checklist, and nothing is marked done until the agent that *didn't* do it
verifies it. What lands in your inbox has already survived a second opinion from
a model that doesn't share the first one's blind spots. That is a materially
different artifact from one model's confident first answer.

**It is asynchronous by nature.** You send a task and close your laptop. Email is
already the queue, the audit log, and the notification system. The whole
deliberation sits in a thread you can read, forward, or search months later.

**It stops instead of spinning.** Every run has a turn budget, a no-progress
halt, and a send ceiling enforced outside the agents' reach. If it cannot finish,
it tells you exactly where it stopped and why, rather than burning budget being
agreeable.

## The two rules everything else protects

1. **An item reaches `done` only when the agent that did _not_ do the work
   verifies it.** Enforced by the runner, not requested in a prompt.
2. **The two agents must come from different model families.** A model reviewing
   itself shares its own blind spots, so the review carries almost no
   information. Startup refuses a same-family pair.

## Status

| Piece | State |
|---|---|
| Turn loop, state machine, guards | working, 35 tests |
| Both CLI adapters | working, verified against live CLIs |
| Human report | working |
| Ingress Worker (D1) | deployed, auth and round trip verified |
| Outbound mail via Resend | code complete, needs the API key in the keychain |
| Resend inbound route for `rally@` | needs configuring in the Resend dashboard |
| Agent-to-agent email leg | designed, not yet the transport (runner dispatches locally) |

Honest naming: today the loop is **email-attested**, not yet email-driven. The
report is real mail. The turn handoff is still in process. Swapping it is one
module, which is the point of the ingress interface.

## Quickstart

```bash
make check                    # pins, binaries, credentials, limits
make dry                      # exercise the loop, no tokens spent
make test                     # 35 tests

./bin/rally --run "your task" --workdir /path/to/repo --no-mail
make serve                    # poll for commissions and run them
```

See [docs/RUNBOOK.md](docs/RUNBOOK.md) to operate it, including how to stop a run.

## Documents

| Document | What it is |
|---|---|
| [docs/FOUNDING.md](docs/FOUNDING.md) | The charter. Intent, principles, guardrails. Authority on why. |
| [docs/SPEC.md](docs/SPEC.md) | The build. Envelope, state machine, limits, invocation. |
| [docs/DIAGRAMS.md](docs/DIAGRAMS.md) | The system in four figures. |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | Operating it. Setup, intervention, failure modes. |
| [docs/FINDINGS.md](docs/FINDINGS.md) | What the first live run exposed. The most useful page here. |
| [docs/DEMO.md](docs/DEMO.md) | **Start here to see it work.** Numbered steps, two paths. |
| [docs/BUILD-1HR.md](docs/BUILD-1HR.md) | The cut-to-the-bone first hour. |

## Layout

```
bin/rally              entry point
src/runner.py          authoritative state, turn dispatch, guards
src/envelope.py        parsing and state-machine enforcement
src/agents.py          the two CLI adapters, pin and symmetry checks
src/transport.py       Resend send, fail-closed ceilings
src/ingress.py         collect inbound, classify, authorise
src/report.py          the one message the human reads
src/worker/            Cloudflare ingress Worker
config/rally.json      pins, limits, addresses, owners
runs/<id>/             state.json and the agents' workspace
```
