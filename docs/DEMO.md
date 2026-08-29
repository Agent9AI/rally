# Demo runbook

For the recorded narrative, use [DEMO-SCRIPT.md](DEMO-SCRIPT.md). This page is
the operator checklist that makes that recording reliable.

## Preflight

```bash
cd ~/rally
make test
make cloud-test
make infra-check
./bin/rally --config config/rally.demo.json --check --smoke
```

When the Cloud service is deployed, preflight must report:

- Claude and Gemini from distinct model families
- both agent CLIs responding
- Resend credential present
- ingress Worker and queue reachable
- Google coordinator reachable on Gemini 3.7 with Firestore state

If the Google coordinator is enabled but unavailable, Rally fails closed before
agent work begins.

## Live email path

Start the runner and leave the terminal open:

```bash
./bin/rally --config config/rally.demo.json --serve
```

Email the task in [DEMO-SCRIPT.md](DEMO-SCRIPT.md) to:

```text
rally@updates.agent9.dev
```

The request can be in the subject or body; a descriptive subject plus the full
acceptance criteria in the body records best on camera. Rally replies to the
human address that commissioned the run. The configured CC is only a fallback
for CLI runs.

Expected thread:

```text
commission from human
  └─ Claude: scope and proposed checklist
      └─ AGY / Gemini: negotiation and first work
          └─ Claude: independent verification and work
              └─ AGY / Gemini: independent verification
                  └─ final executive report
```

Every turn is sent from its model address, carries the same run-tagged subject,
uses standard `In-Reply-To`/`References` headers, and includes a visible sender
watermark. The human is copied on agent-to-agent turns so the orchestration is
visible without opening a dashboard.

## Steering and stopping

Reply in the run thread. `STOP` prevents the next turn without asking either
model to cooperate. Any other reply becomes human guidance for the next turn.

From the shell:

```bash
./bin/rally --status <run_id>
./bin/rally --stop <run_id>
./bin/rally --retry <run_id>
```

## Evidence commands

Show owner and verifier separation:

```bash
python3 -c "import glob,json; s=json.load(open(sorted(glob.glob('runs/*/state.json'))[-1])); [print(i['id'], i['state'], 'owner='+str(i['owner']), 'verified_by='+str(i['verified_by'])) for i in s['checklist']]"
```

Show the real commits and workspace:

```bash
latest=$(ls -td runs/r-* | head -1)
git -C "$latest/workspace" log --oneline --decorate
git -C "$latest/workspace" status --short
```

Show the eval gate without exposing raw model records:

```bash
uv run --project cloud python cloud/scripts/assert_eval_gate.py
```

## No-network fallback

```bash
make dry
```

This exercises the actual state machine, reconciliation, alternation, and
guardrails with deterministic stub agents. State clearly that it is a fallback;
use the prerecorded live email thread and Cloud evidence for model execution.

## Recording discipline

- Rehearse once on the same network and warm both CLIs.
- Do not use Claude Code interactively while Rally consumes the same subscription.
- Do not edit Rally's source during a run; containment monitoring will report it.
- Keep Cloud Console pages pre-opened and sanitized.
- Capture the successful live run before recording the voiceover.
