# Rally product direction

## The category

Rally is not another chat window, model router, agent builder, or coding
copilot. It is the **accountable AI team**: one company identity that rallies
the right models around an outcome, lets them work through explicitly trusted
systems, and returns one independently verified result with evidence.

The public promise is:

> Your AIs, finally on the same team.

The customer should experience one Rally address and one accountable result.
Behind that identity, Gemini, Claude, and future specialized agents can hold
different roles. Rally owns the goal, handoffs, authority, and chain of custody;
no individual model is the product.

The product's distinctive contract is:

> The model that performs consequential work cannot approve that work.

Its continuity promise is **Second Wind**: when one model hits a recoverable
failure, Rally preserves accepted state and gives its teammate a bounded chance
to diagnose or take over. This is recovery without auto-approval; the backup's
repair still requires independent verification.

That contract combines five things competitors often present separately:

1. one shared team identity instead of isolated assistants per employee;
2. least-privilege access to company systems;
3. policy and limits enforced outside model prompts;
4. independent verification by a different model family; and
5. an action trail that a non-technical owner can inspect.

The live release proves this contract on governed repository work. The broader
company-operator claim becomes real only as customer-authorized connectors ship;
the website must keep that boundary explicit.

## What “give the team a goal” means

Start with one bounded outcome the operator should own repeatedly. Define the
systems it may use, the actions it may take without interruption, the actions
that require independent verification, and the actions that always require a
human. Then run a genuine job and inspect the receipts.

This is clearer than “request a managed pilot,” which describes a sales process
rather than a customer outcome.

## Connection sequence

| Priority | Connector | Why it earns native support | Authentication and minimum first scope | Required action policy | Status |
|---|---|---|---|---|---|
| 1 | Google Workspace | Gmail, Drive, Docs, Sheets, Slides, Calendar, Chat, and People cover the daily operating surface of a company and inherit existing user permissions. | Google OAuth with the narrowest per-product scopes. Begin with selected-file reads, draft creation, free/busy, and bounded Sheet ranges. | Sending mail or chat, sharing files, changing calendars, and broad writes require a human gate. Treat retrieved content as untrusted. | Researched official remote MCP; customer connection not shipped |
| 2 | Slack | Slack holds team history, decisions, status, and the natural place to request human approval. Its official MCP server supports search, messages, canvases, and users. | Confidential OAuth with only the search/read scopes needed first. Add `chat:write` only for approved workspaces. | Search and drafting may be autonomous. Posting, channel creation, and user-affecting actions require verification or human approval. | Researched official MCP; customer connection not shipped |
| 3 | GitHub | It converts Rally's current repository proof into a customer-grade installation with explicit repositories and auditable platform identity. | A dedicated GitHub App is preferred over a broad personal token. Expose only selected repositories and required issue/pull-request/check permissions. | Branch work and pull-request creation may be verified autonomously. Merge, settings, secrets, releases, and destructive operations require a human gate. | Current product wedge; native platform connection not shipped |
| 4 | Cloudflare | Sites, DNS, Workers, storage, observability, and security make it the operating plane for a company's web presence. | OAuth with customer-selected permissions. Begin with account discovery, analytics, build status, logs, and configuration reads. | Configuration writes require a second-family verifier; domain transfer, tokens, billing, and destructive storage actions remain unavailable. | Researched official MCP; customer connection not shipped |
| 5 | n8n | One connection can expose only administrator-enabled workflows and provide a controlled bridge into the long tail of the business stack. | Instance-level MCP with per-client authorization. Begin with search and execution of explicitly exposed, published workflows. Never auto-expose new workflows. | Workflow execution follows a declared risk class. Workflow creation, editing, and data-table writes require verification; credential operations remain unavailable. | Researched official MCP; customer connection not shipped |
| 6 | Stripe | Payments, subscriptions, customers, and revenue reporting make cross-system operating work tangible while demanding unusually strict controls. | Stripe OAuth, scoped separately by environment. Begin with API reads, documentation, analytics, and reports. | Refunds and all write or money-moving tools require human confirmation; production and sandbox access remain separate. | Researched public-preview MCP; customer connection not shipped |

## Why MCP fits—but is not the security policy

Google ADK can dynamically discover tools from an MCP server and filter which
tools it exposes. That is the interoperability layer. Rally must still own the
authorization layer: connector allowlists, per-action risk classes, budgets,
independent verification, human gates, and append-only evidence stay outside
the model and outside the remote tool server.

The sequence for every connector is:

```text
company outcome
      ↓
Google-governed intake and identity
      ↓
Rally policy: is this connector + action allowed?
      ↓
tool call with narrow customer authorization
      ↓
receipt + state change
      ↓
independent verification or human gate
```

## Source notes

- [Google ADK `MCPToolset`](https://adk.dev/api-reference/typescript/classes/MCPToolset.html)
  dynamically discovers MCP tools and supports explicit tool filters.
- [Cloudflare's official API MCP server](https://developers.cloudflare.com/agents/model-context-protocol/cloudflare/servers-for-cloudflare/)
  uses OAuth with customer-selected permissions and exposes Cloudflare's API
  through a search-and-execute interface.
- [n8n instance-level MCP](https://docs.n8n.io/connect/connect-to-n8n-mcp-server/)
  supports centrally authorized clients and explicit workflow exposure. Its
  documentation also warns that enabled workflows are not isolated per client,
  so Rally should use a dedicated client and a conservative workflow allowlist.
- [GitHub's official MCP host guide](https://github.com/github/github-mcp-server/blob/main/docs/host-integration.md)
  documents OAuth 2.1/PAT authentication and recommends a dedicated app for a
  distributed client.
- [Google Workspace remote MCP servers](https://developers.google.com/workspace/guides/configure-mcp-servers)
  are available in Developer Preview for Gmail, Drive, Docs, Sheets, Slides,
  Calendar, Chat, and People. They use OAuth and inherit user permissions. Google
  also warns that connected agents can be exposed to indirect prompt injection,
  reinforcing the need for Rally's external policy and review gates.
- [Slack's official MCP server](https://docs.slack.dev/ai/slack-mcp-server/)
  supports workspace search, message and canvas operations, user context, and
  confidential OAuth with per-tool scopes.
- [Stripe's official MCP server](https://docs.stripe.com/mcp) uses OAuth,
  separates live and sandbox authorization, exposes read/write API tools, and
  explicitly recommends human confirmation for consequential tools.
