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
Every customer route verifies a Google Identity Services ID token, derives
tenant ownership from Google's immutable `sub` claim, and never receives
permission to invoke the private coordinator. Connector credentials are
encrypted with a new AES-256-GCM data key per connection; Cloud KMS wraps each
data key, while Firestore stores only ciphertext and metadata.

Deployment is deliberately gated and two-phase so Cloud Run never references an
image before its Terraform-managed registry exists. After tests and ADK
evaluations pass:

1. Apply the default bootstrap plan with a non-used placeholder `image_uri`.
   `deploy_service` defaults to false, so this creates the registry, APIs,
   identity, Firestore, IAM, and secret—but not Cloud Run.
2. Build and push an immutable image to the new repository.
3. Apply with `-var deploy_service=true` and the immutable image URI.
4. Run the sensitive `local_token_install_command` output locally.
5. Put Terraform's `service_url` into Rally's `google_cloud.url`, enable the
   integration, and run `./bin/rally --check --smoke`.

## Customer control plane activation

Google requires Web OAuth client registration in Cloud Console. Create a Web
application client named `Rally Web` and authorize the JavaScript origin
`https://rally.agent9.dev`. Only the resulting public client ID is needed;
Rally does not use or store an OAuth client secret for Google Sign-In.

After the immutable image exists, review and apply a plan that preserves the
private coordinator and enables the separate control plane:

```bash
terraform -chdir=cloud/infra apply \
  -var='deploy_service=true' \
  -var='deploy_control_plane=true' \
  -var='image_uri=us-east1-docker.pkg.dev/rally-agent9-2026/rally/rally-google-coordinator:<commit-sha>' \
  -var='google_web_client_id=<public-client-id>' \
  -var='control_plane_allowed_user_emails=["you@example.com"]'
```

Use an initial email allowlist for the first operator test. Put Terraform's
`control_plane_url` and the same public client ID in `site/admin/config.js`, run
the release gate, and then deploy the static site. Never commit provider keys,
Google ID tokens, Terraform state, or KMS plaintext.

Never commit Terraform state, a service token, an identity token, or an eval
result containing model thoughts.
