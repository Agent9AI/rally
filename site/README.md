# Rally website

The public site at `https://rally.agent9.dev` is deployed from this
directory. It is intentionally static: it collects no credentials, stores no
form data, and never pretends an external account is connected before a complete
OAuth integration exists.

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
