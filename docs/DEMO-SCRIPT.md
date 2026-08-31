# Rally — 3:55 winning demo teleprompter

**Target:** 3:48–3:55, about 435 spoken words. Record the live intake section
without cuts. Keep every claim paired with something visible on screen.

## Shot-by-shot script

| Time | Exact screen clip and clicks | Exact voiceover | Proof shown | Backup shot |
|---:|---|---|---|---|
| **0:00–0:22** | `01-homepage.mov` — Rally homepage, pause on hero, click **Give Rally a job**. | **Every company can buy excellent AI. The broken part is the work between them: people carry context, restart failed jobs, and police confident answers. Rally removes that management tax. One business request becomes an accountable result across the AIs and systems a company already trusts and pays for.** | Hosted product; immediate value and “twist.” | Homepage still plus hero animation. |
| **0:22–0:43** | `02-magic-link.mov` — show company-email field, then the clean Rally email in Zoho; click **Sign in to Rally** and land on **Work**. | **Rally begins where work already happens. An employee enters an approved company email and receives this one-time link. No new password, no mailbox credential handed to a model. One click opens a policy-governed workspace shared by email and dashboard.** | Real passwordless auth and polished email. | Start authenticated; show the sign-in email for three seconds. |
| **0:43–1:08** | `03-dashboard-job.mov` — click **New job**, enter the prepared goal, keep **Second Wind** on, click **Accept into queue**, hold on the new run ID. | **Here I commission an executive brief from the dashboard. I specify the outcome, sources, and definition of done—not a chain of prompts. Rally attaches policy, selects specialized workers, allows one bounded recovery handoff, and issues a run receipt before work begins.** | Manual intake; actual run ID; governed policy. | Show a preserved dashboard receipt; call it preserved, not live. |
| **1:08–1:34** | `04-email-live.mov` — in Zoho, finish the final sentence of a prepared request, click **Send**, return to Rally, refresh once, and hold as its second run appears. **Do not cut this clip.** | **Now I send an assignment to rally at updates dot agent9 dot dev. Email enters the same durable queue, preserves subject and body, and creates its own run beside the dashboard request. Humans can reply later in this thread to refine or resume the work.** | Unedited Proof of Action; two intake doors, one queue. | If polling is slow, show the new email receipt and its run ID, then continue. |
| **1:34–1:59** | `05-multi-agent-proof.mov` — open the advancing run, then preserved run `r-20260831-48141a`; show timeline, 6/6 checklist, owner → verifier rows, and receipt. | **Inside the run, Gemini researches, Claude synthesizes, and Codex challenges. Deterministic policy—not a prompt—enforces owner not equal to verifier. This thirteen-turn run rejected unsupported claims, repaired them, and closed six of six independent checks with evidence. Zero items were self-approved.** | Complex delegation; mutation, verification, receipts. | Use only the preserved run and say “preserved proof,” never “live.” |
| **1:59–2:17** | `06-media-proof.mov` — play 3–4 seconds of `deliverable-song.mp3`, show its Vertex receipt and `lyria-3-pro-preview`. If an email delivery is confirmed before recording, show that message and attachment instead. | **This is the actual All Things Agentic song Rally generated with Lyria 3 Pro on Vertex AI—not a mock. Rally also generated an image through Google’s image model. Each file carries provider evidence and stays attributable to its governed request.** | Successful Google media-model generation; real MP3 and image output. | Use the provider receipt and generated files. Do not claim email delivery until visibly confirmed. |
| **2:17–2:42** | `07-second-wind.mov` — open `r-20260830-447f2f`; show 6/6 and the two **SECOND WIND** events. | **Agents fail. Rally plans for it. When a worker blocked on invalid evidence, Second Wind preserved accepted state and handed recovery to another model. The replacement repaired the work but could not approve itself; Claude later verified the outcome. Recovery never weakened policy.** | Failure-tolerant routing; enforced separation. | Sanitized screenshot of the same two events and run ID. |
| **2:42–3:12** | `08-google-cloud.mov` — Cloud Run service/revision → sanitized Firestore `rally_runs` record → content-free trace or `/health`. | **Google is load-bearing. Gemini 3.7 Flash runs through Vertex AI and Google ADK at an IAM-protected Cloud Run coordination boundary. Firestore atomically claims work and fences retries. Cloud Trace records metadata without prompt content, and Cloud KMS protects connection secrets. Licensed model workers execute separately; Google owns the authenticated governance plane.** | Mandatory Gemini, Google framework, Cloud deployment, state, telemetry. | Pre-opened screenshots with project and revision readable; never show Secrets. |
| **3:12–3:39** | `09-architecture-repo.mov` — README architecture diagram → proof ledger → A2A/WebMCP section → test badge. | **The repository makes every decision reproducible: scoped tools, replay-safe state, independent verification, and honest evidence boundaries. A2A admits governed agent tasks; WebMCP lets browser agents inspect receipts and prepare requests while confirmation stays human. Three hundred sixty-nine tests and six live ADK evaluations protect this path.** | Architectural Discipline; documentation; interoperability. | Local rendered README or OG proof card. |
| **3:39–3:55** | `10-close.mov` — return to dashboard receipt or delivered email; finish on Rally logo. | **Rally gives a small company what once required an AI operations team: accountable execution from the inbox to a verified deliverable. One request. The right specialists. Evidence before confidence. Rally is how your AIs work together.** | Memorable value close. | Final report plus `owner ≠ verifier`. |

## Exact demo requests

**Dashboard title:** `Board-ready Google AI opportunity brief`

**Dashboard goal:** `Using current primary Google sources, recommend the three
most consequential Google AI releases from the last 12 months for a five-person
services firm. Return a one-page decision brief with dates, source URLs,
business value, residual risk, and independent verification.`

**Email subject:** `Google AI releases — executive presentation`

**Email body:** `Create a polished executive presentation on the most
consequential Google AI releases from the last 12 months. Use primary Google
sources, include a claim ledger and residual risk, and require a different model
family to verify every factual claim and the finished deliverable.`

## Non-negotiable claim boundaries

- The 22/22 audit belongs only to the committed **882-word checkpoint** in
  `r-20260831-48141a`; disclose the later 897-word mutation if it appears.
- `r-20260830-447f2f` proves blocked-state recovery, not filmed usage exhaustion.
- Cloud Run coordinates; the controlled licensed-worker host executes provider
  CLIs. Do not say all worker execution runs in Cloud Run.
- Say **A2A v1.0 compatible**, never certified or Google-endorsed.
- The media proof currently establishes direct Google model generation. Say it
  was email-delivered only if that exact Rally message is visible in the take.
