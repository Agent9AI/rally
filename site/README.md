# Rally website

The public site at `https://rally.agent9.dev` is deployed from this directory.
Its marketing and evidence surfaces are static. The hosted `/admin/` frontend
submits a credential only after verified Google sign-in, sends it directly over
HTTPS to the separate Google Cloud control plane, and keeps identity, session,
and credential values in page memory rather than persistent browser storage.
The control plane encrypts each credential before Firestore persists it and
never presents storage alone as a verified connection.

The registered production connector callback is intercepted by the Cloudflare
Worker and relayed server-side. Consent start creates a short-lived, per-flow
`HttpOnly`, `Secure`, `SameSite=Lax` browser-binding cookie; the Worker
requires it at callback and clears it afterward. The static Pages origin is not a
callback fallback, so OAuth fails closed when the Worker is unavailable. The
admin page receives neither the one-time provider code nor a provider token.
Workers Logs and automatic tracing are disabled for this callback-bearing Worker
so Rally does not persist callback URLs in those Cloudflare observability
products; deployments must preserve that boundary.

Validate locally with:

```bash
python3 -m http.server 4173 --directory site
```

Deploy to the existing Cloudflare Pages project with Wrangler after review:

```bash
wrangler pages deploy site --project-name agent9-rally
```

`a2a-icon.svg` is an optimized copy of the
[official A2A Protocol mark](https://github.com/a2aproject/A2A/tree/main/docs/assets/a2a_logo),
included only to identify the protocol in factual ecosystem context. It is not
a certification mark and does not imply that Google, the A2A project, or the
Linux Foundation endorses Rally.

`rally-logo.png` is the transparent full lockup supplied for the current Rally
identity. `rally-symbol.png` is its lossless, symbol-only web crop for compact
placements and the favicon. The mark shows distinct agents rallying around one
objective, with the blue path encoding coordinated work and the green check
encoding independent verification. `rally-mark.svg` remains in the repository
as an experimental Newton's-cradle handoff-motion study; it is no longer the
primary brand mark.

The public A2A v1.0 discovery document lives at
`.well-known/agent-card.json`. It intentionally advertises only the deployed
commission skill and contains security scheme names, never credentials.

`app.js` also feature-detects the official WebMCP `document.modelContext` API
and registers three bounded tools for the human-present browser experience:
live-run search, public verification inspection, and governed job drafting.
The draft only populates the visible setup dialog and mail link; it never sends,
stores, connects, or authorizes anything without the person's action. See
[`docs/WEBMCP.md`](../docs/WEBMCP.md) for the complete contract and demo flow.
