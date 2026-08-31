# Product onboarding strategy

The product goal is not “fewer API-key steps.” It is **no customer exposure to
infrastructure credentials on the default path**.

## Path 1: managed onboarding (default)

An administrator names the Rally team identity, supplies commissioner addresses,
chooses the first outcome, and selects the systems and authority each user needs.
Agent9 owns the Cloudflare account, Resend mail plane, Google Cloud control
plane, model configuration, secret rotation, budgets, and upgrades. Everyone
else receives one Rally address and simply gives the team work.

This is the only credible no-key experience today. It removes three cloud
accounts from the user's critical path instead of hiding their setup behind
friendly-looking buttons.

## Path 2: self-hosted (advanced)

A future guided installer should orchestrate provider-native browser consent:

1. `gcloud` opens Google sign-in and sets the target project.
2. Wrangler opens Cloudflare's OAuth consent screen and stores its own token.
3. Terraform provisions Cloud Run, Firestore, IAM, Secret Manager, and Trace.
4. Rally creates and verifies the ingress Worker, D1 schema, and routes.
5. Each operator signs into their own Gemini, Claude, and/or OpenAI Codex
   entitlement. Rally never pools a subscription seat.
6. Each business-system OAuth connection is stored in that commissioner's
   isolated profile and Keychain namespace.
7. A mail provider is connected or the customer uses an Agent9-managed Rally
   address.
8. A final readiness call proves send, receive, Gemini, Claude, Codex, Firestore,
   duplicate suppression, and human reply routing.

The installer may report credential status, but must never print tokens, write
them to the repository, or ask the user to disable security warnings.

## Why every Connect button is real

A website cannot safely reuse Wrangler's local OAuth identity, and a provider
dashboard link is not a completed integration. The hosted admin now labels a
button “Connect” only when all of these exist:

- a registered application and least-privilege consent scopes
- a state-bound callback with PKCE where supported
- encrypted token storage and rotation
- per-user tenant isolation and revocation
- bounded discovery against a committed safe allowlist
- one fixed, harmless live read and a content-free proof
- a complete rollback path

Cloudflare, n8n Cloud, Stripe, Atlassian, and HyperAgent use provider-native
OAuth in the current tab and return to the exact admin card. GitHub uses a
guided fine-grained-token path. A provider whose Rally-owned registration is
not complete remains disabled and labelled “Not available yet.” The card does
not send a nontechnical administrator into a provider console and imply that
finishing Rally's application setup is customer onboarding.

Google Workspace needs a separate confidential OAuth client dedicated to the
connector. It is not the Google Identity Services client used to sign into
Rally. The customer sees one Workspace card, while Rally checks the eight
official Gmail, Drive, Docs, Sheets, Slides, Calendar, Chat, and People MCP
services independently behind it. If the confidential client is absent, or any
service fails its allowlist check, the aggregate card remains disabled.

## Hosted control-plane slice

Rally now has a separate Google-authenticated administration surface for the
part that can be made self-service safely: account identity and encrypted
credential custody. Sign-in uses Google Identity Services; a unique AES-GCM key
protects each connection; Google Cloud KMS wraps that key; and Firestore stores
only ciphertext and non-secret metadata. The browser retains no session or
credential in persistent storage; the admin uses page memory for its short-lived
session and any pasted credential.

The vault moves through `stored_unverified`, `verifying`, and `ready`. OAuth
state is one-use, hashed at rest, expires after ten minutes, and its encrypted
flow record is deleted atomically at callback. In production, the Cloudflare
Worker handles the registered callback server-side and returns to the same card.
A per-flow `HttpOnly`, `Secure`, `SameSite=Lax` cookie proves that the return
came back to the browser that started consent; it contains no identity or
provider credential and is cleared at callback. The admin page receives neither
the authorization code nor the provider token. There is no static callback
fallback: if the production Worker is unavailable, authorization fails closed.
Rally then checks authenticated MCP discovery against a
committed safe allowlist and calls one predetermined read-only canary. Only a
successful call may create the content-free proof: canary name, schema digest,
timestamp, and approved-tool count, never the returned business data. A failed
check becomes `needs_attention`; a stored credential or successful tool list
alone enables nothing.

This hosted activation plane proves custody, provider identity, allowlist fit,
and one harmless live read. A signed-in administrator may use its direct invoke
route only for Certified, preset-allowlisted reads; every call rechecks tenant,
policy, and arguments and writes a content-free receipt. That is not autonomous
model authority. Agent runs remain separate and require a run-scoped, immutable
authority snapshot for that user.

Disconnect also fails closed. Rally disables the connector first. For OAuth
connections whose metadata publishes a revocation endpoint, Rally revokes the
grant before deleting its encrypted copy; failure leaves the copy sealed for
retry. Without automatic revocation, Rally deletes its copy and reports that the
administrator must revoke the grant, key, or token in provider settings. Signing
out separately requests deletion of the current server-side session hash before
clearing page memory; expiry remains the backstop if that request fails. The
certification contract describes what qualifies as Ready, not which public
provider accounts have already passed live certification.

## Company activation checklist

- Rally team name, address, and administrator selected
- Commissioner identities and escalation owner approved
- Each connected system, resource allowlist, and OAuth scope approved
- Read, draft, execute, verify-first, and human-approval action classes set
- Repository and writable scope selected
- Gemini, Claude, and OpenAI Codex entitlements verified per user
- First task chosen with objective acceptance criteria
- Turn, send, timeout, and spend ceilings accepted
- Second Wind recovery toggled on or off, with its handoff ceiling accepted
- Data retention and telemetry mode selected
- One dry run and one live run reviewed by the customer
- Human `STOP` and steering behavior rehearsed

Activation is complete only when a real email commission reaches independent
model families, every completed item has another verifier, and the commissioner
receives the final report in the same thread.
