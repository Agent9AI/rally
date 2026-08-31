# Public launch drafts

These drafts are intentionally not published by automation. Replace bracketed
proof links only after the Cloud and golden-run evidence exists.

## Long-form article

# Rally: the accountable AI team that cannot approve its own work

Most agents combine three powers that should be separate: they decide
what the task means, do the work, and declare themselves finished. That is
convenient, but it is not a reliable chain of custody for engineering work.

We built Rally around a harder rule: **the model that owns a checklist item can
never verify it.**

A user emails one outcome to Rally from any device. A Gemini 3.7 agent built
with Google ADK preserves that request and creates an authenticated, durable
handoff on Google Cloud. Gemini, Claude, and OpenAI Codex workers then rotate in
a shared workspace: they research, build, test, challenge evidence, repair
failures, and verify work owned by another model family. Deterministic Python—not a
prompt—decides whether a transition is legal.

The interface matters as much as the orchestration. A product or operations
leader should not need a CLI, an API key, a cloud console, or prompt-engineering
training to commission bounded work. Email is already available on every phone;
it is also a natural audit thread and intervention channel. Rally turns that
ordinary surface into access to a governed agent fleet.

The Google layer is load-bearing. Cloud Run authenticates the ADK coordinator.
Firestore atomically claims the original mail identity so retries cannot create
duplicate work. A versioned catalog exposes agent capabilities, authority,
department scope, prohibitions, and lifecycle state. Failed coordination can be
reclaimed through leases, while attempt fencing prevents a stale worker from
overwriting the recovery. Cloud Trace and structured logs retain execution
metadata with prompt and response capture disabled.

We learned an important lesson from evaluation. Our first live ADK run produced
an excellent-sounding handoff, but Gemini had paraphrased the human's request at
the audit boundary. Exact tool-trajectory evaluation caught the mutation. We
changed the contract to preserve the commission verbatim and reran the same
gate. Rally now passes six live cases—including policy bypass, hostile artifact
instructions, and a production-shaped release workflow—at 1.00 trajectory and
1.00 response quality.

The current release has 263 deterministic automated tests plus that live
scorecard. More importantly, the demo shows the agents doing the work: researching
primary sources, building an executive presentation, running its checks, placing an item into
`awaiting-verification`, and receiving a verdict from another model family.
The full unedited run is published beside the four-minute walkthrough.

- Product: <https://rally.agent9.dev/#demo>
- Source and reproducible setup: <https://github.com/Agent9AI/rally>
- Four-minute walkthrough: [VIDEO LINK]
- Full unedited agent run: [UNEDITED RUN LINK]

Rally was created for purposes of entering the All Things Agentic Hackathon.

## Social post

I built Rally because an AI agent should not grade its own homework.

One email commissions real repository work. Gemini 3.7 + Google ADK governs the
handoff. Gemini, Claude, and OpenAI Codex implement, test, challenge, and verify. Deterministic
policy enforces one rule neither model can waive: owner ≠ verifier.

263 tests. 6/6 live ADK evals at 1.00/1.00. Full unedited agent run included.

One request. Three model families. Zero self-approval.

[VIDEO OR PRODUCT LINK]

Created for the All Things Agentic Hackathon. #AllThingsAgentic

## Short social variant

Rally turns one email into independently verified professional work.

Gemini + Google ADK govern. Gemini + Claude + OpenAI build and review. Code—not model
confidence—enforces zero self-approval.

Demo + full unedited run: [LINK]

Created for the All Things Agentic Hackathon. #AllThingsAgentic
