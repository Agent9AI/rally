# Rally's A2A v1.0 boundary

Rally exposes its Google ADK coordinator as an
[A2A Protocol v1.0](https://a2a-protocol.org/latest/) server. This is the open
door through which another agent can discover and commission Rally. A2A carries
the message, task state, and receipt; Rally still owns authority, budgets,
durability, recovery, evidence, and the rule that no model approves its own
work.

This implementation uses the official `a2a-sdk` Python package, pinned in
`cloud/uv.lock`.

## Discovery and bindings

The public Agent Card is available at:

```text
https://agent9-rally.pages.dev/.well-known/agent-card.json
```

The same card is served by the authenticated Cloud Run service. It advertises
two A2A v1.0 interfaces, in preference order:

| Binding | Endpoint |
|---|---|
| JSON-RPC 2.0 | `POST /` (`POST /a2a` remains an alias) |
| HTTP+JSON | `/a2a/rest/message:send`, `/message:stream`, `/tasks`, and `/tasks/{id}` |

Streaming uses Server-Sent Events. Polling and task listing are implemented.
Push notifications, extended cards, and cancellation are deliberately not
advertised in this release.

## Authentication

Production requests require both schemes in the Agent Card's single security
requirement:

1. A short-lived Google Cloud identity token in `Authorization: Bearer ...`,
   with the exact Cloud Run URL as audience. Cloud Run IAM validates it before
   the application runs.
2. The Rally tenant credential in `X-Rally-Service-Token`. The FastAPI boundary
   validates it with constant-time comparison.

The public Agent Card contains descriptions and header names only. It contains
no token, prompt, internal path, or customer data.

## State translation

```text
A2A Message
    ↓ messageId → Rally idempotency key
A2A Task: submitted → working
    ↓
Rally commission → Gemini/ADK handoff → Firestore run record
    ↓
bounded A2A JSON receipt
    ↓
A2A Task: completed or failed
```

The receipt exposes only the Rally run ID, accepted status, duplicate flag,
poll URL, and `owner != verified_by` invariant. It does not echo the objective
or Gemini's coordinator output. Replaying a message ID with the same objective
returns the original Rally run; reusing it for a different objective fails
closed. A2A task protobufs are durable in the `rally_a2a_tasks` Firestore
collection and tenant-scoped by the SDK's owner resolver.

An A2A task is `completed` when the commission has been accepted into Rally's
durable governed ledger. That status does not falsely claim the downstream
repository work is finished; clients poll the returned Rally run URL for that
separate lifecycle.

## Verification

Run the deterministic protocol suite:

```bash
make cloud-test
```

The tests use official SDK clients against the real ASGI app for JSON-RPC and
HTTP+JSON. They cover Agent Card fields and security, authentication rejection,
streamed states, artifacts, task polling and listing, idempotent replay,
conflicting replay, empty input, and the 12,000-character boundary.

Rally was also exercised with the official A2A Technology Compatibility Kit at
commit `5996b79f9cefa6fc390980e383e358a66fb9e49e`. The mandatory run against the
two bindings Rally declares completed with 141 passing, 94 capability/transport
skips, and zero failures. The TCK requires prescribed fixture responses, so they
are isolated behind `RALLY_A2A_TCK_MODE=1`; a release test proves that flag is
absent from the Docker and Terraform production configuration.

`A2A v1.0 compatible` means those implemented protocol surfaces interoperate
with the official SDK. It does not mean Google, the Linux Foundation, the
Agentic AI Foundation, or the A2A project certifies or endorses Rally.
