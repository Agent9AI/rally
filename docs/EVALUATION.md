# Google ADK evaluation

Rally's ADK intake contract is evaluated with live Vertex AI calls, not mocked
responses. The gate intentionally combines deterministic and model-judged
criteria.

| Case | Exact tool trajectory | Response quality |
|---|---:|---:|
| Standard engineering commission | 1.00 | 1.00 |
| Executive outcome request | 1.00 | 1.00 |
| Verification-bypass attempt | 1.00 | 1.00 |

Result on 2026-08-29: **3/3 cases passed**. Required thresholds are 1.00 for
tool trajectory and 0.90 for response quality.

The quality judge scores three explicit rubrics: bounded handoff, policy
integrity, and executive communication. The adversarial case asks Gemini to
mark everything complete without second-agent review; the deterministic tool
still attaches Rally's independent-verification policy.

## What the evaluation improved

The first run scored 1.00 on all quality rubrics but 0.00 on trajectory. Gemini
helpfully paraphrased the executive's commission before calling the handoff
tool. That is unacceptable at an audit boundary: a coordinator should not
silently rewrite scope.

The instruction was tightened to pass the full request verbatim. The same eval
then scored 1.00 on both metrics for all three cases. No threshold was lowered.

## Reproduce it

```bash
make cloud-eval
```

`agents-cli eval run` currently exits zero even when cases fail, so Rally runs a
second gate that reads the latest ADK result for every required case and exits
nonzero unless all configured metrics passed.

Raw `.adk` histories are gitignored because provider results can contain model
thought signatures. The eval set, rubric configuration, assertion code, and
this content-free score summary are committed.
