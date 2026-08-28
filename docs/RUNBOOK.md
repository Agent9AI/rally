# Runbook

Operating Rally. For what it is, read [FOUNDING.md](FOUNDING.md); for how it is
built, [SPEC.md](SPEC.md).

## Addresses

| Address | Purpose |
|---|---|
| `rally@updates.agent9.dev` | **Commission a run.** Email a task here. |
| `claude@updates.agent9.dev` | Agent A mailbox (agent-to-agent leg) |
| `agy@updates.agent9.dev` | Agent B mailbox (agent-to-agent leg) |

Only verified owners may commission. Authority comes from the sender address,
never from anything the body claims. A stranger's mail is fetched, classified,
ignored and acked.

## One-time setup

**1. Credentials into the keychain.** Nothing secret lives in the repo.

```bash
# Resend: sends agent mail and the human report, and fetches inbound bodies
security add-generic-password -U -s rally-resend -a rally -w '<resend key>'

# Ingress: bearer token the runner uses to collect from the Worker
# (already stored if you deployed the Worker from this machine)
security find-generic-password -s rally-poll-token -w
```

**2. Point Resend's inbound webhook at the Worker.** In the Resend dashboard,
route `rally@updates.agent9.dev` to:

```
https://rally-ingress.terry-c87.workers.dev/inbound/<INGEST_TOKEN>
```

The token is the path, so an unauthenticated POST gets a 404 rather than a hint
that the endpoint exists.

**3. Preflight.**

```bash
make check
```

It reports model pins, both CLI binaries, credentials, and the limits. It exits
non-zero if either binary is missing or the two agents share a model family.

## Daily use

```bash
make serve                    # poll the Worker, run whatever arrives
./bin/rally --serve --once    # a single pass, for testing
```

Then email a task to `rally@updates.agent9.dev`. You get one report back when the
run finishes or halts.

## Running without email

```bash
make dry                                      # stub agents, no tokens spent
./bin/rally --run "task" --workdir /path --no-mail
./bin/rally --resume r-20260828-abc123 --no-mail
```

## Intervening in a live run

Reply into the run's thread. The subject tag routes it.

- `STOP` halts the run. The runner refuses the next turn, so the halt does not
  need the agents to cooperate.
- Anything else is injected as guidance into the next turn, ahead of the
  counterpart's envelope. It does not consume a turn.

From the shell:

```bash
./bin/rally --resume <run_id> --note "STOP"
./bin/rally --resume <run_id> --note "skip c3, the API is down"
```

## Reading what happened

```
runs/<run_id>/state.json    authoritative state: checklist, evidence, violations
runs/<run_id>/workspace/    the agents' git tree, one commit per turn
```

`state.json` carries three fields worth knowing:

- `violations` — changes the runner rejected. A model trying to mark its own
  work done shows up here.
- `containment` — turns where an agent wrote outside its workspace.
- `report` — the message the human received.

## When it goes wrong

**"execution asymmetry" at startup.** One agent has `exec_flags` and the other
does not. The agent that cannot run commands can only read source, so its
verification is weaker than the `done` it records. Give both agents the flag or
neither.

**"same-family pair" at startup.** The Antigravity CLI also serves Claude models.
Two agents from one family means the system is reviewing itself. Pin `agy` to a
`gemini-*` model.

**Run halts with `no_progress`.** Four turns passed with no item changing state.
Usually the checklist has an item neither agent can verify. Read the last
narrative and either split the item or `STOP`.

**Run halts with `disputed`.** The agents disagreed three times on one item.
Both positions are in the report. Decide, then re-commission with the decision
stated in the task.

**Nothing arrives when you email.** Check in order:

```bash
curl -s https://rally-ingress.terry-c87.workers.dev/health
curl -s -H "Authorization: Bearer $(security find-generic-password -s rally-poll-token -w)" \
     https://rally-ingress.terry-c87.workers.dev/pending
```

Health failing means the Worker; empty pending with mail sent means Resend's
route is not pointing at the ingest URL.

## Limits, and why they are not optional

The sending quota is shared with unrelated projects, so a runaway loop here is
someone else's outage. Every ceiling is enforced by the runner, before the API
call, and fails closed: if the ledger cannot be read, nothing sends.

| Guard | Default |
|---|---|
| Turns per run | 24 |
| Turns with no state change | 4, then halt |
| Rejections of one item | 2, then disputed |
| Sends per run | 60 |
| Sends per hour, all runs | 30 |
| Sends per day, all runs | 200 |
| Turn wall clock | 25 min |
