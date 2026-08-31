# Submission operator checklist

This is the last-mile path from the release candidate to a defensible Devpost
entry. Items are ordered so a failure cannot invalidate later evidence.

## 1. Freeze deterministic proof

- [x] `make release-check` passes from a clean terminal.
- [x] `make cloud-eval` passes all required cases without changing thresholds.
- [x] The live result reads 6/6, trajectory 1.00, quality 1.00.
- [x] `git diff --check` passes.
- [x] No token, private key, webhook URL, or prompt content appears in tracked files.
- [x] The repository and site say 263 tests everywhere.
- [x] The standard and filmed model pins are documented accurately.

## 2. Approval gate: Google Cloud deployment

Deployment changes an external account and can consume credits. Do not cross
this gate without the operator's explicit approval.

- [x] Operator states: **I approve deploying Rally to Google Cloud project `rally-agent9-2026`.**
- [x] Confirm active account and project.
- [x] Confirm the expected low-cost plan and budget alert.
- [x] Read and follow the Google ADK deployment workflow before executing it.

## 3. Provision and deploy

- [x] Phase 1 Terraform bootstrap provisions APIs, Artifact Registry, Firestore,
      service account, IAM, and Secret Manager while `deploy_service=false`.
- [x] Confirm bootstrap created the application-token version without printing it.
- [x] Build and push the commit-addressed image in `us-east1`.
- [x] Production Terraform uses `deploy_service=true`,
      `deploy_control_plane=true`, the `imterryim@gmail.com` account allowlist,
      and `google_workspace_client_id=""` for this release.
- [x] Both Cloud Run images are pinned by digest, not a mutable tag.
- [x] Confirm the private coordinator has at most one instance. Confirm the
      public control plane has at most two instances and all customer routes
      still require verified Rally authentication.
- [x] Install the service token in macOS Keychain using the documented command.
- [x] Configure the local bridge URL and audience without committing credentials.

## 4. Prove the Google path

- [x] Authenticated health call returns the expected service/model identity.
- [x] Unauthenticated commission and catalog calls are rejected.
- [x] Authenticated `GET /v1/agents` returns the versioned fleet catalog.
- [x] A new commission creates one Firestore record.
- [x] Exact replay returns the same run and does not invoke Gemini again.
- [x] A conflicting replay with the same key returns HTTP 409.
- [ ] One controlled failed attempt resumes with an incremented attempt number.
- [ ] A stale attempt cannot overwrite the reclaimed attempt.
- [x] Cloud Trace links the intake and Gemini spans.
- [x] Logs contain metadata but no commission or model response content.

Save sanitized screenshots for each judge-visible claim.

## 5. Golden end-to-end run

- [x] Use the exact commission in `docs/DEMO-SCRIPT.md`.
- [ ] Start a complete unedited screen recording before pressing Send.
- [ ] Show email → durable intake → Gemini/ADK handoff → repository work.
- [ ] Keep one owner edit/test → `awaiting-verification` → other-family verdict
      sequence continuous and readable.
- [x] Verify every completed item names a different verifier and evidence.
- [x] Verify the final report includes outcome, tests, residual risk, and the public console header carries the run ID.
- [ ] Preserve the entire email thread and run state as sanitized evidence.

## 6. Produce the entry video

- [ ] Follow `docs/DEMO-SCRIPT.md`; final entry is four minutes or shorter.
- [ ] Upload the public YouTube/Vimeo cut early; processing can take hours and
      must finish before the submission deadline.
- [ ] Add captions and readable cursor/highlight treatment.
- [ ] Label every elapsed-time cut; do not imply instantaneous inference.
- [ ] Never show secrets, raw webhook URLs, thought signatures, or account menus.
- [ ] End on: **One request. Three model families. Zero self-approval.**
- [ ] Upload the full unedited run as supporting proof.
- [ ] Check playback, captions, privacy, and link access in a signed-out browser.

## 7. Devpost entry

- [ ] Category is **Fortified Enterprise Fleet**.
- [ ] Every contributor is listed on the Devpost project and one eligible person
      is named as the Representative.
- [ ] Every teammate has accepted their Devpost invitation.
- [x] Repository is public under Apache-2.0; private-repository judge grants do
      not apply.
- [ ] Use the copy in `docs/HACKATHON.md` and the proof order in
      `docs/JUDGE-PACKET.md`.
- [ ] Link the reviewable GitHub repository, product site, entry video, and
      unedited run.
- [ ] Upload the presentation-ready architecture diagram.
- [ ] Enter the hosted Rally project URL; if any judge-visible experience is
      gated, include working login credentials in the testing instructions.
- [ ] Explain why each model handles its workload.
- [ ] Explicitly name Gemini 3.7 via Vertex AI, Google ADK, and Google Cloud services.
- [ ] Include the new-project disclosure.
- [ ] Preview every field and link in a signed-out browser.
- [ ] Submit before **August 31, 2026 at 5:00 PM PDT**; save confirmation evidence.
- [ ] Freeze the submitted repository, video, and site until winners are
      announced; use a separate fork for any post-deadline development.

## 8. Optional bonus content

- [ ] Publish the long-form draft in `docs/PUBLIC-LAUNCH-DRAFT.md` only after
      replacing proof placeholders with live links.
- [ ] Include the required hackathon acknowledgement.
- [ ] Publish the social version with the final video/product link and relevant tag.
- [ ] Archive the public URLs in the Devpost submission.

The auditable requirement matrix and remaining human confirmations live in
`docs/FAQ-COMPLIANCE.md`.
