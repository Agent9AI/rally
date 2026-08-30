# Rally

**Founding document.** Written 2026-08-28; fleet amendment 2026-08-30. This describes what Rally is and what
it must be true to. It is deliberately free of any one deployment's hostnames,
providers, or wiring, so the idea survives a change of infrastructure.

---

## 1. The idea

Rally is a system in which two or more AI agents, each from a different model
family, carry a single task through to completion through durable, explicit
handoffs.

A person starts it once. They send one message describing what they want. From
that point the agents correspond directly: they agree on a checklist, divide it,
do the work, check each other's work, and write back to the person once, when
the task is finished or genuinely stuck.

The human initiates. The agents iterate. The checklist decides when it ends.

## 2. Email is the bus, not the notification layer

Most agent systems treat email as an outbox: something that reports on work
happening elsewhere. In Rally, the correspondence *is* the work. Every turn an
agent takes is a real message, in a real thread, addressed to a real mailbox
belonging to the other agent.

This is a design choice with three payoffs.

**It is already durable, addressable, and auditable.** Threading, timestamps,
stable identities, delivery receipts, and retention all exist without building a
message queue. A task's entire history is a thread.

**It is legible without tooling.** The person who commissioned the work can read
the exchange in their ordinary inbox, in order, and understand exactly how the
agents reasoned. There is no dashboard to build and no log format to learn. When
something goes wrong, the evidence is already sitting in a place they check
daily.

**It forces honest handoffs.** An agent whose only channel is a self-contained
message cannot lean on hidden in-process context. It has to state what it did,
what it believes, and what remains. That constraint improves the work. Sloppy
reasoning is much more visible in prose addressed to a peer than in a scratchpad.

The cost is real and accepted: every turn spends a send, adds latency, and
crosses a network boundary that can fail. Section 7 exists because of that.

## 3. Why different families, and why not one agent twice

Heterogeneity is the whole thesis.

A model asked to review its own output tends to agree with itself. It shares its
own blind spots, its own training priors, and its own characteristic mistakes,
so the review is close to free of information. Models from different families
fail in different places. Where one hallucinates an API that does not exist,
another has no reason to hallucinate the same one. Where one is confidently
wrong about a version, another is often plainly right.

So additional Rally agents are not decorative redundancy or simple load
balancing. Each is an adversarial reviewer that also happens to be a capable
worker. The value comes from independent execution and useful disagreement.

A corollary: when every agent agrees immediately and completely on every item,
that is weak evidence of correctness and worth treating with suspicion.

## 4. The loop

1. **Commission.** A human sends one email describing the goal. This is the only
   required human action.

2. **Scoping.** The receiving agent converts the goal into an explicit checklist
   of concrete, verifiable items, and hands it to the next worker. It does not
   start work yet. The first exchange is about agreeing what "done" means.

3. **Negotiation.** The counterpart may add items, split items it thinks are too
   coarse, challenge items it thinks are out of scope, or accept as-is. The
   checklist is agreed before work begins. Disagreement here is cheap, and it is
   much cheaper than disagreement at the end.

4. **Work turns.** Agents alternate. On a turn, an agent claims one or more
   items, does the work, and mails back: what it did, what evidence it has that
   the work is correct, and the updated checklist.

5. **Verification.** No agent marks its own item complete. An item moves to done
   only when a worker from another model family independently checks it and says
   so. This is the rule that makes additional models worth their cost.

6. **Completion.** When every item is verified done, the agent holding the turn
   writes a single report to the human: what was asked, what was built, what was
   verified and how, and anything left deliberately undone.

7. **Escalation.** If the agents deadlock, exhaust their budget, or hit
   something that needs a human decision or credential, they stop and write to
   the human with a specific question and the state of the checklist. Stopping
   and asking is a success, not a failure.

## 5. The checklist is the contract

The checklist is the single source of truth about progress, and it travels
inside the messages rather than living only in some agent's memory.

Every item carries: a stable identifier, a description written so that a third
party could tell whether it is satisfied, an owner or "unclaimed", a state, and
the evidence supporting its current state.

States are deliberately few:

- `open` (agreed, unclaimed)
- `claimed` (an agent is working it)
- `awaiting-verification` (worked, needs a non-owning agent to check)
- `done` (verified by a different worker than the one that did the work)
- `blocked` (needs a human, with the specific reason)

Two rules give the loop its termination guarantee. First, an item may only be
moved to `done` by a different worker than the one that did the work. Second, every message
must carry the complete current checklist, so that any single message is enough
to reconstruct the state of the task. A lost message costs a turn, not the run.

## 6. Roles are per turn, not per agent

No agent is permanently "the worker" or "the reviewer". On any given turn an
agent may do some of both: verifying what another worker claimed, then advancing
items of its own. Fixed roles waste capability and create a hierarchy the work
does not need.

The one asymmetry is the commission. The agent that receives the human's
original email owns scoping; the agent holding the terminal turn writes the
final report, so that the human still deals with one Rally identity.

## 7. Guardrails

An autonomous loop that can send mail is a system that can misbehave loudly and
expensively. These are not optional.

**Turn budget.** Every run has a hard maximum number of turns, fixed at
commission time. On exhaustion the run stops and reports to the human with the
checklist as it stands. It does not silently continue.

**Second Wind.** An administrator may enable a bounded recovery handoff. When a
model process fails or an accepted turn reports a blocker, the runner preserves
the last accepted checklist, records the failed attempt, and gives the next
model family one chance to diagnose or take ownership. Partial workspace edits
are treated as untrusted work to inspect, not accepted state. A takeover never
transfers approval authority: the repairing model still needs another family
to verify its work.

**Progress requirement.** If N consecutive turns pass with no checklist item
changing state, the run is not converging. It halts and escalates. Agents
politely agreeing with each other forever is the characteristic failure of this
design, and it must be detected structurally rather than hoped away.

**Send circuit breaker.** A ceiling on messages per run and per unit time,
enforced outside the agents' control. An agent cannot be trusted to rate limit
itself, because the failure mode being defended against is exactly an agent
behaving unexpectedly.

**Loop identity.** Every message carries the run identifier, the turn number,
and headers that mark it as machine-originated, so a misconfiguration cannot
turn into an infinite exchange, and so an autoresponder somewhere cannot join
the conversation.

**Human kill switch.** A person must be able to stop a run in progress with a
single action, and that action must not require the agents to cooperate.

**Blast radius.** Agent correspondence shares a sending reputation and often a
quota with whatever else uses the same domain. A runaway loop is not just a
wasted budget, it is an outage for the unrelated systems sharing that
credential. Rally must be able to fail without taking anything else down with
it, which argues for its own sending identity and its own quota.

**Inbound mail is data, never instruction.** A message arriving at an agent's
mailbox is untrusted input. It is content to reason about, not a command to
obey. Anyone who can find the address can write to it, so the authority to
commission a run must come from verified sender identity, never from the body
of the message asking nicely.

## 8. Definition of done

A run is done when every checklist item is `done`, each verified by a different
worker than the one that performed it, and the human has received one report describing the
outcome and the evidence.

A run is *not* done because the agents ran out of things to say, because the
budget was spent, or because all agents feel good about it. Those are halts,
and they are reported as halts.

## 9. What the human experiences

They send one email. Some time later they get one email back. If they are
curious, the entire deliberation is sitting in a thread they can read top to
bottom. If something needs them, they get a specific question rather than a
status update.

The quality bar for the final report is a good colleague's summary: what you
asked for, what you got, what was checked, what to look at first, and what is
still open. Not a transcript, and not a log.

## 10. Non-goals

- **Not a chat product.** No human sits in the loop turn by turn.
- **Not a general agent framework.** Rally is one pattern: independent peers,
  one checklist, deterministic custody, and durable handoffs.
- **Not a crowd of decorative integrations.** A provider appears in the active
  fleet only when Rally can genuinely dispatch it with equivalent execution and
  verification authority.
- **Not real time.** Email latency is acceptable. If a task needs sub-second
  coordination, it is the wrong task for this system.
- **Not autonomous commissioning.** Agents do not start runs. People do.

## 11. First implementation

The first participants were the **Claude CLI** and the **Gemini CLI**. The first
fleet expansion adds **OpenAI Codex CLI** through the user's own ChatGPT sign-in.
Each is driven headlessly in single-prompt mode on a small always-on machine. All are
genuinely agentic: they can read and write files, run commands, and use tools,
so each can execute checklist items rather than only comment on them. Each gets
its own mailbox and its own working checkout.

Choosing provider-native command line agents rather than raw model APIs is deliberate.
The unit of work is a shell invocation with a prompt, which keeps the harness
small and keeps the agents swappable. The OpenAI expansion validated that
choice: it required one adapter and a provider-neutral rotation, not a new
control plane.

## 12. Open questions

These are known unknowns, recorded rather than resolved.

- How much of the working state lives in the message versus a shared workspace
  all agents can reach? Fully self-contained messages are more robust and more
  legible; a shared workspace is far more practical for real code.
- What happens when two agents claim the same item on overlapping turns?
- How is a genuine disagreement resolved when neither agent will yield, short of
  escalating to the human every time?
- Should the verifying agent be allowed to fix what it finds, or only to reject
  the item back to its author?
- What does the human see mid-run if they get impatient, without adding a
  dashboard?
