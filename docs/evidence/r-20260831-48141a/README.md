# Primary email run · `r-20260831-48141a`

This is the sanitized repository receipt for Rally's five-person-firm Google AI
briefing commission. The live run completed after 13 governed turns, with all
six checklist items owned and verified by different workers, and the report was
delivered through Resend.

## Independently audited checkpoint

Commit `2fa5f26ba4364b8b5d1a0579663fd47c81928423` is the exact checkpoint Codex
audited and Claude independently re-checked in the following turn. It belongs
to the run-local workspace repository and is included as provenance; use the
committed files and SHA-256 values below for public verification.

- [`briefing-audited.md`](briefing-audited.md) — 882 words
- [`sources-audited.md`](sources-audited.md) — 13 official Google sources
- [`audit.md`](audit.md) — 22/22 audited product claims marked `SUPPORTED`
- [`receipt.json`](receipt.json) — sanitized checklist, provenance, recovery,
  and delivery metadata

The exported files match their source-workspace blobs byte for byte. Their
SHA-256 values are recorded in `receipt.json`.

The immutable audit snapshot retains Codex's malformed `?hl=en-4` locale query
in item 14. The corresponding source-ledger URL is the correct `?hl=en`; this
known typo does not change the verdict; the correct ledger URL supports the
claim. It is preserved so provenance remains byte-exact.

## The boundary that matters

After independently verifying the audit—and before report delivery—Claude added
a pricing-promotion sentence and expanded the source ledger. It asked to open a
seventh checklist item because it could not verify its own new claim. Rally
correctly rejected the late scope addition, but the workspace change remained
and the run completed with a 897-word file at commit
`854703939ca3a454c3f9a5318a0f460f6ae73ff6`.

The email report itself retained an earlier 834-word checkpoint; the 897-word
workspace state is not represented as the email payload. Accordingly, this
repository makes the narrower claim the evidence supports:
the 882-word checkpoint has a complete 22-claim independent audit. It does not
claim that the later 897-word workspace file is covered by that audit. This is
also a concrete hardening lesson: artifact mutation must invalidate prior
verification even when checklist scope is closed.

## Privacy treatment

The export omits commissioner identity and contact details, email and provider
message IDs, cloud request keys, local filesystem paths, raw model payloads, and
the private report body. It is a hand-curated evidence snapshot, not a signed
attestation or substitute for the live Google Cloud proof in the demo.
