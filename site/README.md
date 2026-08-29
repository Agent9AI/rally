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
