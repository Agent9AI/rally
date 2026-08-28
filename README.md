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
