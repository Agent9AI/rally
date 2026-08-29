# Rally product direction

## The category

Rally is not another chat window, agent builder, or coding copilot. It is one
governed digital operator for a company: a persistent identity that can receive
outcomes, work through explicitly trusted systems, and return evidence.

The product's distinctive contract is:

> The model that performs consequential work cannot approve that work.

That contract combines five things competitors often present separately:

1. one shared operator identity instead of a personal assistant per employee;
2. least-privilege access to company systems;
3. policy and limits enforced outside model prompts;
4. independent verification by a different model family; and
5. an action trail that a non-technical owner can inspect.

The live release proves this contract on governed repository work. The broader
company-operator claim becomes real only as customer-authorized connectors ship;
the website must keep that boundary explicit.

## What “give Rally a job” means

Start with one bounded outcome the operator should own repeatedly. Define the
systems it may use, the actions it may take without interruption, the actions
that require independent verification, and the actions that always require a
human. Then run a genuine job and inspect the receipts.

This is clearer than “request a managed pilot,” which describes a sales process
rather than a customer outcome.

## Connector sequence

| Priority | Connector | Why it earns native support | Authentication and minimum first scope | Required action policy | Status |
|---|---|---|---|---|---|
| 1 | Cloudflare | Small companies commonly place sites, DNS, Workers, storage, and security behind one account. Cloudflare operates an official remote API MCP server covering its API. | OAuth with customer-selected permissions. Begin with account discovery, analytics, build status, logs, and configuration reads. | Configuration writes require a second-family verifier; domain transfer, token, billing, and destructive storage actions remain unavailable. | Researched; customer connector not shipped |
| 2 | n8n | One n8n connection can expose only owner-enabled workflows and provide a controlled bridge into a broad business-app ecosystem. | Instance-level MCP with per-client authorization. Begin with search and execution of explicitly exposed, published workflows. Do not auto-expose new workflows. | Workflow execution follows the workflow's declared risk class. Workflow creation/editing and data-table writes require verification; credential operations remain unavailable. | Researched; customer connector not shipped |
| 3 | Google Workspace | Google's Developer Preview remote MCP servers cover Gmail, Drive, Docs, Sheets, Slides, Calendar, Chat, and People while inheriting the user's permissions and data-governance controls. This is the closest fit to Rally's Google governance plane. | Google OAuth with the narrowest per-product scopes. Begin with draft creation, selected-file reads, free/busy, and bounded Sheet ranges. | Sending mail or chat, sharing files, changing calendar data, and broad writes require a human gate. Treat content retrieved from mail and documents as untrusted because Google explicitly warns about indirect prompt injection. | Researched Developer Preview; customer connector not shipped |
| 4 | GitHub | It converts Rally's current local-repository proof into a customer-grade installation with explicit repositories and auditable platform identity. | A dedicated GitHub App is preferred over a broad personal token. Expose only selected repositories and required issue/pull-request/check permissions. | Branch work and pull-request creation may be verified autonomously. Merge, settings, secrets, releases, and destructive operations require a human gate. | Current product wedge; native platform connector not shipped |

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
