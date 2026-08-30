# Rally: Technical Specification

**Version 1.1. 2026-08-30.** This is the concrete build. It fills in the blanks left
by [FOUNDING.md](FOUNDING.md), which remains the authority on intent. Where this
document and the founding document disagree, the founding document is right and
this one has a bug.

---

## 1. Stack

| Concern | Choice |
|---|---|
| Transport, both directions | Resend (inbound webhook, outbound API) |
| Agent A | Claude CLI (`claude -p`) |
| Agent B | Antigravity CLI (`agy -p`) |
| Agent C | OpenAI Codex CLI (`codex exec`) |
| Durable ingress | Cloudflare Worker + D1 |
| Intake coordinator | Google ADK + Gemini 3.7 on Cloud Run |
| Coordinator state | Firestore, atomically idempotent by mail message ID |
| Secrets and telemetry | Secret Manager, Cloud Logging, Cloud Trace |
| Turn execution | Local runner on a machine hosting the authorized CLIs |
| Work product | Git checkout, one branch per run |

Provider-native command line agents rather than raw model APIs, for the reason
given in founding section 11: the unit of work is a shell invocation, so the
harness stays small and a new family is an adapter rather than a new architecture.

## 2. Identities

```
updates.agent9.dev
  rally@updates.agent9.dev      Human commission address
  claude@updates.agent9.dev     Agent A mailbox
  agy@updates.agent9.dev        Agent B mailbox
  codex@updates.agent9.dev      Agent C mailbox
```

The sending domain and API key are shared with existing projects. This is a
deliberate, accepted trade recorded here so it is not mistaken for an oversight:
Rally's quota and sending reputation are shared, so a runaway loop is a
cross-project incident, not a Rally-only one. The mitigation is section 9's
circuit breaker, which is therefore load bearing rather than defensive polish.

If Rally is later moved to its own subdomain and key, nothing in this spec changes
except the two addresses and the credential.

## 3. The message envelope

Every Rally message is valid email a human can read, carrying a machine-readable
block. Nothing is hidden in headers that is not also visible in the body.

**Subject:** `[rally #<run_id> t<turn>] <task_title>`

**Headers:**

```
X-Rally-Run:   r-20260828-a1b2c3
X-Rally-Turn:  7
X-Rally-From:  claude | agy | codex
Auto-Submitted: auto-generated
In-Reply-To / References: standard threading to the commission message
```

`Auto-Submitted` keeps well-behaved autoresponders from joining the conversation.

**Body:** prose first, written to the other agent as a colleague, then a single
fenced `json` block:

```json
{
  "rally_version": 1,
  "run_id": "r-20260828-a1b2c3",
  "turn": 7,
  "from_agent": "claude",
  "to_agent": "agy",
  "task_title": "Add rate limiting to the public API",
  "commit": "3d4fa997549163f7298c9fbc2bd3f3cf9ef9f85e",
  "budget": {
    "turns_used": 7, "turns_max": 24,
    "sends_used": 7, "sends_max": 60,
    "no_progress_streak": 0
  },
  "checklist": [
    {
      "id": "c3",
      "description": "Requests over the limit return 429 with Retry-After",
      "state": "awaiting-verification",
      "owner": "claude",
      "verified_by": null,
      "evidence": "tests/rate_limit_test.py::test_429_sets_retry_after passes",
      "rejections": 0
    }
  ],
  "narrative": "One paragraph: what I did this turn and what I want checked.",
  "halt": null
}
```

Item states, as founding section 5: `open`, `claimed`, `awaiting-verification`,
`done`, `blocked`, plus `disputed` introduced in section 7 below.

`halt` is `null` during normal operation, or an object `{reason, detail}` where
reason is one of `complete`, `turn_budget`, `no_progress`, `disputed`, `blocked`,
`stopped_by_human`.

**Schema enforcement.** The canonical schema lives at `schema/envelope.json`.
Every adapter's output is validated and gets exactly one reprompt on failure
before the turn is recorded as failed. Antigravity may additionally use its
native schema mode; Codex writes its final response separately so CLI progress
cannot corrupt the envelope.

## 4. Two planes

The control plane is email. The data plane is git.

Each run gets a branch, `rally/<run_id>`. An agent's turn ends with a commit, and
the envelope carries that commit SHA. This is what makes a message
self-describing: it states both what the agent believes and precisely which tree
that belief refers to. A reader of any single message can check out that SHA and
see exactly what the agent saw.

The founding document's first open question asked whether state travels in the
message or lives in a shared workspace. It is both, split by kind: **decisions and
progress travel in the message, artifacts live in git, and the SHA is the join.**

## 5. Authority, and why the envelope is not trusted

The runner keeps its own record of every run: current turn, checklist, budget
counters, branch. **That local record is authoritative. The envelope is an audit
and recovery record, not a source of truth.**

This matters because anyone who learns the addresses can send mail that looks like
a Rally message. Headers are trivially forged. So an inbound message is accepted
only when it matches local state: known `run_id`, sender address matching the
agent whose turn it actually is, and `turn` exactly one greater than the last
processed turn. Anything else is dropped and logged.

Replay is handled by the same rule. A duplicate delivery carries a turn number
already processed, so it is discarded. This is also the complete answer to the
founding document's second open question: overlapping claims cannot occur, because
only one agent holds the turn and the turn number is monotonic.

A human reply into the thread is the one inbound message exempt from the turn
rule. It does not consume a turn and does not increment the counter. It is queued
as input to the next agent turn, so a person can write into a run without
disturbing its arithmetic.

If the local store is ever lost, the last message in the thread is enough to
rebuild it. That is the recovery path, used deliberately, not automatically.

## 6. Turn lifecycle

1. **Commission.** A verified human sends a task to `rally@`. The runner creates
   the run, allocates `run_id`, sends an authenticated and idempotent handoff to
   the Google ADK coordinator, cuts the workspace, and sets turn 0.
2. **Scoping.** The first configured worker converts the goal into a checklist
   and hands it to the next family. No work yet.
3. **Negotiation.** Antigravity accepts, splits, adds, or challenges items.
   Agreement on the checklist precedes work.
4. **Work turns.** Agents rotate deterministically. Each turn: verify what another worker left
   in `awaiting-verification`, then advance one or more of your own items, commit,
   mail the envelope.
5. **Completion.** When every item is `done`, the agent holding the turn writes
   the human report.
6. **Recover or halt.** With Second Wind enabled, the first model-process failure
   or newly reported blocker creates a bounded recovery event and hands the last
   accepted state to the next family. A human stop, authority boundary, hard
   budget, repeated dispute, exhausted recovery allowance, or unresolved backup
   review ends the run with `halt` set and a message to the human.

The invariant that makes independent agents worth their cost: **an item may only
move to `done` by an agent that does not own it.**

## 7. Verification, rejection, dispute

Resolving founding open questions three and four.

**Rejection.** A verifier that finds an item wanting sets it back to `claimed`,
increments `rejections`, and states specifically what failed. The author retains
ownership and fixes it.

**Verifier repair.** On the second failure of the same item, the verifier may fix
it directly. Ownership then flips: the original author must verify the repair.
The "never verify your own work" invariant holds, and the reject loop terminates.

**Second Wind recovery.** A process timeout, non-zero exit, repeated malformed
envelope, or `blocked` item is recoverable only when the run's captured
`continuity.second_wind` policy is enabled and its recovery allowance remains.
The runner—not either model—authorizes a one-turn custody transfer for named
`claimed` or `blocked` items. The backup may move them to `claimed` or
`awaiting-verification`; it may not move them to `done`. The full recovery event
is persisted and sanitized into the public console timeline. A block the backup
confirms is escalated rather than bounced back indefinitely.

**Dispute.** An agent may reject a given item at most twice. A third disagreement
sets the item to `disputed` and halts the run. The human receives one message
containing both positions stated plainly and the diff under discussion. This
prevents infinite polite ping-pong without escalating every trivial nit.

## 8. Agent invocation

All adapters are thin. They build a prompt, run one command, parse one envelope.

**Claude:**

```bash
cd "$RUN_WORKDIR" && timeout "$TURN_TIMEOUT_SEC" \
  claude -p --model "$RALLY_CLAUDE_MODEL" --effort "$EFFORT" \
         --output-format json "$TURN_PROMPT"
```

**Antigravity:**

```bash
cd "$RUN_WORKDIR" && timeout "$TURN_TIMEOUT_SEC" \
  agy --model "$RALLY_AGY_MODEL" --effort "$EFFORT" \
      --output-format json --json-schema "$RALLY_ROOT/schema/envelope.json" \
      --print-timeout 25m -p="$TURN_PROMPT"
```

**OpenAI Codex:**

```bash
cd "$RUN_WORKDIR" && timeout "$TURN_TIMEOUT_SEC" \
  codex exec --model "$RALLY_CODEX_MODEL" --cd "$RUN_WORKDIR" \
        --ephemeral --ignore-user-config --skip-git-repo-check \
        --approve-for-me --output-last-message "$PRIVATE_RESULT" "$TURN_PROMPT"
```

Codex uses each operator's own Sign in with ChatGPT session. It is ephemeral and
ignores global user configuration; Rally adds back only the immutable run-scoped
connector gateway. The provider account and connector profile are never shared
or pooled across users.

**The prompt must be attached to the flag as `-p=...`, and it must come last.**
`agy` parses flags Go style, so a bare `-p` swallows the next token: written as
`agy -p --model gemini-3.1-pro-high "prompt"`, the CLI takes `--model` as the
prompt and silently discards the real one. Verified on 2026-08-28.

`agy --print-timeout` defaults to five minutes, which is far too short for real
work, so it is always set explicitly. Its `--effort` scale is `low|medium|high`
with no higher rungs, so any richer internal scale maps down onto it.

**Model pinning is a guardrail, not a setting.** `agy models` offers
`claude-sonnet-4-6` and `claude-opus-4-6-thinking` alongside the Gemini family.
Left unpinned, Rally can silently become one model family reviewing itself, which
deletes the entire premise of founding section 3. The runner therefore refuses to
start a turn unless every configured worker declares a distinct family and the
Antigravity worker remains pinned to `gemini-*`. Defaults are
`gemini-3.1-pro-high`, `opus`, and `gpt-5.4`.

**Placement.** The configured CLIs must be on the machine running the turn. `agy` ships with
the Antigravity desktop application rather than a package registry, so the runner
lives wherever that is installed. The runner is otherwise host agnostic and holds
no assumption about which machine it is.

## 9. Guardrails

Founding section 7, made numeric. Every limit is enforced by the runner, outside
the agents' reach, because the failure being defended against is an agent behaving
unexpectedly.

| Guard | Default | On breach |
|---|---|---|
| Turn budget | 24 turns per run | halt `turn_budget`, report to human |
| No-progress halt | 4 turns with no item changing state | halt `no_progress` |
| Rejections per item | 2, then dispute | halt `disputed` |
| Sends per run | 60 | halt, refuse to send |
| Sends per hour, all runs | 30 | queue, do not send |
| Sends per day, all runs | 200 | halt all runs |
| Second Wind | 2 recovery handoffs | switch model family, then halt when exhausted |
| Turn wall clock | 25 minutes | preserve accepted state, invoke Second Wind if enabled, then halt |

The hourly and daily ceilings are global rather than per run, because the quota
being protected is shared with unrelated projects. They are checked in the runner
before every send and independently in the Worker before it accepts work.
**Both fail closed:** if the counter store cannot be read, no send happens. A
Rally outage is an acceptable outcome; taking down the shared sending domain is
not.

## 10. The human

**Commission** is restricted to verified senders. Authority comes from the
verified sender identity, never from the body of a message asking to be trusted.

**Visibility.** The human is CC'd on every agent-to-agent message. The subject tag
`[rally #<run_id>]` and standard reply headers make that one thread, so it can be as loud
or as quiet as they choose without Rally needing a dashboard. This answers the
founding document's fifth open question.

**Intervention.** Because the bus is email, the human can simply reply into the
thread. Their message is injected as input to the next turn, ahead of the
counterpart's envelope. A reply of `STOP` halts the run immediately, and the halt
does not require the agents to cooperate: the runner refuses the next turn.

**The report.** One message on completion, written to founding section 9's bar:
what was asked, what was built, what was verified and how, what to look at first,
what remains open. Not a transcript.

## 11. Security

- **Inbound mail is data, never instruction.** Message content is reasoned about,
  never obeyed. A message that asks an agent to change its budget, skip
  verification, or mail a credential is content to report, not a command.
- **Local state is authoritative** over anything asserted in a message, per
  section 5.
- **No secrets in mail.** Envelopes and reports never carry keys, tokens, or
  signed URLs. The runner scrubs outbound bodies against the known credential set
  before handing them to Resend.
- **Commission authority** comes from verified sender identity only.
- **Blast radius is accepted and bounded** by section 9's fail-closed ceilings.
- **Cloud Run is dual authenticated.** Google IAM admits the configured operator
  and the application independently checks a Secret Manager-backed token.
- **Retries do not duplicate work.** The edge deduplicates provider events and
  Firestore atomically claims the original mail message ID before Gemini runs.
- **Telemetry excludes content.** Trace and structured logs carry execution
  metadata, IDs, status, and latency, never prompts or responses.

## 12. Repository layout

```
rally/
  docs/FOUNDING.md          charter, intent, principles
  docs/SPEC.md              this document
  schema/envelope.json      canonical envelope schema
  src/worker/               Cloudflare Worker: inbound webhook, durable queue
  src/runner.py             run store, turn dispatch, budget enforcement
  src/agents.py             Claude, Antigravity, and Codex adapters
  src/cloud_coordinator.py  authenticated Cloud Run bridge
  cloud/rally_adk/          ADK + Gemini intake agent
  cloud/service.py          Cloud Run HTTP service
  cloud/store.py            Firestore idempotency and run records
  cloud/infra/              production Terraform
  config/                   defaults, model pinning, limits
  tests/                    envelope validation, state machine, guard breaches
  scripts/                  operational helpers
```

## 13. Open items

- Whether `agy` can run on arm64 Linux, which would let the runner leave the
  desktop machine. Unknown, and the design deliberately does not depend on it.
- Whether the scoping turn should be allowed to run twice when two agents
  produce very different checklists, or whether first disagreement should go
  straight to negotiation.
- Retention: how long run branches and threads are kept before archival.
