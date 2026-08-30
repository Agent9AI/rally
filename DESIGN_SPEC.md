# Rally Google Cloud Product Path

## Overview

Rally is an asynchronous engineering operations agent. A human sends a request
by email; Rally turns it into a bounded checklist, coordinates three model
families, requires independent verification, and returns an executive-ready
evidence report.

The Google Cloud path adds a Google ADK coordinator on Cloud Run. Gemini is the
Google-native intake and coordination model. The existing Rally runner remains
the policy authority for checklist transitions, budgets, identity, and
verification. Resend and the Cloudflare Worker remain the email edge during the
transition.

Rally also exposes the coordinator as an A2A Protocol v1.0 server. A2A is the
standards boundary for discovering and commissioning Rally from another agent;
it does not replace Rally's verification policy, run ledger, or model adapters.
The same commission function serves the native REST API and both A2A bindings so
the protocol cannot become a less-governed side door.

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
- The official A2A Python SDK for Agent Card discovery plus JSON-RPC and
  HTTP+JSON task/message bindings.
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
- A2A requests require the authentication schemes declared in the Agent Card.
  The public card contains no credentials, prompts, or internal paths.
- An A2A message ID becomes Rally's idempotency key. Reusing it with different
  task content fails closed rather than creating a second run.
- A2A task events and artifacts contain bounded receipts, not raw prompts or
  coordinator output. Firestore persists production tasks; tests use memory.
- Unsupported cancellation and push notifications are declared unsupported and
  return protocol-native errors. Rally never advertises a capability it cannot
  enforce.

## Success Criteria

- A commission reaches Cloud Run and produces a durable run record.
- Gemini/ADK creates a bounded task envelope without writing code itself.
- Rally’s three-family worker rotation completes or halts with an explicit reason.
- Every completion claim has independent evidence.
- The demo visibly proves Gemini, ADK, Cloud Run, state persistence, and the
  alternating verification turns.
- The fleet catalog makes agent specialization, authority, lifecycle state, and
  30-day retention policy inspectable without exposing credentials or prompts.
- `/.well-known/agent-card.json` validates as an A2A v1.0 Agent Card, identifies
  Google Cloud bearer identity plus the Rally service-token requirement, and
  lists only the commission skill that this release actually performs.
- Official A2A SDK clients can discover the card, send, stream, poll, and list a
  task through both JSON-RPC and HTTP+JSON bindings.
- Duplicate A2A messages return the original Rally run; conflicting replays,
  malformed messages, oversized tasks, and unauthenticated requests fail safely.
- The live Cloud Run revision passes an authenticated A2A smoke test before the
  landing page may call the release A2A v1.0 compatible.
