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

## Business-system connection sequence

| Priority | Connector | Why it earns native support | Authentication and minimum first scope | Required action policy | Status |
|---|---|---|---|---|---|
| 1 | Google Workspace | Gmail, Drive, Docs, Sheets, Slides, Calendar, Chat, and People cover the daily operating surface of a company and inherit existing user permissions. | Pre-registered confidential Google OAuth with 15 pinned read-only scopes. | The first preset is read-only. Sending, drafting, sharing, calendar changes, and broad writes remain outside it. Treat retrieved content as untrusted. | Eight-service bundled runtime adapter and read-minimal preset shipped; customer Cloud project registration and live auth pending |
| 2 | Slack | Slack holds team history, decisions, status, and the natural place to request human approval. Its official MCP server supports search, messages, canvases, and users. | Confidential OAuth for an internal or Marketplace app; public/read-only scopes only. | Private search, posting, channel creation, and user-affecting actions are excluded from the first preset. | Runtime adapter and read-minimal preset shipped; customer app registration and live auth pending |
| 3 | GitHub | It converts Rally's current repository proof into a customer-grade installation with explicit repositories and auditable platform identity. | Dedicated GitHub App/OAuth token or fine-grained PAT; five pinned toolsets. | Server-enforced read-only and lockdown headers; write, merge, settings, secrets, releases, and destructive tools are unavailable. | Runtime adapter and read-only preset shipped; customer token and live discovery pending |
| 4 | Cloudflare | Worker observability makes the operating health of a company's web applications available without exposing broad API execution. | OAuth to Cloudflare's narrow Observability MCP server. | Exactly three read-oriented observability tools; the broad API `execute` surface remains unavailable. | Runtime adapter and observability preset shipped; customer auth and live discovery pending |
| 5 | n8n | One connection can expose only administrator-enabled workflows and provide a controlled bridge into the long tail of the business stack. | Tenant-scoped n8n Cloud MCP endpoint and user OAuth. | Exact workflow IDs only; execution requires a one-time human approval; workflow mutation and credentials remain unavailable. | Runtime adapter and workflow-bounded preset shipped; tenant auth and live discovery pending |
| 6 | Stripe | Payments, subscriptions, customers, and revenue reporting make cross-system operating work tangible while demanding unusually strict controls. | Stripe OAuth, scoped separately by environment. | Minimal account/documentation/search reads only; refunds, broad reads, writes, and money movement are excluded. | Runtime adapter and read-minimal preset shipped; customer auth and live discovery pending |
| 7 | BigQuery | It gives Rally a governed analytical surface for the large datasets and background research emphasized by the hackathon brief. | Google ADC or workload identity against Google's official remote MCP endpoint. Start with metadata; grant `roles/mcp.toolUser` plus the narrowest dataset roles. | The built-in preset exposes four metadata tools and no SQL. Bounded read-only SQL is a separate administrator decision. | Runtime adapter shipped; live MCP handshake and six-tool discovery verified 2026-08-29; metadata-only preset shipped |
| 8 | Atlassian | Jira, Confluence, and Compass combine planned work, institutional knowledge, and service ownership—the context professionals otherwise carry between assistants. | OAuth 2.1 through Atlassian's hosted Rovo MCP server, restricted to selected sites and products. | Search and retrieval may be read-only. Create, edit, transition, and notification tools remain excluded. | Runtime adapter and read-minimal preset shipped; customer auth and live discovery pending |
| 9 | Salesforce | CRM and service records provide the customer and revenue truth required for high-value operating work. | Customer External Client App plus OAuth to Salesforce's read-only SObject server. | Six bounded schema, SOQL, SOSL, identity, recent-record, and relationship tools; no mutation endpoint. | Runtime adapter and SObject Reads preset shipped; customer app, endpoint, auth, and live discovery pending |

## External agent network

Business connectors give Rally tools and context. External agent systems are
different: they accept delegated work and return task state or artifacts. Keep
them in a separate **agent network** surface so customers can distinguish
"Rally may read this system" from "Rally may commission this workforce."

| System | Interoperability path | Rally decision | Required boundary | Status |
|---|---|---|---|---|
| Gemini, Claude, OpenAI Codex | Provider-native CLI workers | Core workforce | Per-user provider sign-in, distinct model-family identity, shared checklist, no self-approval | Shipped and live-authenticated |
| Hyperagent | Hosted OAuth MCP | Support as a managed external workforce | Read agent/thread state by default; start, send, and upload require exact approval; never resolve Hyperagent approvals autonomously | Gateway adapter and read-minimal preset shipped; customer auth pending |
| Hermes Agent | Native bidirectional A2A v1.0 | Highest-priority external peer | Customer-hosted HTTPS endpoint, Agent Card pin, per-peer bearer identity, bounded task/turn limits, Rally-owned durable task mirror and independent verification | Official interface verified; Rally outbound A2A admission not yet shipped |
| OpenClaw | Native authenticated A2A v1.0 | Support after Hermes through the same A2A admission boundary | Expose only selected agent IDs; unique peer token; 1 MiB request/64 KiB text ceilings; Rally persists task state because OpenClaw's A2A task store is memory-only | Official interface verified; Rally outbound A2A admission not yet shipped |
| Prime Intellect | CLI/SDK for sandboxes, environments, compute, evaluation, and training | Do not present as an agent peer | Evaluate later as isolated execution infrastructure; require API-key isolation, explicit spend ceilings, and workload teardown | No stable A2A or hosted agent-delegation contract verified |

This avoids bespoke local-runtime adapters for Hermes and OpenClaw. Rally can
reuse the Google-originated A2A protocol it already implements, while retaining
its own authority, receipts, Second Wind recovery, and verification invariant.
An adapter is not labeled connected until a real customer-owned endpoint passes
Agent Card discovery, authentication, task submission, polling, failure, and
replay tests.

## Three protocols, three jobs

- **WebMCP** is the human-present surface: a browser agent and person inspect
  the same live evidence and prepare the same governed job draft.
- **A2A** is the agent-network surface: independent workforces discover one
  another and exchange durable tasks and artifacts.
- **MCP** is the business-tool surface: a Rally worker uses an explicitly
  approved capability behind the run's frozen authority snapshot.

Keeping these roles separate is a product advantage. WebMCP cannot become a
hidden submission path, A2A cannot become an approval bypass, and a remote MCP
tool cannot silently turn into another autonomous workforce. Rally remains the
authority and receipt layer across all three.

## Why MCP fits—but is not the security policy

Google ADK can dynamically discover tools from an MCP server and filter which
tools it exposes. That is the interoperability layer. Rally must still own the
authorization layer: connector allowlists, per-action risk classes, budgets,
independent verification, human gates, and append-only evidence stay outside
the model and outside the remote tool server.

## Why A2A fits—but is not Rally's product

MCP gives an agent a standard way to use tools. The Google-originated
[Agent2Agent (A2A) Protocol](https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability/)
gives independent agents a standard way to discover capabilities and exchange
long-running work across vendors. A2A reached stable v1.0 and, on August 27,
2026, was
[accepted into the Linux Foundation's Agentic AI Foundation at Growth Stage](https://a2a-protocol.org/latest/blog/2026/08/27/a-new-chapter-for-a2a-joining-the-agentic-ai-foundation/).

That makes A2A the correct interoperability boundary for Rally, not a
replacement for Rally. The protocol can carry discovery, messages, task state,
and artifacts. Rally must still own commission intent, connector authority,
budgets, ownership, cross-family verification, Second Wind recovery, evidence,
and human control outside that boundary.

The current release implements that thin, replaceable adapter with the official
A2A Python SDK. A public Agent Card advertises one real skill and two v1.0
bindings: JSON-RPC and HTTP+JSON. Message IDs become Rally idempotency keys;
only bounded receipts return as artifacts; A2A task protobufs persist in
Firestore. The adapter calls Rally's existing commission function, so the
deterministic runner remains authoritative and the protocol cannot become a
less-governed side door. Compatibility is tested with official SDK clients and
is not presented as certification or endorsement.

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
- [BigQuery's official remote MCP server](https://docs.cloud.google.com/bigquery/docs/use-bigquery-mcp)
  uses Google identity, IAM, audit logs, and optional Model Armor. Rally adds a
  per-run tool allowlist and content-free call receipts outside the model.
- [Atlassian's Rovo MCP server](https://www.atlassian.com/platform/rovo-mcp)
  is the hosted OAuth path for Jira, Confluence, and Compass tools.
- [Salesforce hosted MCP servers](https://developer.salesforce.com/blogs/2026/06/the-salesforce-developers-guide-to-the-summer-26-release)
  expose Salesforce platform capabilities through tenant-authorized MCP
  endpoints, including CRM data and custom platform actions.
- [Hermes Agent A2A](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/a2a)
  provides bidirectional A2A v1.0, official-SDK interoperability, per-peer
  bearer identities, signed push notifications, audit logging, and anti-loop
  limits.
- [OpenClaw A2A](https://docs.openclaw.ai/channels/a2a) provides authenticated
  A2A v1.0 discovery, submission, and polling with per-peer session isolation;
  its current task store is memory-only and therefore cannot replace Rally's
  durable ledger.
- [Prime Intellect CLI and SDK](https://github.com/PrimeIntellect-ai/prime)
  exposes compute, sandboxes, environments, evaluation, and training rather
  than a stable remotely callable agent peer.
