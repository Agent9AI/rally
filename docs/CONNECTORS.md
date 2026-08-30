# Connector gateway

Rally exposes one MCP server to every worker: `rally-connectors`. The gateway is
not a bag of credentials. It is a run-scoped policy boundary between a model and
each customer system.

BigQuery, Atlassian, Salesforce, and Hyperagent are implemented as the first
runtime adapters. They are committed **disabled**. A customer connection becomes usable
only after all four gates pass:

1. the user authenticates their own Google ADC or browser OAuth profile;
2. live MCP tool discovery answers from the provider;
3. an administrator explicitly allowlists individual read tools for that user; and
4. every worker receives the same immutable authority snapshot for the run.

Everything else defaults to deny. Retrieved connector content is untrusted
input. Arguments and results are hashed into receipts; their content is not
copied into the receipt log.

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
MCP successfully and returned six tools. Enable the five read-safe tools
explicitly; keep the broader `execute_sql` tool gated:

```bash
./bin/rally connectors enable bigquery \
  --tool list_dataset_ids=read \
  --tool get_dataset_info=read \
  --tool list_table_ids=read \
  --tool get_table_info=read \
  --tool execute_sql_readonly=read \
  --tool execute_sql=human_approval
```

For a separate commissioner profile, stage that user's ADC file and include
`--profile person@company.com --credential-file /private/path/to/adc.json` on
the `enable` command. The ignored policy stores only the path; the credential
file itself must remain private and outside the repository.

### Atlassian

```bash
./bin/rally connectors --profile person@company.com auth atlassian
./bin/rally connectors --profile person@company.com enable atlassian \
  --tool DISCOVERED_SEARCH_TOOL=read \
  --tool DISCOVERED_GET_TOOL=read
```

The first command performs OAuth 2.1 in the browser, stores OAuth state in the
profile-specific macOS Keychain service, and proves live Jira,
Confluence, or Compass tool discovery. Grant only the sites and products needed
for the demo.

### Salesforce

Salesforce's hosted MCP endpoint is tenant/server-specific. Stage that endpoint,
then authenticate and discover tools:

```bash
./bin/rally connectors --profile person@company.com enable salesforce \
  --endpoint 'https://YOUR-SALESFORCE-MCP-ENDPOINT' 
./bin/rally connectors --profile person@company.com auth salesforce
./bin/rally connectors --profile person@company.com enable salesforce \
  --tool DISCOVERED_QUERY_TOOL=read \
  --tool DISCOVERED_DESCRIBE_TOOL=read
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
surface. Starting or continuing external work remains behind the real
pre-execution gate and therefore fails closed in this release:

```bash
./bin/rally connectors --profile person@company.com auth hyperagent
./bin/rally connectors --profile person@company.com enable hyperagent \
  --tool list_agents=read \
  --tool list_threads=read \
  --tool get_thread=read \
  --tool create_thread=human_approval \
  --tool send_message=human_approval \
  --tool create_attachment_upload=human_approval
```

This connection is distinct from Hyperagent's optional ChatGPT subscription
connection. Rally authorizes the user's Hyperagent MCP account; it never
receives or brokers the user's ChatGPT entitlement through Hyperagent.

## Verify before a live run

```bash
./bin/rally connectors --profile person@company.com list
./bin/rally connectors --profile person@company.com doctor bigquery
./bin/rally connectors --profile person@company.com doctor atlassian
./bin/rally connectors --profile person@company.com doctor salesforce
./bin/rally connectors --profile person@company.com doctor hyperagent
./bin/rally --check
make test
make cloud-test
```

`doctor` is evidence: it authenticates, initializes an MCP session, and lists
the tools the provider actually returned. An enabled connector with zero read
tools remains discovery-only. `verify_first` and `human_approval` policies are
represented but fail closed in this release because a genuine pre-execution
approval workflow has not shipped; they are never treated as post-hoc review.

## Run receipts

Every run freezes its connector authority into
`runs/<run-id>/connector-authority.json`. Allowed, denied, and failed calls append
to `connector-receipts.jsonl` with actor, connector, tool, risk, decision,
duration, and SHA-256 hashes of arguments/results. The snapshot names only the
one-way credential-profile key. OAuth tokens, user email addresses, tool
arguments, and returned business data are excluded.

Official references:

- [BigQuery remote MCP server](https://docs.cloud.google.com/bigquery/docs/use-bigquery-mcp)
- [Atlassian Rovo MCP server](https://www.atlassian.com/platform/rovo-mcp)
- [Salesforce hosted MCP servers](https://developer.salesforce.com/blogs/2026/06/the-salesforce-developers-guide-to-the-summer-26-release)
- [Hyperagent hosted OAuth MCP server](https://www.hyperagent.com/docs/concepts/agents/invocations/mcp-server/)
