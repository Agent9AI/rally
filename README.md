# Rally

**Rally is the accountable AI team: your best models, finally working
together.** A company gets one Rally identity on the outside and a governed
team of specialized models on the inside. Give it one difficult outcome; Rally
coordinates the handoffs, works inside approved boundaries, and returns one
independently verified result with evidence.

The current release proves that contract with three provider-native workers.
Gemini, Claude, and OpenAI Codex, from **different model families**, rotate around
one shared checklist. A person commissions the run once. The models execute and
review. Deterministic policy—not any model's confidence—decides when it ends.
The next product layer connects the systems where company work lives.
All ten catalogued systems—Google Workspace, Slack, GitHub, Cloudflare
Observability, n8n Cloud, Stripe, BigQuery, Atlassian, Salesforce, and
Hyperagent—now have deny-by-default gateway adapters. The catalog is not an
activation claim. A hosted card stays disabled until Rally has finished the
provider registration needed to complete the flow itself; nontechnical users
are not sent to a provider console to finish our setup. An available connection
becomes **Certified** only after the user authenticates, live discovery matches
the committed safe allowlist, and Rally completes one fixed harmless read. The
proof records hashes and metadata, never the returned business content.

The fleet uses the **Claude CLI** (`claude -p`), **Antigravity CLI** (`agy -p`)
pinned to Gemini, and **Codex CLI** (`codex exec`) pinned to OpenAI. Each runs
through the user's own provider sign-in; accounts and connector credentials are
never shared between users. A Google ADK coordinator on **Cloud Run** preserves
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
        ┌─────────────┼─────────────┐
   claude -p        agy -p       codex exec
   Anthropic        Gemini        OpenAI
        └────── implement ↔ verify ──────┘
                      │ every turn + final report
you ◀─────────────────┘
```

## Why

**Give your team one accountable AI team, configured to your company, at an
address anyone can email.**

Organizations already use multiple AI models, but their people still carry the
context and supervise the handoffs. One assistant knows the customer history;
another is strongest at code; another reasons over the plan. Each lives in its
own tab, account, and permission boundary. The models do not become a team just
because the company pays for all of them.

Rally is the handshake between them and the accountability layer around their
work. You configure it **once**, against your approved systems, conventions,
and limits. Then it lives at an address:

```
rally@updates.agent9.dev
```

The open ecosystem is moving in the same direction. Google introduced the
[Agent2Agent (A2A) Protocol](https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability/)
so independent agents can discover capabilities and collaborate across vendors;
on August 27, 2026, A2A was
[accepted into the Agentic AI Foundation at Growth Stage](https://a2a-protocol.org/latest/blog/2026/08/27/a-new-chapter-for-a2a-joining-the-agentic-ai-foundation/).
Rally's contribution is the accountability layer around that interoperability:
policy, ownership, recovery, evidence, and independent verification. The current
release exposes an official A2A v1.0 Agent Card plus JSON-RPC and HTTP+JSON
bindings backed by the same governed commission path. That is a tested
interoperability claim, not a certification or endorsement claim.

That changes a few things at once.

**No install, no seat, no onboarding.** If you can send an email, you can use it.
Nobody needs a license, a CLI, a plugin, or a laptop that can run any of it. A
product manager on a phone has exactly the same access as the staff engineer who
set it up.

**It is configured once and correct for everyone.** The stack, the conventions,
the model pins, the spend limits, the repo it works in. One person gets that
right and the whole team inherits it, instead of fifteen people each half-solving
it.

**The work is checked before you see it.** Different model families work the
same checklist, and nothing is marked done until a worker that *didn't* do it
verifies it. What lands in your inbox has already survived a second opinion from
a model that doesn't share the first one's blind spots. That is a materially
different artifact from one model's confident first answer.

**It is asynchronous by nature.** You send a task and close your laptop. Email is
already the queue, the audit log, and the notification system. The whole
deliberation sits in a thread you can read, forward, or search months later.

**It recovers before it stops.** With **Second Wind** enabled, a failed turn or
reported blocker is handed once to the next model family from the last accepted
state. The backup may inspect partial workspace edits, repair the work, and take
ownership—but it still cannot approve its own repair. Hard turn, progress, send,
authority, and recovery ceilings remain outside every agent's reach; if the team
still cannot finish, Rally tells you exactly where and why.

## The two rules everything else protects

1. **An item reaches `done` only when the agent that did _not_ do the work
   verifies it.** Enforced by the runner, not requested in a prompt.
2. **Every configured worker must come from a distinct model family.** A model
   reviewing itself shares its own blind spots, so the review carries almost no
   information. Startup refuses duplicate families.

## Status

| Piece | State |
|---|---|
| Turn loop, state machine, console projection, guards | working, 88 product/integration tests |
| Claude + Gemini CLI execution | working, live multi-turn runs completed |
| OpenAI Codex CLI execution | working, live authenticated preflight passed with per-user ChatGPT sign-in |
| Executive turn emails + report | working through Resend |
| Ingress Worker (D1) | deployed, signed webhook and round trip verified |
| Judge console | live Pages UI backed by a double-sanitized D1 run projection; professional proof run `r-20260830-447f2f` is public |
| `rally@updates.agent9.dev` route | working; replies return to the commissioner |
| Connector gateway | BigQuery live MCP handshake + six-tool discovery verified; ten pinned runtime adapters; provider-safe presets; exact one-time human approvals; per-run authority, payload ceilings, and content-free receipts |
| Product + Cloud test suite | 259 automated tests passing |
| Google ADK coordinator | implemented; live eval 6/6, both metrics 1.00 |
| Cloud Run + Firestore + Trace | deployed privately in `rally-agent9-2026`; authenticated commission, replay, Firestore, logs, and content-free trace verified |
| Customer identity + credential vault | verified Google-account boundary, tenant-isolated API, and Cloud KMS envelope encryption implemented; Google web sign-in and each business-system authorization remain separate trust grants |
| A2A v1.0 boundary | Agent Card, JSON-RPC, HTTP+JSON, SSE streaming, polling, listing, Firestore tasks, and dual-auth tested with official SDK clients |
| WebMCP browser surface | Three feature-detected tools shipped for public-run search, bounded verification inspection, and human-confirmed job drafting; production ChatGPT in-app invocation remains the final proof gate |

The current release candidate has **259 automated tests**: 88 deterministic
runner, ingress, policy, bridge, connector, and site tests plus 171 Cloud, A2A,
credential, preset, approval, and connector-gateway service tests.
The separate live ADK scorecard remains 6/6 at 1.00 trajectory and 1.00 quality.

### Why the models have different jobs

Gemini 3.7 Flash is the load-bearing Google ADK coordinator on Vertex AI. It
preserves the human's request, invokes one bounded handoff tool, and creates the
durable governance record. Three licensed CLI workers then operate in the
workspace: Claude, Antigravity/Gemini, and OpenAI Codex can each implement and
review, but the runner rotates item ownership so no family can approve its own work. The
standard profile keeps its deliberate high-reasoning worker pin; the filmed
profile uses Gemini 3.7 Flash for speed. The required Gemini 3.5+ path is never
decorative or confined to the presentation layer.

Honest boundary: email starts the real run and mirrors every turn, but the next
agent is dispatched by the authoritative runner rather than by re-delivering the
email. The local host remains necessary because the coding subscriptions are
accessed through desktop CLIs. Google Cloud is the durable intake, governance,
identity, and observability plane—not a decorative API call.

## What a connector card promises

The hosted administrator signs into Rally first. That Google web sign-in proves
who owns the vault; it does **not** authorize Gmail, Drive, or any other business
system. Each connector uses a separate provider grant and returns to the same
card that started it, where Rally either records a content-free certification or
leaves the adapter disabled.

At the registered production callback, Rally's Cloudflare Worker matches the
one-time provider response to a short-lived, per-flow `HttpOnly`, `Secure`,
`SameSite=Lax` browser-binding cookie, relays the response server-side, and
clears the cookie. The control plane then atomically consumes the encrypted
flow. The admin page receives neither the authorization code nor a provider
token. The static Pages origin is deliberately not a callback fallback: if the
Worker is unavailable, provider authorization fails closed instead of weakening
the same-browser guarantee.

Google Workspace is intentionally one product card rather than eight setup
chores. Behind that card, Rally uses a separate confidential Workspace connector
client—not the Rally Web sign-in client—and checks Gmail, Drive, Docs, Sheets,
Slides, Calendar, Chat, and People independently. All eight must expose an
allowlisted read surface. Rally runs fixed, resource-free canaries against Gmail,
Drive, Calendar, Chat, and People; Docs, Sheets, and Slides are omitted from the
certified manifest until Rally can prove a user-owned resource read. Until the
confidential connector client is configured, the card remains unavailable
rather than opening Google Cloud Console for the customer.

The hosted vault is an activation bridge, not autonomous model authority. A
signed-in administrator may call a Certified, preset-allowlisted read tool
through the hosted control plane; Rally rechecks tenant ownership, readiness,
arguments, and policy and writes a content-free receipt. Agent runs additionally
receive a separate immutable, user-bound authority snapshot.

Disconnecting an OAuth connector disables it first, then asks the provider to
revoke the grant when it publishes a revocation endpoint. Rally deletes its
encrypted copy only after a successful automatic revocation; if the provider
does not offer one, Rally deletes its copy and reports that provider action is
still required. Manually supplied keys and tokens must be revoked in the
provider's own settings. These are acceptance rules, not a claim that every
catalogued provider has passed live production certification.

## Quickstart

```bash
make check                    # pins, binaries, credentials, limits
make dry                      # exercise the loop, no tokens spent
make test                     # 88 local policy, ingress, connector, recovery, and site tests
make cloud-test               # Cloud coordinator tests + lint
make cloud-eval               # live ADK eval; exact trajectory + quality gates

./bin/rally --run "your task" --workdir /path/to/repo --no-mail
make serve                    # poll for commissions and run them

./bin/rally connectors list
./bin/rally connectors install              # register the gateway with Antigravity
./bin/rally connectors --profile you@company.com list
./bin/rally connectors auth atlassian       # local runtime OAuth + bounded discovery
./bin/rally connectors doctor bigquery      # ADC + live tool discovery
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
| [docs/A2A.md](docs/A2A.md) | A2A v1.0 discovery, bindings, security, state mapping, and verification. |
| [docs/CONNECTORS.md](docs/CONNECTORS.md) | Governed MCP gateway, ten runtime adapters, setup, policy, approvals, and receipts. |
| [docs/CUSTOM-MCP.md](docs/CUSTOM-MCP.md) | Labs admission contract for custom remote MCP and WebMCP boundary. |
| [docs/WEBMCP.md](docs/WEBMCP.md) | Shipped browser tools for live-run review and human-confirmed job drafting. |
| [docs/WEBMCP-CHALLENGE.md](docs/WEBMCP-CHALLENGE.md) | September 3 submission story, three-minute proof, and must-pass gate. |
| [docs/assets/rally-architecture.svg](docs/assets/rally-architecture.svg) | Presentation-ready architecture diagram. |
| [docs/EVALUATION.md](docs/EVALUATION.md) | Live ADK eval design, scores, and the behavior it improved. |
| [docs/HACKATHON.md](docs/HACKATHON.md) | Judge-facing positioning and submission checklist. |
| [docs/JUDGE-PACKET.md](docs/JUDGE-PACKET.md) | Four-minute proof order and claim-to-receipt index. |
| [docs/SUBMISSION-CHECKLIST.md](docs/SUBMISSION-CHECKLIST.md) | Final operator checklist with explicit deployment gate. |
| [docs/FAQ-COMPLIANCE.md](docs/FAQ-COMPLIANCE.md) | Requirement-by-requirement Devpost FAQ compliance record. |
| [docs/PUBLIC-LAUNCH-DRAFT.md](docs/PUBLIC-LAUNCH-DRAFT.md) | Bonus-content and social-copy drafts. |
| [docs/SECURITY.md](docs/SECURITY.md) | Threats, controls, and demo-safe evidence. |
| [docs/ONBOARDING.md](docs/ONBOARDING.md) | Managed no-key launch and secure self-host strategy. |
| [docs/BUILD-1HR.md](docs/BUILD-1HR.md) | The cut-to-the-bone first hour. |

## Layout

```
bin/rally              entry point
src/runner.py          authoritative state, turn dispatch, guards
src/envelope.py        parsing and state-machine enforcement
src/agents.py          three CLI adapters, pin and symmetry checks
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

## Must do before Devpost submission

The deadline is **August 31, 2026 at 5:00 PM PDT**. Do not submit until every
box below is checked; see `docs/SUBMISSION-CHECKLIST.md` for the evidence-level
version.

- [x] Deploy the authenticated ADK coordinator to Google Cloud and complete the
      professional governed run (`r-20260830-447f2f`, 6/6 independently verified).
- [ ] Record visible Cloud Run, Vertex AI, Firestore, and Trace proof in the
      narrated demo; keep the public YouTube/Vimeo cut under four minutes and
      verify it in an incognito window.
- [ ] Upload the video early enough for processing to finish before submission.
- [ ] Add every teammate to Devpost, confirm every invitation is accepted, and
      name the Representative.
- [x] Publish this repository under Apache-2.0 so judges can review it without
      private-account access.
- [ ] Link the public repository in the Devpost submission.
- [ ] Upload `docs/assets/rally-architecture.svg`, enter the hosted Rally URL,
      and include testing credentials only if the submitted experience is gated.
- [ ] Preview all links and instructions while signed out, submit, save the
      confirmation, then freeze the submitted repo, video, and site until winner
      announcements.

## License

Copyright 2026 Agent9 AI. Licensed under the
[Apache License 2.0](LICENSE).
