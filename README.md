# Rally

Two AI coding agents, from different model families, carry one task to completion
by writing email to each other. A person commissions the run. The checklist
decides when it ends.

The first two participants are the **Claude CLI** (`claude -p`) and the
**Antigravity CLI** (`agy -p`), with **Resend** as the transport.

## Documents

| Document | What it is |
|---|---|
| [docs/FOUNDING.md](docs/FOUNDING.md) | The charter. Intent, principles, guardrails. Authority on why. |
| [docs/SPEC.md](docs/SPEC.md) | The build. Envelope, state machine, limits, invocation. |
| [docs/DIAGRAMS.md](docs/DIAGRAMS.md) | The system in four figures. |
| [docs/BUILD-1HR.md](docs/BUILD-1HR.md) | The cut-to-the-bone first hour. |

## The two rules everything else protects

1. An item reaches `done` only when the agent that **did not** do the work
   verifies it.
2. The two agents must come from **different model families**. Same-family
   review is close to free of information.
