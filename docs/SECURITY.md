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
| Cross-tenant credential access | Verified Google `sub` ownership, tenant-derived document IDs, and owner-hash checks | `cloud/user_auth.py`; `cloud/credential_vault.py` |
| Redirect login replay or CSRF | Exact callback route, Google's double-submit CSRF check, atomic one-use code, hashed short-lived session, Firestore TTL | `src/worker/index.js`; `cloud/auth_sessions.py`; control-plane tests |
| Connector credential disclosure | Unique AES-256-GCM data key per connection, wrapped by Cloud KMS; ciphertext-only Firestore records | `cloud/credential_vault.py`; KMS tests |
| Rejected credential reflected by API | Redacted `SecretStr` input plus a non-reflective validation handler | `cloud/control_plane.py`; control-plane tests |
| Prompt injection changes policy | ADK is advisory; runner reconciles every transition | `cloud/rally_adk/agent.py`; `src/envelope.py` |
| Agent approves its own work | Owner/verifier invariant enforced in code | checklist tests |
| Same-family rubber stamp | Startup refuses non-distinct model families | `src/agents.py`; tests |
| Runaway turns or email spend | Turn, stagnation, rejection, per-run, hourly, daily ceilings | `src/runner.py`; `src/transport.py` |
| Secret or prompt leakage in telemetry | Metadata-only OTel; no content capture | `cloud/telemetry.py`; Terraform env |
| Credential committed to source control | Common secret-bearing files are ignored; repository secret scanning and push protection are enabled | `.gitignore`; GitHub security settings |
| Agent writes into Rally itself | Isolated git workspace plus containment fingerprint | `src/runner.py` |
| Failed handling deletes work | D1 acknowledgement occurs only after successful or intentionally quarantined handling | `src/runner.py`; reliability tests |
| Token timing side channel | Worker hashes both candidates and uses Web Crypto `timingSafeEqual`; Cloud service uses `hmac.compare_digest` | Worker and Cloud service source |

## Demo-safe proof

Show IAM policy membership, service account roles, a Cloud Trace span, and
structured log fields. Do not reveal the Secret Manager payload, identity
token, application token, Resend key, ingest-token URL, or raw eval histories.

## Credential handling

- Never place provider keys, OAuth tokens, client secrets, refresh tokens,
  service-account credentials, private keys, or customer credentials in source
  files, fixtures, commits, issues, logs, screenshots, or demo evidence.
- Store local operator connector credentials in the macOS Keychain. The hosted
  control plane creates a fresh AES-GCM data-encryption key per user connection,
  asks Google Cloud KMS to wrap that key, and stores only ciphertext, the wrapped
  key, and non-secret status metadata in Firestore. Store deployed application
  credentials in Secret Manager and expose them only to the service identity
  that needs them.
- Commit only empty examples such as `.env.example`. If a secret is ever
  committed, revoke or rotate it immediately; removing it in a later commit is
  not sufficient because Git history preserves it.

## Accepted boundaries

- Agent execution is not an OS sandbox. The isolated workspace and repository
  fingerprint detect escape; a production fleet should add process isolation.
- Email turn messages are an audit mirror; runner dispatch—not email arrival—
  advances the next agent.
- One operator account remains the only private coordinator invoker. The
  separate public control plane accepts verified Google accounts but has no
  permission to invoke the coordinator; an optional email or Workspace-domain
  allowlist can close initial access while role groups are added.

## Customer identity and credential vault

The coordinator and customer control plane are deliberately separate Cloud Run
services. The private coordinator keeps Cloud Run IAM plus its independent
Secret Manager application token. The public control plane is network
reachable because a browser must call it, but every protected customer route
verifies a Google Identity Services ID token or a hashed, short-lived Rally
session. The
Google path verifies audience, issuer, expiry, verified email, and optional
account/domain allowlists. Redirect sign-in additionally verifies Google's
double-submit CSRF token and atomically consumes a two-minute exchange code.
Rally keys tenancy only by the Google `sub` claim; email is display data and may
change.

The browser keeps the short-lived ID token or 30-minute Rally session and a
submitted credential only in memory. It never writes those raw values to
cookies, local storage, session storage, HTML, logs, repository files, or
Firestore. Firestore stores only hashes of redirect codes and sessions with
verified identity metadata and expiration timestamps. The API never returns
credential material and replaces FastAPI's default validation detail with a
non-reflective error so an invalid oversized secret cannot be echoed.

The browser sends identity in exactly one dedicated application header:
`X-Rally-ID-Token` for the Google fast path or `X-Rally-Session` for the
full-page fallback. It never uses `Authorization`, which Cloud Run reserves for
its own IAM token processing.
