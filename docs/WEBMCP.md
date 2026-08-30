# WebMCP browser collaboration

Rally exposes a small, working WebMCP surface from the public application at
`https://rally.agent9.dev`. A browser agent and a person can search the same
live run index, inspect the same verification record, and prepare the same
governed job draft without screen scraping or hidden submission.

WebMCP is the human-present edge of Rally. A2A handles agent discovery and task
exchange, the remote MCP gateway governs business tools used by background
workers, and WebMCP gives a browser agent structured access to the page the
person is actively reviewing.

## Tool contract

| Tool | Effect | Trust annotation |
|---|---|---|
| `rally_list_public_runs` | Reads the explicitly public D1 projection, filters it, and updates the visible live console | Read-only; returned public content is untrusted |
| `rally_inspect_public_run` | Opens one public run and returns a bounded checklist and numeric value receipt | Read-only; descriptions and evidence are untrusted |
| `rally_draft_job` | Populates the visible managed-setup form and pre-filled mail link | State-changing page draft; never transmitted without the person's click |

All three tools use explicit JSON Schemas with closed objects, type checks,
length limits, bounded arrays, and exact connector identifiers. The read tools
return only the public projection and label model- or user-authored strings as
untrusted. They do not return raw private runs, credentials, prompts, mail IDs,
worktree paths, or cloud request keys.

`rally_draft_job` accepts a concrete outcome, optional company/team context,
an allowlisted set of trusted systems, an optional source run, and the bounded
Second Wind preference. It performs no network write. Its result explicitly
reports `drafted_not_submitted`, `transmitted: false`, `stored: false`, and
`human_confirmation_required: true`.

## Why this is a WebMCP-native workflow

A useful demonstration is a three-tool collaboration:

1. Ask the browser agent to find a blocked public Rally run.
2. Ask it to inspect the incomplete verification record and explain what is
   missing while the same record opens in the visible console.
3. Ask it to prepare a recovery job referencing that run, using only approved
   systems and Second Wind. The managed-setup dialog opens with the draft.
4. The person reviews or edits every field and decides whether to click the
   final mail link.

The agent gains a reliable structured path through live application state. The
person keeps situational awareness and the consequential action. That division
is the point of the feature, not a limitation.

## Compatibility and testing

The implementation feature-detects `document.modelContext`, so ordinary
browsers keep the complete human experience with no polyfill or failure. Test
the deployed site in ChatGPT's in-app browser, or in Google Chrome with WebMCP
enabled at `chrome://flags/#enable-webmcp-testing`. A browser harness can also
provide a test `modelContext.registerTool` implementation before `app.js`
loads, then invoke the registered callbacks against the live public endpoint.

For ChatGPT testing, use the current desktop app with site tools enabled under
**Settings → Browser → Permissions**, and select GPT-5.6 Sol or GPT-5.6 Terra.
OpenAI's current documentation says GPT-5.6 Luna has WebMCP disabled and site
tools are not available in Enterprise or Edu workspaces. Inspect **Site tools →
Available site tools** in the browser address bar and preserve **Recently used**
as invocation evidence.

As of 2026-08-30, WebMCP is a Web Machine Learning Community Group Draft, not a
W3C Standard or a document on the W3C Standards Track. Rally keeps the API
behind feature detection and treats its metadata and outputs according to the
draft's prompt-injection, same-origin, privacy, and ambiguous-side-effect threat
model.

Official references:

- [WebMCP Community Group Draft](https://webmachinelearning.github.io/webmcp/)
- [Chrome WebMCP origin trial](https://developer.chrome.com/blog/ai-webmcp-origin-trial)
- [OpenAI WebMCP Challenge](https://openai.com/webmcp-challenge/)
- [Cloudflare WebMCP developer preview](https://blog.cloudflare.com/webmcp/)
- [OpenAI site tools documentation](https://learn.chatgpt.com/docs/webmcp)
