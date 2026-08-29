# All Things Agentic submission brief

## One line

**Rally turns one executive email into independently verified engineering work
by coordinating Claude and Gemini until a deterministic checklist—not either
model's confidence—says the task is complete.**

## Thirty-second pitch

Single-agent coding systems have a structural trust problem: the same model that
does the work usually decides whether the work is done. Rally separates those
roles. Email a commission from any device; Google ADK and Gemini preserve and
govern the request; Claude and Gemini alternate implementation and review; and
the runner rejects every self-approved completion. Every turn appears as a
polished email, every claim carries evidence, and every loop has a hard stop.

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
| Failure-tolerant routing | Edge records are acknowledged only after handling; transient hydration errors retry; Cloud coordination uses leases and fencing; exact replays reuse the run | Retry tests, duplicate response, resumed attempt counter |
| Security and governance | Signed webhook, commissioner allowlist, Cloud Run IAM plus service token, isolated worktree, hard budgets, no self-approval | IAM policy, security table, rejected illegal transition |
| Telemetry | Structured Worker logs plus metadata-only Cloud Logging and Cloud Trace | Trace waterfall and redacted log query |

## Judge matrix

| Criterion | Rally's claim | Proof to show |
|---|---|---|
| Innovation & operational utility (40%) | Email-native access plus cross-family verification converts agents from personal copilots into a shared, accountable team service | Send one email; show alternating Claude/Gemini executive updates and final evidence |
| Technical architecture (30%) | ADK + Gemini on IAM-protected Cloud Run, atomic Firestore idempotency, Secret Manager, Cloud Trace, signed edge webhook, deterministic state machine | Architecture diagram, Terraform, trace/log, verification state |
| Demo & production readiness (30%) | Deployed path, live eval gate, bounded costs, polished emails, human stop/steer, reproducible repo | 3/3 eval, 72 tests, live Cloud Run health, complete email thread |

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

Teams are adopting coding agents faster than they are adopting ways to trust
them. A single agent can produce impressive work, but it also grades its own
homework. Meanwhile, access is fragmented across individual CLIs, licenses, and
personal configuration. We wanted one address a whole team could use and one
rule no model could talk its way around: you cannot approve your own work.

### What it does

A verified user emails `rally@updates.agent9.dev`. Rally durably queues the
request, sends it through a Google ADK/Gemini coordinator, then alternates
Claude and Gemini against one shared checklist. They negotiate scope, implement,
run tests, reject weak evidence, and verify each other's work. The commissioner
sees polished, watermarked updates in one email thread and receives a final
executive report when every item is independently verified—or a precise halt
report when the loop cannot safely finish.

### How we built it

The email edge is Resend plus a Cloudflare Worker/D1 queue. A local policy runner
authenticates the commissioner and calls an IAM-protected Cloud Run service with
both a Google identity token and a Secret Manager-backed application token. A
Gemini 3.7 Flash agent built with Google ADK preserves the commission verbatim
and creates a bounded handoff. Firestore atomically claims the request key to
prevent duplicate execution. Claude and Gemini CLIs then work in an isolated git
workspace while deterministic Python code enforces the checklist state machine,
model-family separation, review invariant, and budget guards. Cloud Logging and
Cloud Trace capture metadata without prompt or response content.

### Challenges

The hardest problem was separating believable model behavior from enforceable
system behavior. We also discovered through live ADK evaluation that Gemini was
paraphrasing requests at the audit boundary. The response looked excellent, but
exact trajectory evaluation exposed the scope mutation. We changed the agent to
preserve commissions verbatim and reran the unchanged gate to 3/3 passes.

### Accomplishments

- Real cross-family work and verification, visible turn by turn in email
- A completion invariant enforced outside model prompts
- Atomic idempotency across webhook retries and concurrent delivery
- Retry-safe edge acknowledgement and resumable Cloud coordination with fencing
- Authenticated fleet catalog for cross-department discovery and governance
- Dual-auth Cloud Run boundary and least-privilege runtime identity
- Metadata-only GenAI observability
- 72 automated tests plus three live ADK eval cases at 1.00/1.00
- Validated Terraform and a demo-ready operator workflow

### What we learned

Multi-agent value does not come from adding more personas. It comes from giving
agents incompatible authority: one can work, another can approve, and neither
can change the rules. Evaluation also needs to measure tool arguments and policy
preservation, not just whether the final answer sounds good.

### What's next

Move licensed execution into isolated fleet workers, add organization groups and
repository routing, stream run events directly from Firestore, and support a
third verifier for high-risk changes. The email interface and state-machine
contract remain unchanged.

## Final evidence checklist

- [x] Public source repository with founding documents and implementation
- [x] Gemini 3.7 + ADK source and repeatable eval set
- [x] Cloud infrastructure defined and validated in Terraform
- [x] Security, architecture, runbook, and honest-boundary documentation
- [x] Versioned agent catalog and recovery/fencing tests
- [ ] Cloud Run revision live with Firestore and Trace evidence
- [ ] End-to-end email run through the Cloud coordinator
- [ ] Four-minute video uploaded and linked
- [ ] Devpost fields, screenshots, and repository link entered

## New-project disclosure

Rally's first commit was created on August 28, 2026, inside the August 3–31
submission period. The repository history preserves that chronology. The build
uses standard open-source frameworks and provider services; no pre-hackathon
Rally implementation was incorporated.
