# Security evidence

Rally assumes that email is hostile input, model output is untrusted, webhook
delivery repeats, and autonomous loops eventually behave unexpectedly.

| Threat | Control | Evidence |
|---|---|---|
| Forged Resend webhook | Svix signature verification over the raw request | `src/worker/index.js` |
| Duplicate mail or retry race | D1 event dedupe, durable message identity, atomic Firestore claim, retry lease, and attempt fencing | Worker schema; `cloud/store.py`; recovery tests |
| Unauthorized commissioner | Sender allowlist outside prompt context | `src/ingress.py`; config owners |
| Public Cloud Run invocation | IAM allows one Google principal | `cloud/infra/main.tf` |
| Stolen or omitted app credential | Secret Manager-backed token; constant-time check; fail closed | `cloud/service.py` |
| Prompt injection changes policy | ADK is advisory; runner reconciles every transition | `cloud/rally_adk/agent.py`; `src/envelope.py` |
| Agent approves its own work | Owner/verifier invariant enforced in code | checklist tests |
| Same-family rubber stamp | Startup refuses non-distinct model families | `src/agents.py`; tests |
| Runaway turns or email spend | Turn, stagnation, rejection, per-run, hourly, daily ceilings | `src/runner.py`; `src/transport.py` |
| Secret or prompt leakage in telemetry | Metadata-only OTel; no content capture | `cloud/telemetry.py`; Terraform env |
| Agent writes into Rally itself | Isolated git workspace plus containment fingerprint | `src/runner.py` |
| Failed handling deletes work | D1 acknowledgement occurs only after successful or intentionally quarantined handling | `src/runner.py`; reliability tests |
| Token timing side channel | Worker hashes both candidates and uses Web Crypto `timingSafeEqual`; Cloud service uses `hmac.compare_digest` | Worker and Cloud service source |

## Demo-safe proof

Show IAM policy membership, service account roles, a Cloud Trace span, and
structured log fields. Do not reveal the Secret Manager payload, identity
token, application token, Resend key, ingest-token URL, or raw eval histories.

## Accepted boundaries

- Agent execution is not an OS sandbox. The isolated workspace and repository
  fingerprint detect escape; a production fleet should add process isolation.
- Email turn messages are an audit mirror; runner dispatch—not email arrival—
  advances the next agent.
- One operator account is the initial Cloud Run invoker. Team identity and role
  groups are a post-hackathon control-plane feature.
