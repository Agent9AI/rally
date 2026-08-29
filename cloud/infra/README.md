# Rally Google Cloud infrastructure

Terraform owns the production Cloud Run service, its least-privilege service
account, Firestore, Artifact Registry, Secret Manager token, API enablement, and
the sole Cloud Run invoker grant.

The service is not public. The local bridge impersonates a dedicated
`rally-local-invoker` service account to mint a short-lived, service-audience ID
token. Only `imterryim@gmail.com` may impersonate it, and the caller must also
present the independent `X-Rally-Service-Token` application credential. Prompt
and response bodies are excluded from telemetry.

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

Never commit Terraform state, a service token, an identity token, or an eval
result containing model thoughts.
