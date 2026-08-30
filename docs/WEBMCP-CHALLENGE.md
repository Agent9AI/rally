# WebMCP Challenge release plan

The WebMCP Challenge closes **September 3, 2026 at 1:00 PM PT**. Rally is an
existing open-source application with a live Cloudflare deployment, so the
submission should prove a polished human-agent workflow rather than rebuild the
product or add decorative tools.

Official judging criteria are WebMCP leverage, execution, potential impact,
and creativity/ambition. The submission also requires a working live URL, a
public licensed repository, a text explanation, and a public demo video under
three minutes.

## Submission story

> Browser agents can understand a dashboard. Rally lets them inspect the chain
> of custody behind the work, then prepare the next governed commission beside
> the human who remains responsible for sending it.

The differentiator is Rally's protocol bridge:

- WebMCP lets the browser agent and person work in the same live interface.
- A2A connects Rally to independent agent workforces.
- MCP connects those workers to approved company systems.
- Rally keeps authority, recovery, evidence, and independent verification
  outside every model and protocol.

## Three-minute proof

1. Open `https://rally.agent9.dev` in ChatGPT's built-in browser and show the
   three available site tools.
2. Ask: **“Find a blocked public Rally run and show me its verification gap.”**
   `rally_list_public_runs` updates the visible console, then
   `rally_inspect_public_run` opens the same authoritative record the agent is
   reading.
3. Ask: **“Prepare a bounded recovery job for that run using Google Workspace
   and BigQuery, with Second Wind on. Do not submit it.”**
   `rally_draft_job` opens and populates the visible managed-setup panel.
4. Point out the on-screen source run, trusted systems, recovery control, and
   human-confirmation boundary. Edit one field manually to show shared state.
5. Close on the protocol map: WebMCP for the shared page, A2A for agent tasks,
   MCP for company tools, Rally for accountability.

## Must-pass gate

- [ ] Latest ChatGPT desktop app, personal workspace, GPT-5.6 Sol or Terra
- [ ] Site tools enabled in Browser permissions
- [ ] Production page lists exactly three tools with correct read/write labels
- [ ] Live blocked-run search updates the visible D1 console
- [ ] Run inspection returns bounded checklist and numeric value receipt
- [ ] Public content is marked untrusted in both read tools
- [ ] Draft opens the managed setup panel and fills every requested field
- [ ] Draft result says not submitted, not transmitted, not stored, and requires
      human confirmation
- [ ] Clicking nothing produces no email, network write, credential request, or
      Rally commission
- [ ] Ordinary Chrome without WebMCP still works without console errors
- [ ] Public repository, Apache-2.0 license, setup instructions, and live URL
- [ ] Public video is under three minutes and includes visible tool invocations
- [ ] Submission completed before the deadline buffer, not at the deadline

Official challenge: <https://openai.com/webmcp-challenge/>
