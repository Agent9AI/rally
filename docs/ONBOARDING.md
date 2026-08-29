# Product onboarding strategy

The product goal is not “fewer API-key steps.” It is **no customer exposure to
infrastructure credentials on the default path**.

## Path 1: managed onboarding (default)

An administrator names the Rally team identity, supplies commissioner addresses,
chooses the first outcome, and selects the systems and authority it needs.
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
5. A mail provider is connected or the customer uses an Agent9-managed Rally
   address.
6. A final readiness call proves send, receive, Gemini, Claude, Firestore,
   duplicate suppression, and human reply routing.

The installer may report credential status, but must never print tokens, write
them to the repository, or ask the user to disable security warnings.

## Why there are no fake Connect buttons

A website cannot safely reuse Wrangler's local OAuth identity, and a provider
dashboard link is not a completed integration. Rally will label a button
“Connect” only when all of these exist:

- a registered application and least-privilege consent scopes
- a state-bound callback with PKCE where supported
- encrypted token storage and rotation
- tenant isolation and revocation
- a post-connect capability check
- a complete rollback path

Until then, the public site offers managed onboarding and accurately describes
the self-host flow.

## Company activation checklist

- Rally team name, address, and administrator selected
- Commissioner identities and escalation owner approved
- Each connected system, resource allowlist, and OAuth scope approved
- Read, draft, execute, verify-first, and human-approval action classes set
- Repository and writable scope selected
- Claude and Gemini entitlements verified
- First task chosen with objective acceptance criteria
- Turn, send, timeout, and spend ceilings accepted
- Second Wind recovery toggled on or off, with its handoff ceiling accepted
- Data retention and telemetry mode selected
- One dry run and one live run reviewed by the customer
- Human `STOP` and steering behavior rehearsed

Activation is complete only when a real email commission reaches both model
families, every completed item has another verifier, and the commissioner
receives the final report in the same thread.
