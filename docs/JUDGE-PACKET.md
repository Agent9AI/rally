# Rally judge packet

## The thesis

**Rally gives companies accountable AI teammates employees can email like
coworkers. One familiar message commissions the work; Gemini governs the
handoff; independent model families execute and review; and one verified result
with receipts returns in the same thread.**

Primary category: **Fortified Enterprise Fleet**.

The category fit is not “we used several agents.” Rally gives people a stable
role while making isolated models behave like one accountable company team,
then provides discovery, durable execution state, security and governance, and
telemetry for agents that can modify production repositories. The unlikely hero
is Terry, the owner-operator of a five-person professional-services firm who can
commission that work from a phone without becoming an AI platform engineer.

## The four-minute proof order

| Time | Judge question | Evidence surface | Run or receipt |
|---|---|---|---|
| 0:00 | Is this useful for the unlikely hero? | Terry emails one finished outcome for his five-person firm | Live capture run ID visible |
| 0:22 | Is it really running? | Send → durable queue → state change, continuously | Actual live capture run; never borrow another run's numbers |
| 0:52 | Is Google load-bearing? | Cloud Run revision → Firestore or Trace record | Gemini 3.7 Flash + ADK handoff and atomic request key |
| 1:24 | Are agents doing and rejecting real work? | Owner work → `awaiting-verification` → other-family verdict | Primary outcome history `r-20260831-48141a` |
| 2:24 | Is checklist authority enforceable? | Sanitized receipt, audit, and committed artifact | `r-20260831-48141a`: 13 turns, 6/6; 882-word checkpoint with 22/22 audited claims; delivery receipt |
| 2:56 | Does recovery preserve authority? | Two recovery log lines under a separate-run label | `r-20260830-447f2f`: successful Second Wind recovery for c6 |
| 3:16 | Is it production-minded? | ADK eval, 369-test receipt, metadata-only trace | 6/6 at 1.00/1.00; prompt capture disabled |
| 3:43 | What does the user receive? | Final brief and delivery receipt | Primary run only; no console archaeology |

The entry itself should contain a genuine continuous live execution. The safest
organizer-confirmed treatment is a single take with no cuts or splices; if time
compression is necessary, accelerate the entire take uniformly and keep the
factor visible on screen. Publish the complete 1× capture beside the entry. If
`r-20260831-48141a` was not captured continuously, use a new run for the live
sequence and identify its actual ID rather than calling a replay “live.”

## Claim-to-receipt index

The committed [public evidence index](evidence/) contains the sanitized primary
checkpoint and the separate Second Wind receipt. Runtime `runs/` state remains
gitignored because it can contain commissioner and provider metadata.

| Claim | Primary implementation | Automated proof | Visual proof |
|---|---|---|---|
| No self-approval | `src/envelope.py` | `tests/test_envelope.py` | Rejected owner transition, then different-family verification |
| Distinct model families | `src/agents.py` | `tests/test_agents.py` | Gemini, Claude, and OpenAI worker identities in the roster and thread |
| Per-user authorization | connector profiles + native CLI sign-in | connector isolation and adapter tests | One-way profile ID; no pooled token or seat |
| Private work dashboard | `src/worker/index.js`, D1 workspace index, `/admin/` | workspace-isolation contract | Signed-in Work queue and run receipt; Connections are a separate view |
| Durable email intake | `src/worker/index.js`, D1 schema | runner reliability tests | Queued D1 row before acknowledgement |
| Retry-safe coordination | `cloud/store.py`, `cloud/service.py` | store/service recovery and fencing tests | Failed record resumes with incremented attempt |
| Cross-model recovery | `src/runner.py`, `src/envelope.py` | Second Wind runner and custody-transfer tests | Separate run `r-20260830-447f2f`: Claude → Gemini recovery for c6; backup cannot self-approve |
| Governed discovery | `cloud/agent_catalog.json`, `cloud/catalog.py` | catalog schema and auth tests | Authenticated `/v1/agents` response |
| Gemini is load-bearing | `cloud/rally_adk/agent.py` | live ADK eval set | Cloud trace from request through Gemini span |
| Cloud is not decorative | Cloud Run, Firestore, Secret Manager, Trace Terraform | `make infra-check` | Revision, record, IAM policy, and trace waterfall |
| Bounded autonomy | runner and transport limits | policy and reliability suite | Exact halt report for one controlled failure |
| Reproducible build | Makefile, Dockerfile, Terraform, CI | `make release-check` | Clean release-gate terminal |

## What to say about model choice

Gemini 3.7 Flash through Vertex AI and Google ADK is the model-mediated intake
gate. The agent is instructed and evaluated to call the one bounded handoff tool
with the complete commission. Deterministic service code normalizes and persists
the handoff and governance record before workspace execution starts, and marks
the record ready only after the coordinator returns.
Claude, Antigravity/Gemini, and OpenAI Codex are licensed CLI workers using the
operator's own provider sign-ins. They have symmetric build and review
abilities, but the runner assigns incompatible authority so the owner of an item
cannot verify it. The standard profile keeps a deliberative worker pin; the
filmed profile uses Gemini 3.7 Flash for predictable latency.

That is a deliberate allocation by workload, not a compatibility workaround.
The required Gemini 3.5+ path is substantive and visible.

xAI Grok Build is a fourth-family candidate, not a launch claim. Its safe
adapter uses a dedicated profile and disables memory, subagents, automatic
updates, and web search. It remains outside the active fleet and cannot enter a
connector-backed run until Rally can prove sole-gateway MCP isolation and a
live symmetric execution test.

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
controlled licensed host while placing identity, durable coordination, state,
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

- 369 automated deterministic tests: 183 product tests + 186 Cloud/A2A/connector tests
- 6 live ADK evaluation cases
- 1.00 tool trajectory score
- 1.00 response-quality score
- 3 live-authenticated worker model families
- 0 allowed self-approvals
- 1 authenticated, versioned fleet catalog
- 30-day declared Cloud coordination retention horizon

## Truth boundary

The post-deploy evidence checklist passed again on August 31, 2026. Tie every live
claim to the private Cloud Run revision, Firestore record, IAM policy, or
content-free Trace shown in the demo; never substitute a diagram for that proof.

Run `r-20260831-48141a` completed in 13 turns with 6/6 checklist items
independently verified across three model families. Its committed 882-word
checkpoint has 22/22 audited claims supported, and the final report was
delivered. During Gemini turn 7, concurrent
operator edits to three submission documents triggered Rally's advisory
repo-containment fingerprint. The edits were not made by the agent; retain the
event as honest evidence that the monitor detected an external tree change.

After that audit was verified, Claude added one pricing claim and asked to open
c7 because it could not self-approve the change. Rally rejected the late scope
addition but did not invalidate the earlier artifact verification; the
workspace therefore ended at 897 words without that new claim entering the
22-claim audit. Use the committed
[`docs/evidence/r-20260831-48141a/`](evidence/r-20260831-48141a/) snapshot for
the audit claim and disclose the late mutation. The delivered report retained
an even earlier 834-word checkpoint. That run's one Second Wind attempt ended
unresolved and required an authenticated human resume. The successful recovery
receipt is the separate run `r-20260830-447f2f`, where Claude handed c6 to
Gemini and the runner recorded `SECOND WIND RECOVERED`. Never combine those
histories.

Do not claim Memory Bank, Agent Runtime, Gemini Enterprise Agent Platform, or a
Gemma/Veo/Lyria bonus integration. Rally uses its own durable state and a
controlled licensed-worker host, with Gemini 3.7 Flash via Vertex AI, Google
ADK, Cloud Run, and Firestore as the mandatory load-bearing Google stack.

Do not say email delivers every model turn. The first email starts the real run,
the authoritative runner dispatches subsequent turns, and email mirrors each
turn plus the final report.

## Assets and tabs

### Live proof anchors — August 31, 2026

Use these identifiers to open the genuine records before recording. Keep tokens,
request keys, account menus, and raw prompt fields off screen.

| Surface | Live anchor |
|---|---|
| Public product + separate recovery proof | <https://rally.agent9.dev/#demo> — `r-20260830-447f2f`; 11 turns, 6/6, 36-claim presentation, successful Second Wind for c6 |
| Primary email run | [`docs/evidence/r-20260831-48141a/`](evidence/r-20260831-48141a/) — 13 turns, 6/6; 882-word checkpoint with 22/22 audited claims; report delivered; later mutation disclosed |
| Cloud project | `rally-agent9-2026` |
| Private ADK coordinator | `rally-google-coordinator-00007-xpq` |
| Hosted control plane | `rally-control-plane-00011-pg6` |
| Both Cloud Run images | `sha256:b1836e2224518a8bed51da7e02ef256aeba1aeeae858808f470a0d02d33fa6e2` |
| Release Cloud Build | `58a580b6-c6d2-45d6-945b-8fc1bb643cd5` (`SUCCESS`) |
| Firestore proof record | `r-cloud-redaction-20260829` in `(default)` |
| Content-free Cloud Trace | `05b54fcc39e0f869fcb486ed62d5350f` — eight linked spans, all ADK payload attributes `{}` |
| Cloudflare Worker | `rally-ingress` version `757237b2-8c72-4429-913a-f854d014cf2a` |
| Hosted product | <https://rally.agent9.dev/> — Pages deployment <https://f2d67f82.agent9-rally.pages.dev/> |
| Submission source | <https://github.com/Agent9AI/rally> — repository remains private during final hardening; pin the final release commit after the submission freeze |

Prepare these in order before recording:

1. Inbox compose window with the executive-brief commission.
2. Narrow `make serve` terminal with secrets absent.
3. Sanitized primary-run brief, source ledger, audit, and checklist view.
4. [`rally-architecture.png`](assets/rally-architecture.png).
5. Cloud Run revision, Firestore record, agent catalog, and Cloud Trace tabs.
6. Sanitized ADK eval result.
7. Final email thread for `r-20260831-48141a`.
8. Two-line recovery receipt for `r-20260830-447f2f`, visibly labeled as a
   separate run.

The official sources of truth are the
[All Things Agentic rules](https://allthingsagentichackathon.devpost.com/rules)
and the Devpost manager's
[continuous uniform-speed guidance](https://allthingsagentichackathon.devpost.com/forum_topics/44809-demo-video-is-speeding-up-the-whole-recording-allowed-under-unedited).
