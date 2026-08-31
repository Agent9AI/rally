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
| Cross-workspace teammate access | Verified workspace identity on every list/create route; browser responses omit workspace ID and creator subject | `cloud/control_plane.py`; `cloud/teammate_store.py`; teammate tests |
| Unverified tenant squats another company's address | Pending customer-domain claims are workspace-scoped; only Rally-owned trial names are globally reserved; activation still requires domain/provider proof | `cloud/teammate_store.py`; teammate tests |
| Setup record mistaken for a live mailbox | Every provider currently produces an explicit activation-required state; no create path can return `ready`; Work links switch only to a genuinely ready teammate | `cloud/control_plane.py`; `site/admin/app.js`; teammate tests |
| Redirect login replay or CSRF | Exact callback route, Google's double-submit CSRF check, atomic one-use code, hashed short-lived session, Firestore TTL | `src/worker/index.js`; `cloud/auth_sessions.py`; control-plane tests |
| Company-email link theft, replay, enumeration, or delivery abuse | Uniform Pub/Sub request path, current allowlist checks, per-email plus high emergency circuit limits, signed email/workspace binding, pending-to-active delivery, ten-minute expiry, no plaintext token at rest, and atomic one-use consumption | `cloud/magic_links.py`; magic-link tests |
| Connector OAuth replay, login CSRF, mix-up, or SSRF | Hashed one-use PKCE state, per-flow same-browser `HttpOnly` binding, production-only Worker callback, provider-pinned HTTPS metadata/token hosts, redirect refusal, encrypted ten-minute flow, atomic consume, and same-card return | `src/worker/index.js`; `cloud/connector_oauth.py`; OAuth tests |
| Connector credential disclosure | Unique AES-256-GCM data key per connection, wrapped by Cloud KMS; ciphertext-only Firestore records | `cloud/credential_vault.py`; KMS tests |
| Stored credential mistaken for working authority | Ready requires live authentication, bounded discovery matched to a committed safe allowlist, and one predetermined harmless read; the proof stores only canary/schema metadata | `cloud/hosted_connectors.py`; `cloud/credential_vault.py`; certification tests |
| Over-broad connector consent | Provider-specific minimum OAuth scopes plus exact live-tool intersection with committed safe presets; unavailable app registrations remain disabled | `cloud/hosted_connectors.py`; `cloud/connector_presets.py` |
| Disconnect leaves provider access live | Execution is disabled first; a published OAuth revocation endpoint is called before local deletion, and failure leaves ciphertext sealed. Without automatic revocation—including manual keys or tokens—Rally deletes its copy and requires provider action | `cloud/connector_oauth.py`; `cloud/control_plane.py`; OAuth tests |
| Hosted vault silently becomes autonomous model authority | Hosted direct invocation is tenant-authenticated, Certified, preset-bound, read-only, and receipted; agent runs additionally require an immutable, user-bound authority snapshot | `cloud/control_plane.py`; `cloud/hosted_connector_execution.py`; `src/connectors.py`; gateway tests |
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
- Teammate reachability and approved-sender fields are persisted setup policy,
  not active ingress authority. The current live pilot still uses the runner's
  configured owner allowlist. Activation must connect those records to signed
  inbound identity checks before a new teammate address can receive work.

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
The company-email path accepts only normalized allowlisted addresses and always
returns the same request response. Approved and unknown requests take the same
Google Pub/Sub publish path; the message contains no usable sign-in token. An
OIDC-authenticated delivery endpoint generates a signed, high-entropy ten-minute
link, binds it to the email and configured workspace, and marks it active only
after Resend accepts delivery. Firestore indexes only the token hash; Resend
sees the destination and one-time message. Durable keyed email and
keyed per-email buckets plus a high emergency circuit limit constrain abuse
without trusting spoofable proxy headers or storing raw rate keys in document
IDs. Both paths then issue the
same Rally session, whose access is rechecked against the current allowlist.
Google identities use the
immutable `sub`; company-email identities use a stable hash of the normalized
address and remain scoped to the configured workspace. The pilot deliberately
does not merge those principals: signing in through a different method can show
a distinct per-operator connector vault even when both principals share the
workspace dashboard. Account linking requires an explicit verified migration,
not an email-equality guess.

The admin keeps the short-lived ID token or 30-minute Rally session and a pasted
credential only in page memory. It does not write those raw values to cookies,
local storage, or session storage. Connector consent uses one separate,
ten-minute `HttpOnly`, `Secure`, `SameSite=Lax` cookie containing only an
opaque per-flow browser binding. Page JavaScript cannot read it, it contains no
identity or provider credential, and the Worker clears it on callback. Firestore
stores only hashes of redirect codes and sessions with verified identity
metadata and expiration timestamps. The API never returns credential material
and replaces FastAPI's default validation detail with a non-reflective error so
an invalid oversized secret cannot be echoed.

The registered production connector callback is intercepted by the Cloudflare
Worker. It derives the binding-cookie name from the returned state, forwards the
opaque binding and only bounded callback fields to the control plane, and clears
the cookie. The control plane compares the binding hash before atomically
consuming the flow. The admin page sees neither the provider access token nor the
authorization code. The static Pages origin is not a callback fallback; an
unavailable Worker makes consent fail closed. Rally returns only a one-time
session-restoration code in a URL fragment, which the admin removes immediately
after reading it.

Workers Logs and automatic tracing are disabled for the callback-bearing Worker,
so Rally does not persist provider callback URLs in those Cloudflare
observability products. Deployments must preserve and verify that boundary. The
browser and Cloudflare edge still necessarily process the callback URL, and this
control is not a universal claim that infrastructure outside Rally never handles
request metadata.

The sign-out control asks the control plane to delete the hashed Rally session,
then clears page memory. If the revocation request cannot complete, the browser
still clears locally and the 30-minute server expiry is the backstop.

The browser sends identity in exactly one dedicated application header:
`X-Rally-ID-Token` for the Google fast path or `X-Rally-Session` for the
full-page fallback. It never uses `Authorization`, which Cloud Run reserves for
its own IAM token processing.

Rally Web sign-in and Google Workspace authorization are deliberately separate
OAuth clients and grants. The web client proves the administrator's identity and
vault ownership only. A distinct confidential Workspace connector client asks
for the read-only business scopes. The public UI exposes one Workspace card,
but certification opens Gmail, Drive, Docs, Sheets, Slides, Calendar, Chat, and
People independently and fails the aggregate card if any service does not match
its committed allowlist. A fixed People profile read is the only live canary;
the vault retains its name and schema digest, not its returned content.

The same fail-closed rule applies to provider availability. A card whose
Rally-owned app registration is incomplete remains disabled; the public flow
does not redirect a nontechnical customer to a provider console to finish
Rally's configuration. A provider callback returns to the originating card,
but the card can show Ready only when a content-free certification record
exists. This is a qualification rule, not evidence that any named production
provider connection has already passed it.

Finally, the hosted vault does not grant autonomous model authority. A signed-in
administrator can invoke a Certified, preset-allowlisted read through the hosted
control plane; each call rechecks tenant ownership, readiness, arguments, and
policy and stores a content-free receipt. Agent runs additionally require a
separate immutable, user-bound authority snapshot.

Disconnect disables execution first. When an OAuth provider publishes a
revocation endpoint, Rally revokes the grant before deleting its encrypted copy;
failure leaves that copy sealed for retry. Without automatic revocation, Rally
deletes its copy and reports that provider action is still required. Manually
supplied keys and tokens must be revoked in provider settings.
