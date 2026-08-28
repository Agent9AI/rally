# Demo

Two ways to see it work. The first needs nothing and takes a minute. The second
is the real thing.

---

## A. See it work right now (no setup, no email)

**1.** Open a terminal in the repo.

```bash
cd ~/rally
```

**2.** Check everything is wired.

```bash
make check
```

You should see both agents, two different model families, and both CLI binaries
found.

**3.** Give it a task.

```bash
./bin/rally --run "Write fizzbuzz.py and test_fizzbuzz.py that pass python3 -m unittest discover" --no-mail
```

**4.** Watch the turns alternate. Claude scopes a checklist, Antigravity
negotiates it, then they take turns working and checking each other.

**5.** Read the report it prints at the end, then look at what they actually
built:

```bash
ls runs/*/workspace/
```

That is the whole loop. Nothing is mocked.

---

## B. The real demo: email a task to your team's agent

### One-time setup (about two minutes)

**1.** Put the Resend key in your keychain.

```bash
security add-generic-password -U -s rally-resend -a rally -w '<your resend key>'
```

**2.** Get your ingest URL.

```bash
echo "https://rally-ingress.terry-c87.workers.dev/inbound/$(cat /tmp/rally-ingest-token)"
```

**3.** In the Resend dashboard, route inbound mail for
`rally@updates.agent9.dev` to that URL.

**4.** Confirm it is live.

```bash
make check
curl -s https://rally-ingress.terry-c87.workers.dev/health
```

### The demo itself

**1.** Start the runner. Leave it running.

```bash
make serve
```

**2.** From any email client, on any device, send a task to:

```
rally@updates.agent9.dev
```

Subject can be anything. Put the task in the body, for example:

> Add a --version flag to the CLI and a test that proves it prints the version
> from package.json.

**3.** Watch the terminal. Within a minute you will see the commission arrive,
then the turns alternate between the two agents.

**4.** Check your inbox. You get **one** email back when the run finishes or
gets stuck. It says what was asked, what was built, what was verified and by
which agent, what to look at first, and what is still open.

**5.** To steer a run that is already going, just reply to its thread.

- Reply `STOP` to halt it.
- Reply anything else to inject guidance into the next turn.

---

## What to point at during the demo

**The checklist is negotiated before any work starts.** Turn 0 is one agent
proposing what "done" means. Turn 1 is the other one arguing with it. That is
deliberate: disagreeing about scope up front is cheap, and disagreeing at the end
is not.

**Neither agent can approve its own work.** Watch the `owner` and `verified_by`
columns in the final summary. They never match. This is enforced by the runner,
not requested in a prompt, so a model that tries it gets reverted and told.

```bash
python3 -c "
import json,glob
s=json.load(open(sorted(glob.glob('runs/*/state.json'))[-1]))
for i in s['checklist']:
    print('%-4s %-20s owner=%-7s verified_by=%s' % (i['id'],i['state'],i['owner'],i['verified_by']))
"
```

**The two agents are different models on purpose.** A model reviewing its own
work shares its own blind spots. Startup refuses to run two agents from the same
family, because that failure looks completely healthy in the logs.

**It stops instead of spinning.** Show the limits in
[RUNBOOK.md](RUNBOOK.md#limits-and-why-they-are-not-optional). A run that is not
converging halts after four turns with no progress and tells you so, rather than
two agents agreeing politely with each other until the budget is gone.
