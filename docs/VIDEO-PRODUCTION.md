# Rally demo recording sheet

## Fastest safe production method

Record one continuous **1920×1080, 30 fps** master while reading
`docs/DEMO-SCRIPT.md`. That is the safest interpretation of “unedited, live
execution.” The filenames below are chapter markers and emergency pickups—not
permission to manufacture a run. If you assemble a cut, keep
`04-email-live.mov` continuous and label it **LIVE · UNEDITED**.

Final filename: **`rally-all-things-agentic-0355.mp4`**<br>
Untouched master: **`rally-live-master-1x.mp4`**

## Files and voiceover pickups

| Screen file | Voice file | Target |
|---|---|---:|
| `01-homepage.mov` | `vo-01.wav` | 0:22 |
| `02-magic-link.mov` | `vo-02.wav` | 0:21 |
| `03-dashboard-job.mov` | `vo-03.wav` | 0:25 |
| `04-email-live.mov` | `vo-04.wav` | 0:26 |
| `05-multi-agent-proof.mov` | `vo-05.wav` | 0:25 |
| `06-media-proof.mov` | `vo-06.wav` | 0:18 |
| `07-second-wind.mov` | `vo-07.wav` | 0:25 |
| `08-google-cloud.mov` | `vo-08.wav` | 0:30 |
| `09-architecture-repo.mov` | `vo-09.wav` | 0:27 |
| `10-close.mov` | `vo-10.wav` | 0:16 |

## One-page recording checklist

### Fifteen minutes before

- [ ] Set browser zoom to **110–125%**; confirm every critical label is readable
  in a 1080p preview.
- [ ] Turn on Do Not Disturb. Hide bookmarks, extensions, unrelated tabs,
  notifications, raw email headers, account menus, and all secrets.
- [ ] Put tabs in script order: homepage, sign-in email, dashboard, preserved
  primary run, Second Wind run, media receipt/files, Cloud Run, Firestore,
  trace/health, repository.
- [ ] Request the one-time sign-in email 2–5 minutes before recording.
- [ ] Prepare the dashboard and email text, but leave the final sentence unsent.
- [ ] Open project `rally-agent9-2026` and verify the currently ready Cloud Run
  revision before filming; narrate the visible revision, not a memorized value.
- [ ] Confirm `r-20260831-48141a` and `r-20260830-447f2f` load without private
  data or debug overlays.
- [ ] Confirm the Lyria MP3 plays and its provider/model receipt is readable.
  Claim Rally email delivery only if the actual message is visible.

### During the take

- [ ] Start with the homepage already loaded; move the pointer deliberately.
- [ ] Hold each new run ID for two seconds.
- [ ] Never wait for a fresh run to finish. A real state transition plus the
  preserved completed evidence is stronger and predictable.
- [ ] Keep the 1:08–1:34 email-to-queue sequence uninterrupted.
- [ ] Show exactly one active state change, then move to preserved proof.
- [ ] Show only sanitized Cloud fields: service, ready revision, run ID, status,
  attempts, and `handoff.source`.
- [ ] Stop at **3:55**, even if a live request is still running.

### If something fails

- [ ] Magic link fails: begin already authenticated and show the clean sign-in
  email as proof; do not troubleshoot on camera.
- [ ] Email polling is slow: show the ingress receipt/run ID and say “accepted,”
  not “completed.”
- [ ] Media email is not confirmed: show the direct Vertex receipt and generated
  MP3/image only. Do not describe them as delivered through Rally email.
- [ ] Cloud Console stalls: use pre-opened sanitized screenshots plus the public
  repository implementation.

### Before upload

- [ ] Duration is **3:55 or less**; speech is intelligible at 1×.
- [ ] The live segment contains no cuts, hidden errors, or substituted data.
- [ ] Video visibly proves Gemini 3.7+, Google ADK, Cloud Run, and Firestore.
- [ ] Upload public YouTube/Vimeo, verify while signed out, then paste the URL
  into Devpost before polishing anything else.

Official references: [rules](https://allthingsagentichackathon.devpost.com/rules),
[FAQ](https://allthingsagentichackathon.devpost.com/details/faqs), and
[final submission checklist](https://allthingsagentichackathon.devpost.com/updates/45670-final-call-for-submissions).
