# Video production package

## Deliverables

Produce two distinct artifacts:

1. `rally-entry-4m.mp4` — narrated, captioned, four minutes or shorter.
2. `rally-golden-run-unedited.mp4` — complete proof from before Send through the
   final report, with secrets and unrelated notifications excluded at capture.

The unedited run makes the agent labor falsifiable. The short film makes it
understandable.

## Capture layout

Use 1920×1080 at 30 fps. Keep browser zoom at 110–125% and terminal text at
least 18 px. Use a neutral desktop, disable notifications, and keep the mouse
stationary unless it is pointing at a receipt.

Prepare four scenes:

| Scene | Left | Right | Purpose |
|---|---|---|---|
| Commission | Inbox compose | Architecture diagram | User value and mental model |
| Work | Repository diff/editor | `make serve` + test output | Visible agent action |
| Verify | Email turn/checklist | Run state evidence | Different-family verdict |
| Cloud proof | Cloud Run/Firestore | Trace/eval summary | Google path and readiness |

Do not record Secret Manager payloads, raw webhook URLs, bearer tokens, thought
signatures, personal inbox content, browser account menus, or terminal history.

## Capture order

1. Record the full golden run first. If it fails, preserve it as diagnostic
   evidence and start a new run ID; never edit the failed run into a success.
2. Export the unedited proof master.
3. Record clean architecture, eval, test, and Cloud evidence pickups.
4. Record narration against the locked `docs/DEMO-SCRIPT.md` timing.
5. Assemble the short entry with explicit `elapsed time` cards at every jump.
6. Caption, normalize speech, inspect every frame around account transitions,
   and export.

## Acceptance checks

- The email Send, intake, first scoped turn, and one owner-to-verifier sequence
  are continuous in the short film.
- One worker visibly edits code and runs tests.
- The checklist visibly enters `awaiting-verification`.
- The other model family visibly accepts or rejects the evidence.
- Gemini 3.7, Google ADK, Cloud Run, and Firestore are readable on screen.
- The final state shows `owner != verified_by` and concrete evidence.
- All elapsed-time compression is labeled.
- Captions remain inside safe margins and match the narration.
- Both videos play in a signed-out browser and their links are public.

## Suggested chapter cards

- `00:00  THE TRUST GAP`
- `00:25  EMAIL IS THE INTERFACE`
- `00:55  GOOGLE GOVERNS THE HANDOFF`
- `01:30  WATCH THE AGENTS WORK`
- `02:25  EVIDENCE, NOT CONFIDENCE`
- `03:05  EVALUATED AND OBSERVABLE`
- `03:35  THE SECOND OPINION ARRIVES`

End card: **ONE REQUEST · TWO MODEL FAMILIES · ZERO SELF-APPROVAL**
