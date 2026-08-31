# Rally Google Cloud infrastructure

Terraform owns two deliberately separate Cloud Run services, their
least-privilege service accounts, Firestore, Artifact Registry, Secret Manager,
Cloud KMS, API enablement, and narrowly scoped invoker grants.

The coordinator is not public. The local bridge impersonates a dedicated
`rally-local-invoker` service account to mint a short-lived, service-audience ID
token. Only `imterryim@gmail.com` may impersonate it, and the caller must also
present the independent `X-Rally-Service-Token` application credential. Prompt
and response bodies are excluded from telemetry.

The optional `rally-control-plane` service is public only at the network edge.
Every customer route verifies either a Google Identity Services ID token or a
hashed, short-lived Rally browser session, derives tenant ownership from
Google's immutable `sub` claim, and never receives permission to invoke the
private coordinator. Redirect sign-in uses an exact same-origin callback,
double-submit CSRF validation, a two-minute one-use exchange code, and a
30-minute session; Firestore stores hashes rather than the raw values and TTL
cleans expired records. Connector credentials are encrypted with a new
AES-256-GCM data key per connection; Cloud KMS wraps each data key, while
Firestore stores only ciphertext and metadata.

Deployment is deliberately gated and two-phase so Cloud Run never references an
image before its Terraform-managed registry exists. After tests and ADK
evaluations pass:

1. Apply the default bootstrap plan with a non-used placeholder `image_uri`.
   `deploy_service` defaults to false, so this creates the registry, APIs,
   identity, Firestore, IAM, and secret—but not Cloud Run.
2. Build and push a commit-addressed candidate to the new repository, then
   resolve its registry digest.
3. Apply the reviewed production plan with both Cloud Run services enabled and
   both image URIs pinned by digest.
4. Run the sensitive `local_token_install_command` output locally.
5. Put Terraform's `service_url` into Rally's `google_cloud.url`, enable the
   integration, and run `./bin/rally --check --smoke`.

## Customer control plane activation

Google requires Web OAuth client registration in Cloud Console. Create a Web
application client named `Rally Web` and authorize the JavaScript origin
`https://rally.agent9.dev`. Also authorize the exact redirect URI
`https://rally.agent9.dev/admin/google/callback` for privacy-browser fallback.

The Google Workspace connector deliberately uses a second confidential OAuth
client rather than the public sign-in client. It is not enabled in this release:
keep `google_workspace_client_id=""`, and the hosted card remains unavailable.
For a future release, register its exact redirect as
`https://rally.agent9.dev/admin/connect/callback`, then add the client secret
directly to Secret Manager without placing it in Terraform state or this repo:

```bash
gcloud secrets versions add rally-google-workspace-oauth-client-secret \
  --project=rally-agent9-2026 --data-file=-
```

Set `google_workspace_client_id` only after that secret version exists and the
connector flow has passed release testing. Rally keeps the Workspace card
unavailable until both values are present in the control plane. Google Sign-In
itself needs only the separate Rally Web public client ID; Rally does not use or
store an OAuth client secret for sign-in.

After the candidate image exists, resolve its digest, then review and apply a
plan that preserves the private coordinator and enables the separate control
plane:

```bash
terraform -chdir=cloud/infra plan -out=/tmp/rally-production.tfplan \
  -var='deploy_service=true' \
  -var='deploy_control_plane=true' \
  -var='image_uri=us-east1-docker.pkg.dev/rally-agent9-2026/rally/rally-google-coordinator@sha256:<proven-coordinator-digest>' \
  -var='control_plane_image_uri=us-east1-docker.pkg.dev/rally-agent9-2026/rally/rally-google-coordinator@sha256:<control-plane-digest>' \
  -var='google_web_client_id=<public-client-id>' \
  -var='google_workspace_client_id=""' \
  -var='control_plane_allowed_origins=["https://rally.agent9.dev"]' \
  -var='control_plane_allowed_user_emails=["imterryim@gmail.com"]'

terraform -chdir=cloud/infra apply /tmp/rally-production.tfplan
```

The separate image variables prevent a control-plane release from silently
replacing the private coordinator revision. If both services intentionally use
the same digest-pinned image, `control_plane_image_uri` may be omitted.

Use an initial email allowlist for the first operator test. Put Terraform's
`control_plane_url` and the same public client ID in `site/admin/config.js`, run
the release gate, and then deploy the static site. Never commit provider keys,
Google ID tokens, Terraform state, or KMS plaintext.

Never commit Terraform state, a service token, an identity token, or an eval
result containing model thoughts.
