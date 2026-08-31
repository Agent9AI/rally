# All Things Agentic submission brief

## One line

**Rally turns the AI models a company already trusts into one accountable team:
one difficult goal in, cross-model work and review, and one independently
verified result out.**

## Thirty-second pitch

Companies are collecting powerful AI assistants, but people still copy context
between them, manage every handoff, and decide which answer to trust. Rally puts
those models on one accountable team. Email one outcome from any device; Google
ADK and Gemini govern the request; Gemini, Claude, and OpenAI Codex rotate
through execution and review; and deterministic policy rejects every
self-approved completion. The
human receives one finished result with evidence and residual risk.

## Target category

Primary: **Fortified Enterprise Fleet**. Rally is a governed multi-agent fleet
with identity, replay protection, durable state, independent review, telemetry,
operator intervention, and an authenticated catalog. Gemini Enterprise Agent
Platform is recommended rather than mandatory; Rally deliberately demonstrates
that the same enterprise outcomes can be enforced with Google ADK, Vertex AI,
Cloud Run, Firestore, IAM, Secret Manager, and OpenTelemetry. Its implementation
workflow also demonstrates the Taskmaster pattern, but the submitted category
and story remain Fortified.

The unlikely hero is the nontechnical product or operations leader. That person
can commission repository work from a phone without a CLI, cloud console, API
key, or prompt-engineering skill, while still receiving evidence a security or
engineering leader can audit.

## Fortified proof matrix

| What judges ask for | Rally implementation | Visible evidence |
|---|---|---|
| Discovery and lifecycle | Authenticated `GET /v1/agents` catalog with version, owner, capabilities, departments, authority, prohibitions, and status | Catalog response and `cloud/agent_catalog.json` |
| Long-running runtime and state | D1 retains unopened commissions; local state saves every turn; Firestore keeps the ADK handoff and 30-day retention metadata | D1 row, Firestore record, recovered run log |
| Failure-tolerant routing | Edge records are acknowledged only after handling; transient hydration errors retry; Cloud coordination uses leases and fencing; exact replays reuse the run; Second Wind hands recoverable worker failures to the next model family | Retry tests, duplicate response, resumed attempt counter, bounded takeover test |
| Security and governance | Signed webhook, commissioner allowlist, Cloud Run IAM plus service token, isolated worktree, hard budgets, no self-approval | IAM policy, security table, rejected illegal transition |
| Telemetry | Structured Worker logs plus metadata-only Cloud Logging and Cloud Trace | Trace waterfall and redacted log query |

## Judge matrix

| Criterion | Rally's claim | Proof to show |
|---|---|---|
| Innovation & operational utility (40%) | Email-native access plus cross-family verification converts agents from personal copilots into a shared, accountable team service | Send one email; show provider-native worker turns and final evidence |
| Technical architecture (30%) | ADK + Gemini on IAM-protected Cloud Run, atomic Firestore idempotency, Secret Manager, Cloud Trace, signed edge webhook, deterministic state machine | Architecture diagram, Terraform, trace/log, verification state |
| Demo & production readiness (30%) | Deployed coordination path, live eval gate, bounded costs, polished emails, human stop/steer, reproducible repo | 6/6 eval, 369 tests, live Cloud Run health, complete email thread |

## Model assignment rationale

- **Gemini 3.7 Flash through Vertex AI + Google ADK:** authenticated intake,
  verbatim intent preservation, and the governed handoff. This is the mandatory,
  load-bearing Gemini 3.5+ path.
- **Claude worker:** repository scoping, implementation, tests, and independent
  verification of Gemini-owned checklist items.
- **Antigravity/Gemini worker:** the same execution capabilities from a different
  model family; it implements its own items and independently verifies
  Claude-owned items. The standard profile retains its high-reasoning pin while
  the filmed profile uses Gemini 3.7 Flash for predictable demo latency.
- **OpenAI Codex worker:** an invocation-local, ephemeral Codex CLI process
  authenticated through each operator's own ChatGPT sign-in. It ignores global
  MCP configuration, receives only Rally's run-scoped gateway, and has the same
  implementation and independent-review authority as the other workers.
- **Deterministic runner:** owns policy, budgets, routing, and completion. It is
  intentionally not an LLM and cannot be persuaded by either worker.

## Required Google technology

- Gemini 3.7 Flash on Vertex AI
- Google Agent Development Kit
- Cloud Run
- Firestore
- Secret Manager
- Cloud Logging and Cloud Trace
- Artifact Registry and Cloud Build

Google is load-bearing: Cloud Run authenticates and hosts the ADK coordinator;
Firestore decides whether a delivery already owns a commission; Vertex Gemini
creates the audited handoff; and Trace links the intake to model execution.

## Devpost draft

### Inspiration

Companies already have multiple capable AI models, but those models live in
separate tabs, accounts, and permission boundaries. People carry context between
them, supervise every handoff, and decide which answer to trust. We wanted one
accountable AI team a whole company could reach through one identity—and one
rule no model could talk its way around: you cannot approve your own work.

### What it does

A verified user emails one difficult goal to `rally@updates.agent9.dev`. Rally
durably queues it, sends it through a Google ADK/Gemini coordinator, and rallies
Gemini, Claude, and OpenAI Codex around one shared checklist. They negotiate scope, implement,
run tests, reject weak evidence, and verify each other's work. The commissioner
sees the accountable team working in one thread and receives one executive
result when every item is independently verified—or a precise halt report when
the work cannot safely finish.

### How we built it

The email edge is Resend plus a Cloudflare Worker/D1 queue. A local policy runner
authenticates the commissioner and calls an IAM-protected Cloud Run service with
both a Google identity token and a Secret Manager-backed application token. A
Gemini 3.7 Flash agent built with Google ADK preserves the commission verbatim
and creates a bounded handoff. Firestore atomically claims the request key to
prevent duplicate execution. Gemini, Claude, and OpenAI Codex CLIs then work in an isolated git
workspace while deterministic Python code enforces the checklist state machine,
model-family separation, review invariant, and budget guards. Cloud Logging and
Cloud Trace capture metadata without prompt or response content.

### Challenges

The hardest problem was separating believable model behavior from enforceable
system behavior. We also discovered through live ADK evaluation that Gemini was
paraphrasing requests at the audit boundary. The response looked excellent, but
exact trajectory evaluation exposed the scope mutation. We changed the agent to
preserve commissions verbatim, expanded the gate, and caught task details being
paraphrased in the confirmation. The coordinator now emits a fixed,
privacy-preserving receipt after the exact handoff. All six cases pass without
lowering a threshold.

### Accomplishments

- Real cross-family work and verification, visible turn by turn in email
- A completion invariant enforced outside model prompts
- Atomic idempotency across webhook retries and concurrent delivery
- Retry-safe edge acknowledgement and resumable Cloud coordination with fencing
- Authenticated fleet catalog for cross-department discovery and governance
- Dual-auth Cloud Run boundary and least-privilege runtime identity
- Metadata-only GenAI observability
- 369 automated tests (183 local + 186 Cloud) plus six live ADK eval cases at 1.00/1.00
- Validated Terraform and a demo-ready operator workflow

### What we learned

Multi-agent value does not come from adding more personas. It comes from giving
agents incompatible authority: one can work, another can approve, and neither
can change the rules. Evaluation also needs to measure tool arguments and policy
preservation, not just whether the final answer sounds good.

### What's next

Onboard Rally through one administrator-controlled connection center. Every
model entitlement and business-system connection belongs to one user profile;
Rally never pools a provider seat or connector token. All ten catalogued
business systems now have runnable gateway adapters with Google ADC, OAuth, or
external bearer authentication, live discovery, per-run allowlists,
provider-safe presets, exact human approvals, and content-free receipts.
Customer app registration and live authorization still have to be completed
independently for Google Workspace, Slack, GitHub, and Salesforce; Rally never
calls those accounts connected before their provider checks pass. Each connection declares what Rally
may read and which actions require a real pre-execution gate. Use the shipped
A2A v1.0 boundary to admit
additional external agents without moving policy, ownership, or verification
out of Rally's deterministic control plane. The
one-company identity, cross-model team, and no-self-approval contract remain
unchanged.

## Final evidence checklist

- [ ] Reviewable source repository with founding documents and implementation;
      it remains private during final hardening
- [x] Gemini 3.7 + ADK source and repeatable eval set
- [x] Cloud infrastructure defined and validated in Terraform
- [x] Security, architecture, runbook, and honest-boundary documentation
- [x] Versioned agent catalog and recovery/fencing tests
- [x] Cloud Run revision live with Firestore and Trace evidence
- [x] Primary governed run `r-20260831-48141a` completed in 13 turns with 6/6
      independently verified checklist items across three model families and its
      report delivered; the later artifact-mutation boundary is disclosed in
      `docs/evidence/`
- [ ] Four-minute video uploaded and linked
- [ ] Devpost fields, screenshots, and repository link entered

## New-project disclosure

Rally's first commit was created on August 28, 2026, inside the August 3–31
submission period. The repository history preserves that chronology. The build
uses standard open-source frameworks and provider services; no pre-hackathon
Rally implementation was incorporated.
