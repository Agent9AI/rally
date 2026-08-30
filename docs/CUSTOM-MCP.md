# Custom MCP admission

Custom remote MCP belongs in Rally as a governed long-tail connector, not as a
raw URL field. The first release should be labeled **Labs** and remain disabled
until its endpoint, OAuth metadata, discovered tool contract, and egress path
all pass admission.

## Admission contract

- Streamable HTTP over HTTPS/443 only. No stdio commands, local processes,
  WebSockets, legacy SSE, arbitrary headers, IP literals, embedded credentials,
  query-string tokens, or redirects.
- Resolve DNS before every connection and reject every non-global result,
  including loopback, RFC1918, link-local, CGNAT, IPv4-mapped IPv6, multicast,
  and cloud metadata addresses. Production traffic must leave through a
  dedicated egress proxy that cannot reach Rally's private network.
- OAuth 2.1 Authorization Code + PKCE/S256 only at launch. Require protected
  resource and authorization-server metadata, bind tokens to the MCP resource,
  forbid token passthrough, and never forward credentials across origins.
- Dynamic client registration or client-ID metadata provides the one-click
  path. A separately labeled advanced setup may accept a pre-registered client
  ID/secret into the encrypted credential store, never the repository or model
  context.
- Discover in quarantine: at most 20 pages, 128 tools, 512 KiB total metadata,
  64 KiB schema per tool, and 4 KiB description per tool. Names, descriptions,
  annotations, schemas, and results are untrusted input.
- Fingerprint server identity plus each tool's name, description, schema, and
  annotations. Administrator approval binds to that fingerprint; drift disables
  the affected tool until it is reviewed again.
- Default deny. A run sees only approved, fingerprint-matched tools. Provider
  `readOnlyHint` metadata informs review but never grants authority.
- Cap arguments at 256 KiB and results at 1 MiB by default, with lower per-tool
  ceilings and exact resource-ID allowlists where useful. Do not automatically
  fetch returned URLs. Sampling, roots, elicitation, and resource retrieval are
  separate future capabilities.
- Every state-changing tool requires a genuine approval bound to the exact
  connector, tool, argument digest, human identity, expiry, and one-time
  consumption. A receipt records the decision without business content.

The current gateway already supplies provider-pinned HTTPS endpoints,
default-deny tool policy, per-user credential namespaces, no redirects, bounded
discovery, argument/resource constraints, payload ceilings, and content-free
receipts, plus an exact, expiring, single-use human approval gate. Custom
arbitrary origins remain unshipped until DNS revalidation,
isolated egress, OAuth-origin admission, and schema-fingerprint locking exist.

## WebMCP is complementary

Rally's public site now registers three client-side tools through
`document.modelContext`: `rally_list_public_runs`,
`rally_inspect_public_run`, and `rally_draft_job`. They preserve the page's
visible state and let a human and browser agent review the same live evidence
and prepare the same onboarding draft. The draft tool cannot submit a job,
send email, connect a provider, or grant authority; the human must review the
visible form and click the final mail link.

This human-present WebMCP surface does not replace Rally's server-side remote
MCP gateway for asynchronous jobs. The similarly named `webmcp.dev` bridge
predates the current browser proposal and is not a Rally dependency. See
[`docs/WEBMCP.md`](WEBMCP.md) for the shipped contract, security boundary, and
demo path.

As of 2026-08-30, the official document is a Community Group Draft, not a W3C
Standard or a document on the W3C Standards Track. Its security section
explicitly identifies tool-metadata poisoning, output injection, ambiguous
side effects, cross-site privacy leakage, and same-origin risks. Those are
reasons to experiment behind Rally policy—not to merge browser authority into
the background connector plane.

Official references:

- [WebMCP Community Group Draft](https://webmachinelearning.github.io/webmcp/)
- [Official WebMCP project](https://github.com/webmachinelearning/webmcp)
- [MCP authorization specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)
