# Rally in four figures

Companion to [FOUNDING.md](FOUNDING.md) and [SPEC.md](SPEC.md).

## 1. Decisions travel in the message, artifacts live in git

```mermaid
flowchart TB
    subgraph CP["CONTROL PLANE - email"]
        direction LR
        M6["turn 6 · Agent A<br/>checklist + narrative"] -->|mails| M7["turn 7 · Agent B<br/>checklist + narrative"]
        M7 -->|mails| M8["turn 8 · Agent A<br/>checklist + narrative"]
    end
    subgraph DP["DATA PLANE - branch rally/run_id"]
        direction LR
        C6(("3d4fa99")) --- C7(("2181b94")) --- C8(("a7c0e12"))
    end
    M6 -.commit SHA.-> C6
    M7 -.commit SHA.-> C7
    M8 -.commit SHA.-> C8
```

One turn produces one message and one commit. The envelope carries the checklist,
the branch carries the work, and the SHA is the join. A lost message therefore
costs a turn rather than the run.

## 2. The human commissions once, then reads

```mermaid
flowchart LR
    H([human]) -->|commission| S["Scope<br/>agent A"]
    S -->|proposed checklist| N["Negotiate<br/>agent B"]
    N --> W["Work turns<br/>A and B alternate"]
    W -->|every item verified| R["Report<br/>to human"]
    W -->|budget · dispute · blocked| X["Halt<br/>reports state as it stands"]
    W -->|verify theirs, then advance yours| W
```

Agreement on what "done" means comes before any work. A halt is a reported
outcome, not a crash: stopping and asking counts as success.

## 3. An item cannot be marked done by the agent that did it

```mermaid
stateDiagram-v2
    [*] --> open
    open --> claimed: an agent claims it
    claimed --> awaiting_verification: worked and committed
    awaiting_verification --> done: verified by the OTHER agent
    awaiting_verification --> claimed: rejected, at most twice
    claimed --> blocked: needs a human
    awaiting_verification --> disputed: 3rd disagreement
    done --> [*]
    blocked --> [*]
    disputed --> [*]
```

Two bounds guarantee termination. On the second failure of the same item the
verifier may repair it, and ownership flips, so the original author must verify
the repair. Without the cap on that back edge the characteristic failure is not
a crash but an infinite, courteous exchange that burns budget.

## 4. Ingress is a swap point, not a rewrite

```mermaid
flowchart LR
    IN["inbound mail<br/>Resend"] --> IF
    subgraph IF["ingress interface - pick one"]
        A["edge queue<br/>durable, always on"]
        B["existing workflow host<br/>fastest to first run"]
    end
    IF --> RUN["runner<br/>turns, budget,<br/>authoritative state"]
    RUN --> CL["claude -p<br/>opus"]
    RUN --> AG["agy -p<br/>gemini pinned"]
```

The runner holds authoritative state; an envelope is evidence, never authority.
Because the runner does not know which ingress it got, the choice is reversible.

Model pinning belongs here rather than in config: the Antigravity CLI also serves
Claude models, so an unpinned run can quietly become one family reviewing itself
while everything still appears to work.
