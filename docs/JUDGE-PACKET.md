# Rally judge packet

## The thesis

**Rally turns the AI models a company already trusts into one accountable team.
One difficult goal comes in; Gemini governs the handoff; Gemini, Claude, and
OpenAI Codex do visible work and review; and one independently verified result
comes out.**

Primary category: **Fortified Enterprise Fleet**.

The category fit is not “we used several agents.” Rally makes isolated models
behave like one accountable company team, then provides discovery,
runtime and memory, security and governance, and telemetry for agents that can
modify production repositories. The unlikely hero is a nontechnical product or
operations leader commissioning that work from a phone.

## The four-minute proof order

| Time | Judge question | Live proof | Receipt |
|---|---|---|---|
| 0:00 | Is this useful? | Give the accountable AI team one hard goal by email | One familiar identity; no CLI or key for the commissioner |
| 0:25 | Is it really an agent system? | First scoped checklist email | Distinct run ID and model-family watermark |
| 0:55 | Is Google load-bearing? | Cloud Run revision → Firestore record | Gemini 3.7 + ADK handoff, atomic request key, attempt metadata |
| 1:30 | Are agents actually working? | Split view: repository edit, test run, `awaiting-verification`, other-family verdict | Continuous owner-to-verifier sequence |
| 2:25 | Is completion enforceable? | Final state and evidence command | Every `done` item has `owner != verified_by` |
| 3:05 | Is it production-minded? | ADK eval gate and metadata-only trace | 6/6 at 1.00/1.00; prompt capture disabled |
| 3:35 | What does the user receive? | Final executive email | Outcome, evidence, residual risk, and no console archaeology |

The polished entry may use clearly labeled elapsed-time cuts. Publish the full,
unedited golden run beside it. Keep the send, intake, first scope, and one
owner-to-verifier transition continuous in the four-minute cut.

## Claim-to-receipt index

| Claim | Primary implementation | Automated proof | Visual proof |
|---|---|---|---|
| No self-approval | `src/envelope.py` | `tests/test_envelope.py` | Rejected owner transition, then different-family verification |
| Distinct model families | `src/agents.py` | `tests/test_agents.py` | Gemini, Claude, and OpenAI worker identities in the roster and thread |
| Per-user authorization | connector profiles + native CLI sign-in | connector isolation and adapter tests | One-way profile ID; no pooled token or seat |
| Durable email intake | `src/worker/index.js`, D1 schema | runner reliability tests | Queued D1 row before acknowledgement |
| Retry-safe coordination | `cloud/store.py`, `cloud/service.py` | store/service recovery and fencing tests | Failed record resumes with incremented attempt |
| Cross-model recovery | `src/runner.py`, `src/envelope.py` | Second Wind runner and custody-transfer tests | Backup repairs a blocker but cannot self-approve |
| Governed discovery | `cloud/agent_catalog.json`, `cloud/catalog.py` | catalog schema and auth tests | Authenticated `/v1/agents` response |
| Gemini is load-bearing | `cloud/rally_adk/agent.py` | live ADK eval set | Cloud trace from request through Gemini span |
| Cloud is not decorative | Cloud Run, Firestore, Secret Manager, Trace Terraform | `make infra-check` | Revision, record, IAM policy, and trace waterfall |
| Bounded autonomy | runner and transport limits | policy and reliability suite | Exact halt report for one controlled failure |
| Reproducible build | Makefile, Dockerfile, Terraform, CI | `make release-check` | Clean release-gate terminal |

## What to say about model choice

Gemini 3.7 Flash through Vertex AI and Google ADK is the intake coordinator. It
preserves the commission verbatim, makes the single bounded handoff, and creates
the governance record before workspace execution starts. Claude,
Antigravity/Gemini, and OpenAI Codex are licensed CLI workers using the
operator's own provider sign-ins. They have symmetric build and review abilities,
but the runner assigns incompatible authority so the owner of
an item cannot verify it. The standard profile keeps a deliberative worker pin;
the filmed profile uses Gemini 3.7 Flash for predictable latency.

That is a deliberate allocation by workload, not a compatibility workaround.
The required Gemini 3.5+ path is substantive and visible.

## Fast answers to likely objections

**“Is this agents role-playing in one prompt?”**  No. Separate provider-native
CLI executions from different model families share a real workspace. Their output
is parsed by a deterministic state machine, and every turn is independently
emailed.

**“Could the agents simply agree?”**  Agreement is insufficient. A checklist
item can reach `done` only through a legal state transition naming a verifier
from a different model family and retaining evidence.

**“Why is repository execution local?”**  The current Claude, Antigravity, and
Codex workers are licensed CLIs. Rally honestly keeps execution on the
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

- 259 automated deterministic tests: 88 product tests + 171 Cloud/A2A/connector tests
- 6 live ADK evaluation cases
- 1.00 tool trajectory score
- 1.00 response-quality score
- 3 live-authenticated worker model families
- 0 allowed self-approvals
- 1 authenticated, versioned fleet catalog
- 30-day declared Cloud coordination retention horizon

## Truth boundary

The post-deploy evidence checklist passed on August 29, 2026. Tie every live
claim to the private Cloud Run revision, Firestore record, IAM policy, or
content-free Trace shown in the demo; never substitute a diagram for that proof.

Do not say email delivers every model turn. The first email starts the real run,
the authoritative runner dispatches subsequent turns, and email mirrors each
turn plus the final report.

## Assets and tabs

### Live proof anchors — August 29, 2026

Use these identifiers to open the genuine records before recording. Keep tokens,
request keys, account menus, and raw prompt fields off screen.

| Surface | Live anchor |
|---|---|
| Public product + professional proof run | <https://rally.agent9.dev/#demo> — `r-20260830-447f2f` |
| Cloud project | `rally-agent9-2026` |
| Cloud Run | `rally-google-coordinator-00006-v7q` in `us-east1` |
| Coordinator digest | `sha256:b4c8a20343aaeec64a602b108bfdcb73fa723525af1498cba0fa15c0fe64d769` |
| Hosted control plane | `rally-control-plane-00006-cnp`; `sha256:8d8de1f7c6877c1124d2b78ff34452f88c9420b7e2b5ba83a7d91d1af3e1c532` |
| Release Cloud Build | `fa539b5b-5966-440f-b55e-f143206db59e` (`SUCCESS`) |
| Firestore proof record | `r-cloud-redaction-20260829` in `(default)` |
| Content-free Cloud Trace | `05b54fcc39e0f869fcb486ed62d5350f` — eight linked spans, all ADK payload attributes `{}` |
| Cloudflare Worker | `rally-ingress` version `f9942b51-ac13-451d-a711-9636792c0c06` |
| Pages production release | `4993d978.agent9-rally.pages.dev`; branded origin <https://rally.agent9.dev/> |
| Submission source | <https://github.com/Agent9AI/rally> — keep `main` private during final hardening, then make it public under Apache-2.0 and record the frozen submission commit |

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
