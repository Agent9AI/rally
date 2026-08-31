# Public evidence index

Rally's live `runs/` directory is intentionally gitignored because it can hold
commissioner identity, provider message IDs, local paths, and raw business
context. This directory preserves the smallest judge-reviewable snapshots that
substantiate the public claims without publishing that private state.

| Receipt | What a reviewer can inspect | Important boundary |
|---|---|---|
| [`r-20260831-48141a`](r-20260831-48141a/) | The 882-word audited briefing checkpoint, its 13-source ledger, the 22-claim Codex audit, independent-verification ownership, and delivery metadata | After the audited checkpoint—and before report delivery—the workspace gained one post-audit pricing sentence. The 897-word file is **not** represented as covered by the 22-claim audit. |
| [`r-20260830-447f2f`](r-20260830-447f2f/) | A separate successful Second Wind custody transfer and 6/6 cross-worker checklist receipt | This is the recovery proof, not the primary email run. Its numbers are never merged with the primary run. |

These are sanitized evidence exports, not signed attestations. Each receipt says
which fields were removed and identifies the immutable source-workspace commit
where one exists. Those commits belong to gitignored run-local repositories and
are provenance labels, not objects in the public repository history; the
exported file hashes are directly reproducible from this directory. Live Google
Cloud proof belongs in the demo video, as required by the
[official rules](https://allthingsagentichackathon.devpost.com/rules); release
service identifiers are indexed in the root README and judge packet.
