# Devpost FAQ compliance record

Audited against the official All Things Agentic Hackathon FAQ and its Final Call
for Submissions update on August 29, 2026. This file deliberately separates
facts the repository can prove from submission actions and personal eligibility
facts that require the entrant.

## Current verdict

**The technical entry is compliant; the Devpost package is not submission-complete
yet.** The project-age, single-track, Gemini, Google agent-framework, and deployed
Google Cloud requirements are satisfied. The remaining blockers are the public
four-minute video and entrant-controlled Devpost fields, uploads, confirmations,
and final submission.

## Requirements the repository proves

| FAQ requirement | State | Evidence |
|---|---:|---|
| Project created during the submission period | PASS | First commit is August 28, 2026; `docs/HACKATHON.md` includes the new-project and prior-work disclosure. |
| Enter one category | PASS | All submission materials consistently select **Fortified Enterprise Fleet**. |
| Gemini 3.5 or newer through Gemini API or Vertex AI | PASS | Gemini 3.7 Flash is the ADK coordinator through Vertex AI; the six-case live eval passes at 1.00 trajectory and 1.00 quality. |
| At least one Google agent framework | PASS | The coordinator is implemented with Google ADK and tested under `cloud/`. |
| At least one deployed Google Cloud infrastructure service | PASS | Private Cloud Run revision `rally-google-coordinator-00006-v7q` runs the ADK coordinator in project `rally-agent9-2026`; Firestore, IAM, Secret Manager, Artifact Registry, Cloud Logging, and Cloud Trace are live supporting services. |
| Reproducible setup instructions | PASS | `README.md` and `docs/RUNBOOK.md` provide local, cloud, test, and operational instructions. |
| Reviewable repository | PASS | `Agent9AI/rally` is public and carries the Apache License 2.0. The FAQ's private-repository judging-account exception no longer applies. |
| Real autonomous agent work, not a generic chatbot | PASS | Durable intake, bounded multi-turn execution, sourced artifact creation, automated checks, cross-family verification, replay controls, evidence receipts, and completion invariants are implemented. |
| Judge-visible live agent proof | PASS | Public run `r-20260830-447f2f` shows primary-source research, a self-contained executive presentation, a 36-claim ledger, independent rejection of a wrong date and unsupported claim, repair, 6/6 verification, and zero self-approvals. Gemini, Claude, and OpenAI Codex also pass the shipped live provider preflight. |
| Disclose pre-existing work | PASS | The disclosure says Rally began in the submission period and identifies standard third-party tools and services. |

## Mandatory blockers before submission

| Requirement | Current state | Exact closeout action |
|---|---:|---|
| Strict Google Cloud proof in the demo video | BLOCKED | Record the real `.run.app` service, Cloud Console, Firestore record, logs, and content-free trace alongside the public golden run. Do not rely on diagrams or local mocks. |
| Public demo video, four minutes maximum | BLOCKED | Upload the narrated English/captioned cut publicly to YouTube or Vimeo and verify it while signed out. Only the first four minutes are judged. |
| Architecture diagram in the submission | BLOCKED | Upload `docs/assets/rally-architecture.svg`; having it only in the repository does not close the final-call check. |
| Hosted project URL and testing access | BLOCKED | Enter the public Rally URL in Devpost. If the submitted experience is gated, provide working login credentials in the testing instructions. |
| Complete Devpost submission before the deadline | BLOCKED | Submit by August 31, 2026 at 5:00 PM PDT and archive the confirmation. |

## Entrant confirmations the code cannot prove

- [ ] Every contributor is added to the Devpost project and has accepted the
      invitation.
- [ ] One contributor is named as the Representative.
- [ ] Every contributor meets the age, residence, affiliation, and household
      eligibility rules.
- [ ] If claiming Startup Excellence, the entrant represents an incorporated
      organization and supplies a corporate email address.
- [ ] Any non-standard pre-existing code or work is disclosed.

## Recommended and bonus items

These affect competitiveness, not baseline eligibility.

| Item | State | Note |
|---|---:|---|
| Gemini Enterprise Agent Platform | NOT CLAIMED | Recommended for Fortified Enterprise Fleet and potentially worth bonus points, but not mandatory. Rally implements analogous controls with ADK, Cloud Run, Firestore, IAM, Secret Manager, and Trace and must describe that boundary honestly. |
| Public build content | DRAFTED | `docs/PUBLIC-LAUNCH-DRAFT.md` needs final live proof links and the required hackathon acknowledgement before publication. |
| Social post | DRAFTED | Publish with the final project/video link and the official rules' hashtag form. |
| Additional Google AI model such as Gemma, Veo, or Lyria | NOT CLAIMED | Optional; do not add a decorative model call solely to claim a bonus. |

## Submission freeze

After the deadline, do not edit the submitted repository, video, site, or app
until winners are announced. If development continues, work in a separate fork.

Sources:

- <https://allthingsagentichackathon.devpost.com/details/faqs>
- <https://allthingsagentichackathon.devpost.com/updates/45670-final-call-for-submissions>
