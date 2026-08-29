# Rally Google Cloud infrastructure

Terraform owns the production Cloud Run service, its least-privilege service
account, Firestore, Artifact Registry, Secret Manager token, API enablement, and
the sole Cloud Run invoker grant.

The service is not public. `imterryim@gmail.com` must pass Cloud Run IAM and the
caller must also present the independent `X-Rally-Service-Token` application
credential. Prompt and response bodies are excluded from telemetry.

Deployment is deliberately gated. After tests and ADK evaluations pass:

1. Build and push an immutable image to the Terraform-managed repository.
2. Apply with `-var image_uri=us-east1-docker.pkg.dev/rally-agent9-2026/rally/rally-google-coordinator:<sha>`.
3. Run the sensitive `local_token_install_command` output locally.
4. Put Terraform's `service_url` into Rally's `google_cloud.url`, enable the
   integration, and run `./bin/rally --check --smoke`.

Never commit Terraform state, a service token, an identity token, or an eval
result containing model thoughts.
