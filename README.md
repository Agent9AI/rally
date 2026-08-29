# Rally

**Rally is the digital operator that cannot approve its own work.** A company
gets one persistent agent identity, deterministic limits outside every prompt,
and a second model family that must verify consequential work before it is
complete.

The current release proves that contract on engineering operations. Two AI
coding agents, from **different model families**, carry one task to completion
by writing email to each other. A person commissions the run. The checklist
decides when it ends. The next product layer is least-privilege access to
customer-approved systems such as Cloudflare, n8n, Google Workspace, and GitHub;
those connectors are documented as roadmap, not represented as shipped.

Agent A is the **Claude CLI** (`claude -p`). Agent B is the **Antigravity CLI**
(`agy -p`), pinned to Gemini. A Google ADK coordinator on **Cloud Run** preserves
the commission and records it durably in **Firestore** before execution.
Transport is **Resend**; a **Cloudflare Worker + D1** holds inbound mail so a
sleeping runner costs latency, never a lost task.

```
you ──email──▶ rally@updates.agent9.dev
                      │
              Worker + D1 queue
                      │
                 Rally runner
                      │ authenticated, idempotent handoff
          Google ADK + Gemini on Cloud Run
                      │
                  Firestore
                      │
        ┌─────────────┴─────────────┐
   claude -p                     agy -p
   (Anthropic)   ◀── verify ──▶   (Gemini)
        └─────────────┬─────────────┘
                      │ every turn + final report
you ◀─────────────────┘
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
| Turn loop, state machine, console projection, guards | working, 62 core/product tests |
| Claude + Gemini CLI execution | working, live multi-turn runs completed |
| Executive turn emails + report | working through Resend |
| Ingress Worker (D1) | deployed, signed webhook and round trip verified |
| Judge console | live Pages UI backed by a double-sanitized D1 run projection |
| `rally@updates.agent9.dev` route | working; replies return to the commissioner |
| Product + Cloud test suite | 72 automated tests passing |
| Google ADK coordinator | implemented; live eval 3/3, both metrics 1.00 |
| Cloud Run + Firestore + Trace | Terraform validated; deployment approval pending |

The current release candidate has **72 automated tests**: 62 deterministic
runner, ingress, policy, bridge, and site tests plus 10 Cloud service tests.
The separate live ADK scorecard remains 3/3 at 1.00 trajectory and 1.00 quality.

### Why the models have different jobs

Gemini 3.7 Flash is the load-bearing Google ADK coordinator on Vertex AI. It
preserves the human's request, invokes one bounded handoff tool, and creates the
durable governance record. The two licensed coding workers then operate in the
repository: Claude and Antigravity/Gemini can both implement and review, but the
runner rotates item ownership so neither family can approve its own work. The
standard profile keeps its deliberate high-reasoning worker pin; the filmed
profile uses Gemini 3.7 Flash for speed. The required Gemini 3.5+ path is never
decorative or confined to the presentation layer.

Honest boundary: email starts the real run and mirrors every turn, but the next
agent is dispatched by the authoritative runner rather than by re-delivering the
email. The local host remains necessary because the two coding subscriptions are
accessed through desktop CLIs. Google Cloud is the durable intake, governance,
identity, and observability plane—not a decorative API call.

## Quickstart

```bash
make check                    # pins, binaries, credentials, limits
make dry                      # exercise the loop, no tokens spent
make test                     # 53 local policy, ingress, bridge, recovery, and site tests
make cloud-test               # Cloud coordinator tests + lint
make cloud-eval               # live ADK eval; exact trajectory + quality gates

./bin/rally --run "your task" --workdir /path/to/repo --no-mail
make serve                    # poll for commissions and run them
```

See [docs/RUNBOOK.md](docs/RUNBOOK.md) to operate it, including how to stop a run.

## Documents

| Document | What it is |
|---|---|
| [docs/FOUNDING.md](docs/FOUNDING.md) | The charter. Intent, principles, guardrails. Authority on why. |
| [docs/PRODUCT-DIRECTION.md](docs/PRODUCT-DIRECTION.md) | The governed-operator position and researched connector sequence. |
| [docs/SPEC.md](docs/SPEC.md) | The build. Envelope, state machine, limits, invocation. |
| [docs/DIAGRAMS.md](docs/DIAGRAMS.md) | The system in four figures. |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | Operating it. Setup, intervention, failure modes. |
| [docs/FINDINGS.md](docs/FINDINGS.md) | What the first live run exposed. The most useful page here. |
| [docs/DEMO.md](docs/DEMO.md) | **Start here to see it work.** Numbered steps, two paths. |
| [docs/DEMO-SCRIPT.md](docs/DEMO-SCRIPT.md) | The four-minute recording script and shot list. |
| [docs/VIDEO-PRODUCTION.md](docs/VIDEO-PRODUCTION.md) | Short-film and unedited-run capture package. |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Google Cloud topology, trust boundaries, and failure behavior. |
| [docs/assets/rally-architecture.svg](docs/assets/rally-architecture.svg) | Presentation-ready architecture diagram. |
| [docs/EVALUATION.md](docs/EVALUATION.md) | Live ADK eval design, scores, and the behavior it improved. |
| [docs/HACKATHON.md](docs/HACKATHON.md) | Judge-facing positioning and submission checklist. |
| [docs/JUDGE-PACKET.md](docs/JUDGE-PACKET.md) | Four-minute proof order and claim-to-receipt index. |
| [docs/SUBMISSION-CHECKLIST.md](docs/SUBMISSION-CHECKLIST.md) | Final operator checklist with explicit deployment gate. |
| [docs/PUBLIC-LAUNCH-DRAFT.md](docs/PUBLIC-LAUNCH-DRAFT.md) | Bonus-content and social-copy drafts. |
| [docs/SECURITY.md](docs/SECURITY.md) | Threats, controls, and demo-safe evidence. |
| [docs/ONBOARDING.md](docs/ONBOARDING.md) | Managed no-key launch and secure self-host strategy. |
| [docs/BUILD-1HR.md](docs/BUILD-1HR.md) | The cut-to-the-bone first hour. |

## Layout

```
bin/rally              entry point
src/runner.py          authoritative state, turn dispatch, guards
src/envelope.py        parsing and state-machine enforcement
src/agents.py          the two CLI adapters, pin and symmetry checks
src/transport.py       Resend send, fail-closed ceilings
src/ingress.py         collect inbound, classify, authorise
src/cloud_coordinator.py authenticated Google Cloud handoff
src/report.py          the one message the human reads
src/worker/            Cloudflare ingress Worker
cloud/rally_adk/       Google ADK + Gemini coordinator
cloud/service.py       authenticated Cloud Run API
cloud/store.py         atomic Firestore idempotency and run records
cloud/infra/           validated production Terraform
config/rally.json      pins, limits, addresses, owners
runs/<id>/             state.json and the agents' workspace
```
