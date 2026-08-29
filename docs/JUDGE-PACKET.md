# Rally judge packet

## The thesis

**Rally turns one executive email into independently verified engineering work.
Gemini governs the handoff; Claude and Gemini do visible repository work; and
deterministic policy prevents either model from approving its own output.**

Primary category: **Fortified Enterprise Fleet**.

The category fit is not “we used several agents.” Rally provides discovery,
runtime and memory, security and governance, and telemetry for agents that can
modify production repositories. The unlikely hero is a nontechnical product or
operations leader commissioning that work from a phone.

## The four-minute proof order

| Time | Judge question | Live proof | Receipt |
|---|---|---|---|
| 0:00 | Is this useful? | Send the golden commission from email | One familiar address; no CLI or key for the commissioner |
| 0:25 | Is it really an agent system? | First scoped checklist email | Distinct run ID and model-family watermark |
| 0:55 | Is Google load-bearing? | Cloud Run revision → Firestore record | Gemini 3.7 + ADK handoff, atomic request key, attempt metadata |
| 1:30 | Are agents actually working? | Split view: repository edit, test run, `awaiting-verification`, other-family verdict | Continuous owner-to-verifier sequence |
| 2:25 | Is completion enforceable? | Final state and evidence command | Every `done` item has `owner != verified_by` |
| 3:05 | Is it production-minded? | ADK eval gate and metadata-only trace | 3/3 at 1.00/1.00; prompt capture disabled |
| 3:35 | What does the user receive? | Final executive email | Outcome, evidence, residual risk, and no console archaeology |

The polished entry may use clearly labeled elapsed-time cuts. Publish the full,
unedited golden run beside it. Keep the send, intake, first scope, and one
owner-to-verifier transition continuous in the four-minute cut.

## Claim-to-receipt index

| Claim | Primary implementation | Automated proof | Visual proof |
|---|---|---|---|
| No self-approval | `src/envelope.py` | `tests/test_envelope.py` | Rejected owner transition, then different-family verification |
| Distinct model families | `src/agents.py` | `tests/test_agents.py` | Claude and Gemini watermarks in one thread |
| Durable email intake | `src/worker/index.js`, D1 schema | runner reliability tests | Queued D1 row before acknowledgement |
| Retry-safe coordination | `cloud/store.py`, `cloud/service.py` | store/service recovery and fencing tests | Failed record resumes with incremented attempt |
| Governed discovery | `cloud/agent_catalog.json`, `cloud/catalog.py` | catalog schema and auth tests | Authenticated `/v1/agents` response |
| Gemini is load-bearing | `cloud/rally_adk/agent.py` | live ADK eval set | Cloud trace from request through Gemini span |
| Cloud is not decorative | Cloud Run, Firestore, Secret Manager, Trace Terraform | `make infra-check` | Revision, record, IAM policy, and trace waterfall |
| Bounded autonomy | runner and transport limits | policy and reliability suite | Exact halt report for one controlled failure |
| Reproducible build | Makefile, Dockerfile, Terraform, CI | `make release-check` | Clean release-gate terminal |

## What to say about model choice

Gemini 3.7 Flash through Vertex AI and Google ADK is the intake coordinator. It
preserves the commission verbatim, makes the single bounded handoff, and creates
the governance record before repository execution starts. Claude and
Antigravity/Gemini are licensed coding workers. They have symmetric build and
review abilities, but the runner assigns incompatible authority so the owner of
an item cannot verify it. The standard profile keeps a deliberative worker pin;
the filmed profile uses Gemini 3.7 Flash for predictable latency.

That is a deliberate allocation by workload, not a compatibility workaround.
The required Gemini 3.5+ path is substantive and visible.

## Fast answers to likely objections

**“Is this two agents role-playing in one prompt?”**  No. Two separate CLI
executions from different model families share a real workspace. Their output
is parsed by a deterministic state machine, and every turn is independently
emailed.

**“Could both agents simply agree?”**  Agreement is insufficient. A checklist
item can reach `done` only through a legal state transition naming a verifier
from the other model family and retaining evidence.

**“Why is repository execution local?”**  The current Claude and Antigravity
workers are licensed desktop CLIs. Rally honestly keeps execution on the
controlled licensed host while placing identity, durable coordination, memory,
catalog discovery, and telemetry on Google Cloud.

**“Why not Gemini Enterprise Agent Platform?”**  It is recommended, not
required. Rally proves the Fortified concerns directly with Google ADK, Vertex
AI, Cloud Run, Firestore, IAM, Secret Manager, and OpenTelemetry. The official
rules require Gemini 3.5+, one listed Google agent framework, and one Google
Cloud infrastructure service; Rally uses all three categories in load-bearing
roles.

**“What if a webhook or worker crashes?”**  Edge events remain in D1 until
successful handling. Exact delivery reuses the original request key. Failed or
lease-expired coordination can be reclaimed, while attempt fencing prevents the
stale owner from overwriting the new attempt.

## Judge-visible numbers

- 63 automated deterministic tests: 53 product tests + 10 cloud tests
- 3 live ADK evaluation cases
- 1.00 tool trajectory score
- 1.00 response-quality score
- 2 independent model families
- 0 allowed self-approvals
- 1 authenticated, versioned fleet catalog
- 30-day declared Cloud coordination retention horizon

## Truth boundary

Do not describe Cloud Run, Firestore, Trace, or Artifact Registry as live until
the post-deploy evidence checklist passes. Before then, use: **implemented,
tested, containerized, and Terraform-validated; deployment pending approval.**

Do not say email delivers every model turn. The first email starts the real run,
the authoritative runner dispatches subsequent turns, and email mirrors each
turn plus the final report.

## Assets and tabs

Prepare these in order before recording:

1. Inbox compose window with the golden commission.
2. Narrow `make serve` terminal with secrets absent.
3. Sanitized repository diff/test split view.
4. [`rally-architecture.png`](assets/rally-architecture.png).
5. Cloud Run revision, Firestore record, agent catalog, and Cloud Trace tabs.
6. Sanitized ADK eval result.
7. Final email thread.

The official source of truth is the
[All Things Agentic rules](https://allthingsagentichackathon.devpost.com/rules).
