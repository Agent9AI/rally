# Judging strategy

This is the honest evidence plan for the **Fortified Enterprise Fleet** rubric.
It separates implemented proof from capture work and does not treat a private
repository, an unpublished artifact, or an optional bonus as complete.

## Rubric map

| Criterion | Weight | Honest Rally case | Proof ready now | Remaining capture action |
|---|---:|---|---|---|
| Innovation and operational utility | 40 | Terry, the owner-operator of a five-person professional-services firm, emails one outcome to a stable AI teammate; three provider-native model families share one checklist; deterministic policy requires an independent verifier and returns evidence in the same thread. | Runner ownership/verification invariants, distinct-family checks, durable email intake, primary final run `r-20260831-48141a`, and separate successful recovery run `r-20260830-447f2f`. | Record the commission and one continuous live state transition. Keep the unlikely hero and finished business outcome—not infrastructure—as the through-line. |
| Technical architecture | 30 | Gemini 3.7 + Google ADK are load-bearing for the authenticated handoff; Firestore provides retry-safe coordination; Cloud Run, IAM, Secret Manager, Trace, Worker/D1, and the local licensed-worker host have explicit trust boundaries. Workspace execution is local, not end-to-end on Cloud Run. | Terraform and security contracts; coordinator `rally-google-coordinator-00007-xpq`; control plane `rally-control-plane-00011-pg6`; both pinned to image `sha256:b1836e2224518a8bed51da7e02ef256aeba1aeeae858808f470a0d02d33fa6e2`; Cloud Build `58a580b6-c6d2-45d6-945b-8fc1bb643cd5`; Worker `757237b2-8c72-4429-913a-f854d014cf2a`; Pages `f2d67f82.agent9-rally.pages.dev`. | Capture sanitized Cloud Run revision, Firestore record, IAM boundary, and content-free trace. Pair them with the architecture diagram; do not use the diagram as deployment proof. |
| Demo and production readiness | 30 | The current suites contain 369 deterministic tests (183 local + 186 Cloud), the separate live ADK eval is 6/6 at 1.00 trajectory and 1.00 quality, and failure/replay/budget controls are enforced outside prompts. | `make test`, `make cloud-test`, release checks, eval scorecard, and `r-20260831-48141a`: 13 turns, 6/6 cross-worker checklist items, a committed 882-word checkpoint with 22/22 audited claims supported, and a delivery receipt. The later 897-word mutation is disclosed separately. | Capture a 3:55-or-shorter entry containing continuous live execution, plus its complete 1× run; verify signed-out playback, repository access, and Devpost fields. Preserve the turn-7 containment advisory as an operator-edit event, not an agent escape. |

## Bonus posture

Claim only the public build-content bonus after the article/social post and its
links are actually public. Use the exact hashtag `#AllThingsAgenticHackathon`.
Do not claim Memory Bank, capability-aware routing, Gemini Enterprise Agent
Platform, or an additional Google AI model. Do not add a decorative Gemma, Veo,
Lyria, or other model call solely for points.

## Four-minute evidence order

1. **Unlikely hero + live intake (0:00–0:52):** show Terry's five-person-firm
   outcome, press Send, and keep the live run ID and first state change visible.
2. **Google proof (0:52–1:24):** show the real Cloud Run/ADK/Firestore or Trace
   handoff without leaving the continuous take.
3. **Agent work (1:24–2:24):** show live progress, then the preserved rejection
   and owner-to-verifier evidence from primary run `r-20260831-48141a`.
4. **Enforced checklist (2:24–2:56):** use only `r-20260831-48141a` for 13
   turns, 6/6, the committed 882-word checkpoint with 22/22 audited claims,
   and the delivery receipt. Do not call the later 897-word mutation audited.
5. **Separate recovery (2:56–3:16):** visibly label `r-20260830-447f2f` as the
   successful Second Wind receipt; never attach its recovery to primary-run
   numbers.
6. **Readiness (3:16–3:43):** show 369 tests, 6/6 eval, and content-free trace.
7. **User receipt (3:43–3:55):** close on the primary final brief and delivery.

## Submission gates

- The repository remains private during final hardening. Publish it or provide
  the required judge access before treating source review as complete.
- Preserve the final state and sanitized capture for `r-20260831-48141a`.
- Treat `r-20260831-48141a` as completed evidence unless an actual continuous
  recording of its execution exists. A replay or dashboard inspection is not a
  live run. If the entry captures a new run, show its real ID and results.
- Use `r-20260830-447f2f` only as a separately labeled successful Second Wind
  proof. The primary run's recovery attempt was unresolved and later required
  an authenticated human resume.
- Use the committed 882-word evidence snapshot for the 22/22 audit claim. The
  final workspace grew to 897 words after verification; disclose that late
  mutation and do not call it covered by the audit. The delivered report also
  retained an earlier 834-word checkpoint.
- Disclose its turn-7 containment advisory: concurrent operator edits to
  submission documents triggered the fingerprint during Gemini's turn.
- Keep the entry at 3:55 or shorter and use one continuous take. If compressed,
  speed the entire take uniformly, disclose the factor on screen, and do not
  cut or splice it. Publish the complete 1× capture beside it.
- Show real Cloud Run plus Gemini 3.7/ADK and Firestore or Trace; the architecture
  diagram is supporting context, not deployment proof.
- Do not claim Memory Bank, Agent Runtime, Gemini Enterprise Agent Platform, or
  a Gemma/Veo/Lyria integration.
- Replace every video, full-run, and public-source placeholder; verify links
  signed out.
- Freeze the exact submitted repository, site, video, and identifiers after the
  deadline confirmation is archived.
