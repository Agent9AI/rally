# Four-minute demo script

The story is **your AIs, finally on the same team**—made accountable by **one
request, three model families, and zero self-approval**. Keep the human's goal and
finished outcome as the heroes. Terminal and Cloud Console are evidence, not
the product.

## Before recording

- Use `config/rally.demo.json`; confirm `./bin/rally --check --smoke` is green.
- Start `make serve` and keep its terminal narrow enough to read on video.
- Open the inbox, Cloud Run service page, one Cloud Trace, and the latest run's
  `state.json` before recording.
- Hide bookmarks, account menus, tokens, webhook URLs, and Secret Manager values.
- Record the live run first. Then record narration and use jump cuts while the
  agents work; do not make viewers wait through inference.
- Preserve a second, complete unedited capture of the golden run and link it as
  supporting proof. In the four-minute entry, keep the email send, intake, first
  scope turn, and one owner-to-verifier transition continuous and uncut; label
  every later elapsed-time jump explicitly.

Use this commission:

> Create a polished, self-contained HTML presentation for an executive AI strategy meeting covering the most consequential Google AI product launches and major releases from 2025-08-29 through 2026-08-29. Use primary Google sources only. For every included launch, show the release date, what changed, who it matters to, a concrete business use, and a source URL. Include an executive synthesis, a coverage appendix grouped by product family, and a machine-readable claim ledger. Do not guess: unsupported or disputed claims must be omitted or labeled. Add automated checks for required sections, dates, source URLs, and local presentation loading. Every factual claim and the finished presentation must be independently verified.

## Timeline

### 0:00–0:25 — Hook

Visual: compose an email to `rally@updates.agent9.dev` and press Send.

Narration:

> Companies are collecting powerful AI assistants, but people still manage the
> handoffs and decide which answer to trust. Rally puts those models on one
> accountable team. I send one difficult outcome by email; Gemini, Claude, and
> OpenAI Codex work it to completion, and none can approve what it owns.

### 0:25–0:55 — The product surface

Visual: inbox and the first polished, watermarked turn from Claude.

> There is no seat, plugin, or prompt training for the user. Email is the entry
> point, audit trail, and intervention channel. The first turn scopes a concrete
> checklist before anyone starts the work.

Point briefly to run ID, sender watermark, status, and collapsed technical
record. Do not read the whole email.

### 0:55–1:30 — Google is load-bearing

Visual: architecture diagram, then Cloud Run revision and Firestore record.

> Behind that email, an IAM-protected Cloud Run service runs a Gemini 3.7 agent
> built with Google ADK. It preserves the request verbatim and records the
> handoff in Firestore. The mail message ID is the idempotency key, claimed in
> one transaction, so webhook retries cannot launch duplicate work.

Show the service name, revision, Gemini model, and `ready_for_rally` status. Do
not open the raw commission field.

### 1:30–2:25 — Multi-agent proof

Visual: jump through the email thread: Claude → AGY/Gemini → OpenAI Codex → Claude.

> Now the model families alternate. Each turn must first inspect work waiting
> for review, then advance its own items. These are real CLI executions and real
> emails—not role-play inside one prompt.

Pause on one item moving to `awaiting-verification`, then on the other model's
evidence moving it to `done`.

> The critical rule lives in Python, outside every prompt. If an owner marks its
> own item done, Rally reverts the transition and records a violation.

Keep one continuous split view on screen long enough to show an agent researching
primary sources and assembling the deck, its presentation checks running, the
item entering `awaiting-verification`, and the other model checking dates,
citations, claims, and the rendered artifact. This is the proof of action; do
not replace it with narration or a static final state.

Use the 2026-08-30 professional proof as the narrative beat: the first deck was
not accepted because independent review caught one wrong release date and one
unsupported feature claim. Rally preserved the accepted state, handed the repair
forward, and completed only after the corrected 36-claim ledger passed again.

### 2:25–3:05 — Evidence, not confidence

Visual: finished presentation, claim ledger, automated checks, and compact
checklist command.

```bash
python3 -c "import glob,json; s=json.load(open(sorted(glob.glob('runs/*/state.json'))[-1])); [print(i['id'], i['state'], 'owner='+str(i['owner']), 'verified_by='+str(i['verified_by']), i['evidence']) for i in s['checklist']]"
```

> Completion means every checklist item names a different verifier and carries
> checkable evidence. If the agents stall, disagree repeatedly, exceed the turn
> budget, or hit an email ceiling, Rally stops and reports why.

### 3:05–3:35 — Evaluation and observability

Visual: the sanitized eval summary, then a Cloud Trace waterfall or structured
log query.

> We test the coordinator with live Vertex calls. A normal request, an executive
> outcome, and an attempt to bypass review all pass exact tool trajectory and
> response-quality gates at 1.00. Cloud Trace links intake to Gemini execution,
> while metadata-only logging deliberately excludes prompts and responses.

### 3:35–4:00 — Close

Visual: polished final report in the same email thread.

> Rally turns the models a company already trusts into one accountable AI team:
> one familiar identity, the right models for the work, and a completion claim
> no model is allowed to make alone.

End on the lines: **Your AIs, finally on the same team. One request. Three model
families. Zero self-approval.**

## Editing rules

- Use clean jump cuts and a small elapsed-time label; never imply inference was
  instantaneous.
- Publish the complete unedited golden-run capture beside the four-minute cut.
- Keep the complete email thread visible long enough to prove distinct sender
  addresses.
- Show one failure-control artifact, not every guardrail.
- Use captions; keep background music below narration.
- Never display a bearer token, keychain output, Secret Manager payload, raw
  ingest URL, or provider thought signature.
