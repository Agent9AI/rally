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
- a post-connect capability check
- a complete rollback path

Cloudflare, n8n Cloud, Stripe, Atlassian, and HyperAgent use provider-native
OAuth in the current tab and return to the exact admin card. GitHub uses a
guided fine-grained-token path. Google Workspace, Slack, and Salesforce remain
labelled “App setup needed” until Rally's provider registrations are complete;
their setup links open separately and are never presented as connections.

## Hosted control-plane slice

Rally now has a separate Google-authenticated administration surface for the
part that can be made self-service safely: account identity and encrypted
credential custody. Sign-in uses Google Identity Services; a unique AES-GCM key
protects each connection; Google Cloud KMS wraps that key; and Firestore stores
only ciphertext and non-secret metadata. The browser retains no session or
credential in persistent storage.

The vault moves through `stored_unverified`, `verifying`, and `ready`. OAuth
state is one-use, hashed at rest, expires after ten minutes, and its encrypted
flow record is deleted atomically at callback. Rally stores a returned token
before immediately testing authenticated MCP discovery and intersecting the
live tool names with a committed safe preset. A failed check becomes
`needs_attention`; no tool is enabled merely because a secret was accepted.

This hosted activation plane proves custody, provider identity, and the safe
tool boundary. The existing runner gateway remains a separate execution plane:
a ready hosted connection is not delegated to an agent run until Rally issues a
run-scoped, immutable authority snapshot for that user. That last bridge must
remain explicit rather than letting a browser session become model authority.

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
