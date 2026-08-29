# Google Cloud execution path

Google Cloud is Rally's durable governance plane. The implementation uses
Gemini 3.7 on Vertex AI through Google ADK, Cloud Run, Firestore, Secret Manager,
Cloud Logging, Cloud Trace, Artifact Registry, and Cloud Build.

See [ARCHITECTURE.md](ARCHITECTURE.md) for trust boundaries and
[EVALUATION.md](EVALUATION.md) for the live ADK scorecard.

## Local service check

```bash
cd ~/rally
RALLY_ALLOW_INSECURE_DEV=1 RALLY_STATE_BACKEND=memory \
  uv run --project cloud uvicorn service:app --app-dir cloud --port 8080
```

In another terminal:

```bash
curl -s http://127.0.0.1:8080/health | python3 -m json.tool
curl -s -X POST http://127.0.0.1:8080/v1/commissions \
  -H 'content-type: application/json' \
  -H 'idempotency-key: local-demo-1' \
  -d '{"task":"Add rate limiting","run_id":"r-local-demo"}' \
  | python3 -m json.tool
```

Development bypass is accepted only when `RALLY_ALLOW_INSECURE_DEV=1` is
explicitly set. Production Terraform never sets it.

## Production configuration

Infrastructure lives in `cloud/infra` and validates with:

```bash
make infra-check
```

Terraform creates:

- an Artifact Registry Docker repository
- a least-privilege Cloud Run service account
- native Firestore with deletion protection
- a generated application token in Secret Manager
- an IAM-protected Cloud Run service with scale-to-zero
- a dedicated least-privilege Cloud Run invoker identity
- permission for `imterryim@gmail.com` to mint only short-lived tokens as that
  invoker identity

### Approved two-phase deployment

The registry must exist before an image can be pushed, and the image must exist
before Cloud Run can start. Rally encodes that dependency as an explicit safe
gate instead of relying on a failing first apply.

Phase 1 bootstraps the substrate. `deploy_service` defaults to false, so no
Cloud Run revision is created:

```bash
terraform -chdir=cloud/infra apply \
  -var='image_uri=bootstrap-not-used'
```

Phase 2 builds and pushes a commit-addressed image:

```bash
gcloud builds submit cloud \
  --config=cloud/cloudbuild.yaml \
  --project=rally-agent9-2026 \
  --substitutions=_IMAGE=us-east1-docker.pkg.dev/rally-agent9-2026/rally/rally-google-coordinator:<commit-sha>
```

Phase 3 creates the private service and sole invoker grant from that immutable
image:

```bash
terraform -chdir=cloud/infra apply \
  -var='deploy_service=true' \
  -var='image_uri=us-east1-docker.pkg.dev/rally-agent9-2026/rally/rally-google-coordinator:<commit-sha>'
```

Review each plan and approve it interactively. Never add `-auto-approve` to the
operator path.

The deployed service also checks the Secret Manager token. The local runner
impersonates the dedicated invoker to mint a token whose audience is the exact
Cloud Run URL and whose identity claim is available to IAM, then reads the
application token from macOS Keychain. The boundary therefore requires two
independent credentials. `/health` is the external operator check; `/healthz`
is reserved for Cloud Run's internal startup probe.

After the approved service apply, mirror the token locally without printing it:

```bash
security add-generic-password -U -s rally-cloud-token -a rally \
  -w "$(gcloud secrets versions access latest \
    --secret=rally-cloud-service-token \
    --project=rally-agent9-2026)"
```

Then set `google_cloud.enabled` to `true`, put the Terraform `service_url` in
`google_cloud.url`, and run:

```bash
./bin/rally --config config/rally.demo.json --check --smoke
```

## Cost posture

Cloud Run uses zero minimum instances, at most one instance, one vCPU, and
512 MiB memory. Firestore stores one small record per commission. Eval cases
use Gemini Flash and remain deliberately small. The existing $8 billing alert
is monitoring-only; it is not a hard cap.

## Deployment gate

The source, tests, live ADK evaluations, Docker image definition, and Terraform
must all be green before deployment. Deployment creates billable external
resources and therefore requires explicit operator approval at that point.
