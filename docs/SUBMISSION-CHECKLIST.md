# Submission operator checklist

This is the last-mile path from the release candidate to a defensible Devpost
entry. Items are ordered so a failure cannot invalidate later evidence.

## 1. Freeze deterministic proof

- [ ] `make release-check` passes from a clean terminal.
- [ ] `make cloud-eval` passes all required cases without changing thresholds.
- [ ] The live result still reads 3/3, trajectory 1.00, quality 1.00.
- [ ] `git diff --check` passes.
- [ ] No token, private key, webhook URL, or prompt content appears in tracked files.
- [ ] The repository and site say 72 tests everywhere.
- [ ] The standard and filmed model pins are documented accurately.

## 2. Approval gate: Google Cloud deployment

Deployment changes an external account and can consume credits. Do not cross
this gate without the operator's explicit approval.

- [ ] Operator states: **I approve deploying Rally to Google Cloud project `rally-agent9-2026`.**
- [ ] Confirm active account and project.
- [ ] Confirm the expected low-cost plan and budget alert.
- [ ] Read and follow the Google ADK deployment workflow before executing it.

## 3. Provision and deploy

- [ ] Phase 1 Terraform bootstrap provisions APIs, Artifact Registry, Firestore,
      service account, IAM, and Secret Manager while `deploy_service=false`.
- [ ] Confirm bootstrap created the application-token version without printing it.
- [ ] Build and push the commit-addressed image in `us-east1`.
- [ ] Phase 2 Terraform uses `deploy_service=true` and that exact immutable image.
- [ ] Confirm Cloud Run has at most one instance and is not publicly invokable.
- [ ] Install the service token in macOS Keychain using the documented command.
- [ ] Configure the local bridge URL and audience without committing credentials.

## 4. Prove the Google path

- [ ] Authenticated health call returns the expected service/model identity.
- [ ] Unauthenticated commission and catalog calls are rejected.
- [ ] Authenticated `GET /v1/agents` returns the versioned fleet catalog.
- [ ] A new commission creates one Firestore record.
- [ ] Exact replay returns the same run and does not invoke Gemini again.
- [ ] A conflicting replay with the same key returns HTTP 409.
- [ ] One controlled failed attempt resumes with an incremented attempt number.
- [ ] A stale attempt cannot overwrite the reclaimed attempt.
- [ ] Cloud Trace links the intake and Gemini spans.
- [ ] Logs contain metadata but no commission or model response content.

Save sanitized screenshots for each judge-visible claim.

## 5. Golden end-to-end run

- [ ] Use the exact commission in `docs/DEMO-SCRIPT.md`.
- [ ] Start a complete unedited screen recording before pressing Send.
- [ ] Show email → durable intake → Gemini/ADK handoff → repository work.
- [ ] Keep one owner edit/test → `awaiting-verification` → other-family verdict
      sequence continuous and readable.
- [ ] Verify every completed item names a different verifier and evidence.
- [ ] Verify the final report includes outcome, tests, residual risk, and run ID.
- [ ] Preserve the entire email thread and run state as sanitized evidence.

## 6. Produce the entry video

- [ ] Follow `docs/DEMO-SCRIPT.md`; final entry is four minutes or shorter.
- [ ] Add captions and readable cursor/highlight treatment.
- [ ] Label every elapsed-time cut; do not imply instantaneous inference.
- [ ] Never show secrets, raw webhook URLs, thought signatures, or account menus.
- [ ] End on: **One request. Two model families. Zero self-approval.**
- [ ] Upload the full unedited run as supporting proof.
- [ ] Check playback, captions, privacy, and link access in a signed-out browser.

## 7. Devpost entry

- [ ] Category is **Fortified Enterprise Fleet**.
- [ ] Use the copy in `docs/HACKATHON.md` and the proof order in
      `docs/JUDGE-PACKET.md`.
- [ ] Link the public GitHub repository, product site, entry video, and unedited run.
- [ ] Include the presentation-ready architecture diagram.
- [ ] Explain why each model handles its workload.
- [ ] Explicitly name Gemini 3.7 via Vertex AI, Google ADK, and Google Cloud services.
- [ ] Include the new-project disclosure.
- [ ] Preview every field and link in a signed-out browser.
- [ ] Submit before **August 31, 2026 at 5:00 PM PDT**; save confirmation evidence.

## 8. Optional bonus content

- [ ] Publish the long-form draft in `docs/PUBLIC-LAUNCH-DRAFT.md` only after
      replacing proof placeholders with live links.
- [ ] Include the required hackathon acknowledgement.
- [ ] Publish the social version with the final video/product link and relevant tag.
- [ ] Archive the public URLs in the Devpost submission.
