# Connector gateway

Rally exposes one MCP server to every worker: `rally-connectors`. The gateway is
not a bag of credentials. It is a run-scoped policy boundary between a model and
each customer system.

All ten catalogued providers—Google Workspace, Slack, GitHub, Cloudflare
Observability, n8n Cloud, Stripe, BigQuery, Atlassian, Salesforce, and
Hyperagent—have runnable gateway adapters. They are committed **disabled**.
A customer connection becomes usable
only after all four gates pass:

1. the user authenticates their own Google ADC or browser OAuth profile;
2. live MCP tool discovery answers from the provider;
3. an administrator explicitly allowlists individual read tools for that user; and
4. every worker receives the same immutable authority snapshot for the run.

Everything else defaults to deny. Retrieved connector content is untrusted
input. Arguments and results are hashed into receipts; their content is not
copied into the receipt log. Provider endpoints are HTTPS- and hostname-pinned,
redirects are refused, discovery is bounded to 128 tools/512 KiB, arguments to
256 KiB, and returned model-visible data to 1 MiB. Per-tool policy may narrow
those ceilings and constrain exact resource IDs before a network call.

The gateway ships named provider-safe presets. A preset is an exact tool
allowlist with smaller payload bounds; it is not a wildcard and never follows
future provider catalog growth automatically.

## Hosted activation

The Google-authenticated admin at `/admin/` is the hosted connection front
door. Cloudflare Observability, n8n Cloud, Stripe, Atlassian, and HyperAgent use
OAuth Authorization Code with PKCE and an exact Rally callback. Their OAuth
metadata and token endpoints are restricted to provider-owned hosts. GitHub has
a guided fine-grained-token path. Google Workspace, Slack, and Salesforce are
honestly held at provider-app setup instead of showing a Connect button that
cannot complete.

The browser retains neither credential nor connection session in persistent
storage. Google Cloud KMS envelope-encrypts tokens in the user-owned vault.
“Ready” is emitted only after live MCP discovery succeeds and at least one live
tool matches the committed safe preset. Hosted readiness does not itself grant
an agent authority: a later run must receive a separate immutable, run-scoped
authority snapshot through the execution gateway described below.

## Per-user isolation

A connection belongs to one commissioner, never to the Rally installation.
Rally normalizes the commissioner identity and stores only a one-way profile key
such as `p-a8…` in the ignored local policy file. Each OAuth provider gets a
profile-specific macOS Keychain namespace. At commission time, the authenticated
sender selects exactly one profile; its enabled connectors and tool policies are
frozen into the run. Another user cannot inherit that authority.

For direct CLI work, select the same boundary explicitly:

```bash
./bin/rally --as-user person@company.com --run "Prepare the account review"
./bin/rally connectors --profile person@company.com list
```

Codex uses the same run snapshot. It starts with `--ignore-user-config`, so an
unrelated MCP server from the user's global Codex configuration cannot bypass
Rally's gateway. Claude receives a strict per-run MCP file; Antigravity must have
the Rally gateway as its only enabled MCP server.

## Runtime-connector setup

First register the single Rally gateway with Antigravity:

```bash
./bin/rally connectors install
agy mcp list
```

Antigravity's MCP configuration is global. Before enabling a Rally connector,
disable every other enabled MCP server for this worker profile. Rally preflight
will refuse to run if a model could bypass the gateway.

### Google Workspace

Workspace is one Rally connector backed by eight official, pinned Google MCP
services. Rally qualifies discovered tools by service (`gmail.search_threads`,
`drive.search_files`, and so on) and dispatches each call only to that service.
The read-minimal preset requests 15 read-only Google scopes and contains no
draft, send, share, create, update, or delete tool.

```bash
./bin/rally connectors --profile person@company.com register-client google-workspace
./bin/rally connectors --profile person@company.com enable google-workspace \
  --preset read-minimal
./bin/rally connectors --profile person@company.com auth google-workspace
```

The administrator must first enable the eight Workspace MCP services, configure
Google OAuth, and register Rally's local callback URI. The client registration
and user token stay in that profile's macOS Keychain namespace.

### Slack

Slack requires a confidential OAuth client belonging to an internal app or a
Marketplace app; Slack prohibits unlisted apps from using its MCP server. The
initial Rally preset requests only public search, file/channel reads, and user
lookup scopes—no private-message search or mutation scope.

```bash
./bin/rally connectors --profile person@company.com register-client slack
./bin/rally connectors --profile person@company.com enable slack \
  --preset read-minimal
./bin/rally connectors --profile person@company.com auth slack
```

### GitHub

GitHub's remote MCP server requires a token obtained by Rally's host application;
the server does not perform OAuth itself. Import a dedicated GitHub App/OAuth
token or fine-grained PAT, then use the fixed read-only preset:

```bash
./bin/rally connectors --profile person@company.com import-token github
./bin/rally connectors --profile person@company.com enable github \
  --preset read-only
./bin/rally connectors --profile person@company.com doctor github
```

Every GitHub request carries provider-enforced read-only and lockdown headers
plus the pinned `context`, `repos`, `issues`, `pull_requests`, and `users`
toolsets. A local policy edit cannot weaken those headers.

### Cloudflare Observability

Rally starts with Cloudflare's narrow Observability MCP server rather than the
broad API server whose `execute` tool can perform reads or writes. Authenticate,
review the live schemas, and allow only the three read-oriented tools:

```bash
./bin/rally connectors --profile person@company.com auth cloudflare
./bin/rally connectors --profile person@company.com enable cloudflare \
  --preset observability
```

The pinned endpoint is `https://observability.mcp.cloudflare.com/mcp`. The
general Cloudflare API MCP server remains outside this preset until Rally can
classify the underlying API method, not merely the wrapper tool name.

### n8n Cloud

Rally accepts only the tenant-scoped HTTPS endpoint
`https://<tenant>.app.n8n.cloud/mcp-server/http`. Arbitrary self-hosted URLs are
not accepted through this adapter. n8n exposes workflows at the user level, so
administrators must disable automatic exposure and bind each allowed tool call
to explicit workflow IDs using Rally's argument constraints.

```bash
./bin/rally connectors --profile person@company.com enable n8n \
  --endpoint 'https://YOUR-TENANT.app.n8n.cloud/mcp-server/http' \
  --preset workflow-bounded \
  --workflow-id 'EXACT-WORKFLOW-ID'
./bin/rally connectors --profile person@company.com auth n8n
```

Discovery alone grants no execution. `execute_workflow` belongs behind human
approval; search, creation, editing, publishing, archiving, agent mutation, and
data-table writes remain denied by default.

### Stripe

Stripe's pinned hosted endpoint supports OAuth 2.1 with dynamic registration:

```bash
./bin/rally connectors --profile person@company.com auth stripe
./bin/rally connectors --profile person@company.com enable stripe \
  --preset read-minimal
```

Broad customer/financial reads, writes, refunds, reports, feedback submission,
and money movement are not part of the minimal preset. Sandbox and live Stripe
connections must be authorized and reviewed separately.

### BigQuery

BigQuery may use the local OS user's Application Default Credentials identity—no
API key or Rally token file. A non-local commissioner profile must name its own
ADC credential file; Rally refuses to fall back to the machine-wide identity.

```bash
gcloud auth application-default login
./bin/rally connectors --profile local doctor bigquery
```

The identity needs `roles/mcp.toolUser` plus the minimum BigQuery permissions
for the chosen job. Google's read-oriented starting point is
`roles/bigquery.jobUser` and `roles/bigquery.dataViewer`; narrow dataset access
further where possible. The first live doctor check on 2026-08-29 negotiated
MCP successfully and returned six tools. The built-in starting preset is
narrower: four metadata tools and no SQL execution surface.

```bash
./bin/rally connectors enable bigquery \
  --preset metadata-only
```

An administrator can later add `execute_sql_readonly=read` with explicit
project/dataset constraints. The broader `execute_sql` remains denied unless a
separate gated policy is deliberately configured.

For a separate commissioner profile, stage that user's ADC file and include
`--profile person@company.com --credential-file /private/path/to/adc.json` on
the `enable` command. The ignored policy stores only the path; the credential
file itself must remain private and outside the repository.

### Atlassian

```bash
./bin/rally connectors --profile person@company.com auth atlassian
./bin/rally connectors --profile person@company.com enable atlassian \
  --preset read-minimal
```

The first command performs OAuth 2.1 in the browser, stores OAuth state in the
profile-specific macOS Keychain service, and proves live Jira,
Confluence, or Compass tool discovery. Grant only the sites and products needed
for the demo.

### Salesforce

Salesforce's read-only hosted SObject MCP server is selected explicitly. Create
and activate a Salesforce External Client App, store its consumer key (and
secret when required), then authenticate and discover tools:

```bash
./bin/rally connectors --profile person@company.com register-client salesforce \
  --public-client
./bin/rally connectors --profile person@company.com enable salesforce \
  --endpoint 'https://api.salesforce.com/platform/mcp/v1/platform/sobject-reads' \
  --preset sobject-reads
./bin/rally connectors --profile person@company.com auth salesforce
```

OAuth state is stored in that user's namespaced Keychain service. Do not
commit tenant URLs if the organization treats them as private; the ignored
`config/connectors.local.json` holds local endpoint and allowlist settings.

### Hyperagent

Hyperagent publishes a hosted remote MCP server at
`https://hyperagent.com/api/mcp`. Each Rally user completes Hyperagent's
one-time browser OAuth flow; Rally keeps that token in the user's namespaced
Keychain service. The documented surface can list the user's agents and
threads, start a background thread, follow up, upload an attachment, and poll
for the result.

Authenticate first, inspect the live tool schemas, then enable the read-only
surface. Starting or continuing external work belongs behind Rally's exact,
single-use human approval gate:

```bash
./bin/rally connectors --profile person@company.com auth hyperagent
./bin/rally connectors --profile person@company.com enable hyperagent \
  --preset read-minimal
```

`resolve_approval` is never autonomous. The person must inspect and approve the
exact pending Hyperagent action; Rally then consumes that approval once.

For an explicitly allowlisted `human_approval` tool, the first call creates a
private, expiring request and returns its content-free ID. The administrator can
inspect and approve that exact call:

```bash
./bin/rally connectors approvals runs/RUN-ID --status pending
./bin/rally connectors review runs/RUN-ID APPROVAL-ID
./bin/rally connectors approve runs/RUN-ID APPROVAL-ID --as human-operator
```

The agent retries with that approval ID. Rally binds it to the run, connector,
tool, and complete argument digest, then consumes it before the network call;
reuse, argument substitution, expiry, and concurrent replay fail closed.

This connection is distinct from Hyperagent's optional ChatGPT subscription
connection. Rally authorizes the user's Hyperagent MCP account; it never
receives or brokers the user's ChatGPT entitlement through Hyperagent.

## Verify before a live run

```bash
./bin/rally connectors --profile person@company.com list
./bin/rally connectors --profile person@company.com doctor bigquery
./bin/rally connectors --profile person@company.com doctor cloudflare
./bin/rally connectors --profile person@company.com doctor stripe
./bin/rally connectors --profile person@company.com doctor atlassian
./bin/rally connectors --profile person@company.com doctor salesforce
./bin/rally connectors --profile person@company.com doctor hyperagent
./bin/rally connectors --profile person@company.com doctor google-workspace
./bin/rally connectors --profile person@company.com doctor slack
./bin/rally connectors --profile person@company.com doctor github
./bin/rally --check
make test
make cloud-test
```

`doctor` is evidence: it authenticates, initializes an MCP session, and lists
the tools the provider actually returned. An enabled connector with zero read
tools remains discovery-only. `human_approval` tools use the shipped exact,
expiring, one-time approval ledger. `verify_first` continues to fail closed
until an independent pre-execution verifier is selected; it is never treated as
post-hoc review.

## Run receipts

Every run freezes its connector authority into
`runs/<run-id>/connector-authority.json`. Allowed, denied, and failed calls append
to `connector-receipts.jsonl` with actor, connector, tool, risk, decision,
duration, and SHA-256 hashes of arguments/results. The snapshot names only the
one-way credential-profile key. OAuth tokens, user email addresses, tool
arguments, and returned business data are excluded.

Official references:

- [Google Workspace remote MCP servers](https://developers.google.com/workspace/guides/configure-mcp-servers)
- [Slack hosted MCP server](https://docs.slack.dev/ai/slack-mcp-server/)
- [GitHub remote MCP host guide](https://github.com/github/github-mcp-server/blob/main/docs/host-integration.md)
- [Cloudflare remote MCP servers](https://github.com/cloudflare/mcp-server-cloudflare)
- [n8n instance-level MCP](https://docs.n8n.io/connect/connect-to-n8n-mcp-server/)
- [Stripe hosted MCP server](https://docs.stripe.com/mcp)
- [BigQuery remote MCP server](https://docs.cloud.google.com/bigquery/docs/use-bigquery-mcp)
- [Atlassian Rovo MCP server](https://www.atlassian.com/platform/rovo-mcp)
- [Salesforce SObject Reads server](https://developer.salesforce.com/docs/platform/hosted-mcp-servers/references/reference/sobject-reads.html)
- [Hyperagent hosted OAuth MCP server](https://www.hyperagent.com/docs/concepts/agents/invocations/mcp-server/)
