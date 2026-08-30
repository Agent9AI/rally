# The first hour

> **Historical implementation record — August 28, 2026.** This document
> preserves Rally's original one-hour proof plan and its deliberate cuts; it is
> not the current architecture or operator runbook. The production-shaped
> release now has three model families, durable D1 intake, Google Cloud
> coordination, A2A v1.0, and governed connectors. See the root `README.md`,
> `docs/ARCHITECTURE.md`, and `docs/JUDGE-PACKET.md` for current state.

The smallest build that proves the thesis, using only components already
verified working. Everything here is a deliberate cut, not an omission, and each
cut names what it defers.

## What the hour has to prove

**Two agents from different model families drive one checklist to completion,
corresponding in real email, with the verification invariant enforced.**

Anything that does not serve that sentence is out.

## Already proven, do not rebuild

| Component | Status |
|---|---|
| `claude -p --model … --effort …` headless | in daily production use |
| `agy … -p="…"` headless, clean JSON out | verified 2026-08-28, 12s round trip |
| Resend outbound send via API | in production |
| Resend inbound to webhook to dispatch to reply | in production, end to end |

Two traps found while verifying, both already cost-free to avoid:

- **`agy` parses flags Go style.** A bare `-p` swallows the next token, so
  `agy -p --model X "prompt"` silently uses `--model` as the prompt. Always
  `-p="$PROMPT"`, always last.
- **`agy` also serves Claude models.** Unpinned, the run becomes one family
  reviewing itself and still looks healthy. Pin, and assert the pin.

## The one real cut: defer inbound

The loop keeps **real outbound email**. Every turn sends a genuine message to the
thread with the human CC'd, so the correspondence is real, readable, and
auditable in an ordinary inbox.

The loop does **not** wait on inbound delivery to advance. The runner hands the
envelope to the next agent in process.

Why this and not something else: inbound is the only part needing infrastructure
that does not exist yet, namely routing two new addresses and giving the mail
host a network path to the machine that can run both CLIs. The loop's semantics
do not depend on it. The envelope, the state machine, the guards, and the
invariant are all identical either way, which is exactly what the ingress
interface in figure 4 is for. Swapping local dispatch for real inbound later
touches one module.

Honest naming: at T+60 this is an **email-attested loop**, not yet an
email-driven one. The thread is real. The trigger is local.

## Schedule

| Time | Build | Done when |
|---|---|---|
| 0-8 | Config and envelope schema. Model pins, limits, run directory. | `rally --check` prints the pins and refuses a same-family pair. |
| 8-25 | Runner core. Run store as one JSON file per run, alternation, turn cap, state machine. | A dry run alternates 4 turns with stub agents and halts on the cap. |
| 25-40 | The two adapters. Build prompt, shell out, extract envelope, validate, one reprompt on malformed output. | Both CLIs return a valid envelope for a trivial checklist. |
| 40-50 | Resend outbound. One send per turn, human CC'd, ceiling checked **before** the call. | A real thread appears in the inbox. |
| 50-60 | Run a real task end to end and read the thread. | Every item `done`, each verified by the other agent. |

## Kept, because they are cheap and they protect a shared credential

Roughly ten lines total, and the sending quota is shared with unrelated
projects, so a runaway loop is someone else's outage:

- turn cap, default 24
- sends per run, default 60
- send ceiling checked before the Resend call, failing closed
- model pin assertion, refusing to start on a same-family pair

## Cut, and where each one goes

| Cut | Deferred to |
|---|---|
| Edge queue / Worker | the ingress swap |
| Real inbound mail | the ingress swap |
| n8n as an agent capability | after the loop is proven |
| Dispute protocol | the turn cap catches non-convergence for now |
| Attachments, images, media | not on the critical path |
| Multi-run concurrency | one run at a time is enough to prove it |

## Shape of the code

One Python file for the runner, because the work is JSON, state, and one HTTP
call. Two thin adapters that build a prompt, shell out, and parse one envelope.
No framework, no dependencies beyond the standard library.

```
src/runner.py        run store, turn loop, guards, Resend send
src/agents/claude.py adapter
src/agents/agy.py    adapter
config/rally.toml    pins and limits
schema/envelope.json canonical envelope
```

## The first task to give it

Small, externally verifiable, and not about Rally itself. The point of the first
run is to exercise the loop, not to survive a hard problem. A task whose
checklist has three or four items with obvious pass conditions, in a scratch
repo, is ideal. Save the interesting work for run two.
