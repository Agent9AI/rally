# Rally Google Cloud Product Path

## Overview

Rally is an asynchronous engineering operations agent. A human sends a request
by email; Rally turns it into a bounded checklist, coordinates two model
families, requires independent verification, and returns an executive-ready
evidence report.

The Google Cloud path adds a Google ADK coordinator on Cloud Run. Gemini is the
Google-native intake and coordination model. The existing Rally runner remains
the policy authority for checklist transitions, budgets, identity, and
verification. Resend and the Cloudflare Worker remain the email edge during the
transition.

## Example Use Cases

- Add and test a repository change from an executive email request.
- Review a proposed production change and return evidence, risk, and a decision.
- Resume a long-running run after a worker restart without losing checklist state.
- Discover approved agents, capabilities, authority, and prohibited actions
  through one authenticated fleet catalog.

## Tools Required

- Gemini 3.5 or newer through the Gemini API or Vertex AI.
- Google ADK for the intake/coordinator agent.
- Cloud Run for the HTTP service and asynchronous execution boundary.
- Firestore for durable run state and event history.
- An authenticated agent catalog for cross-department discovery and lifecycle.
- Resend plus the existing Cloudflare Worker for inbound email during the demo.

## Constraints & Safety Rules

- The runner, not an LLM, owns checklist state and completion decisions.
- An item can be marked done only by the agent that did not perform the work.
- Human identity, turn budgets, send ceilings, and idempotency are enforced
  outside the model prompt.
- Agent instructions cannot grant themselves permissions, alter budgets, or
  bypass verification.
- Cloud Run endpoints require an authenticated service-to-service request in
  production; local demo mode may use a development token.
- A failed or expired coordination attempt may be reclaimed once; an older
  attempt cannot overwrite the newer lease holder.

## Success Criteria

- A commission reaches Cloud Run and produces a durable run record.
- Gemini/ADK creates a bounded task envelope without writing code itself.
- Rally’s two-agent loop completes or halts with an explicit reason.
- Every completion claim has independent evidence.
- The demo visibly proves Gemini, ADK, Cloud Run, state persistence, and the
  alternating verification turns.
- The fleet catalog makes agent specialization, authority, lifecycle state, and
  30-day retention policy inspectable without exposing credentials or prompts.
