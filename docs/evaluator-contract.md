# Evaluator Contract

The evaluator is the system's constitutional core. If the objective is wrong,
the loop can become more effective at producing harm.

## Two-stage contract

The scorer must return one structured result:

```json
{
  "correct": true,
  "objective": 12.4,
  "metrics": {
    "sample_size": 120,
    "coverage": 0.98,
    "stddev": 0.2
  },
  "evidence": ["results.json"],
  "note": "candidate improved the controlled measurement"
}
```

- `correct=false` means the candidate cannot win.
- Nonzero process exit means the evaluation could not be completed.
- An objective exists only after correctness passes.
- Higher is better; negate cost or latency when necessary.

## Correctness gate

Correctness should include every non-negotiable property that an objective
must never trade away:

- product tests and invariants;
- scope and protected-path restrictions;
- safety, privacy, and policy requirements;
- schema and migration compatibility;
- evidence freshness and completeness;
- minimum sample size;
- authenticated and eligible observation identities;
- absence of evaluator tampering;
- attribution requirements.

For code that adds tests, copy the tests onto the parent revision and require
them to fail there. This prevents a candidate from earning credit for tests
that do not distinguish its behavior.

## Quality objective

Measure the candidate's incremental outcome, not cumulative repository size,
raw activity, or a convenient proxy. Prefer:

```text
candidate treatment - contemporaneous baseline/control
```

over:

```text
all positive events observed after the candidate ran
```

The score should name:

- observation window;
- treatment and control populations;
- attribution completeness;
- sample size and uncertainty;
- missing or truncated evidence;
- novelty versus previously accepted behavior.

## Adversarial verifier

The verifier runs only for a would-be winner and should try to falsify the
claim. It must be independent from candidate editing and should test:

- parent/baseline counterfactual;
- cold-start or alternate-environment reproduction;
- boundary and mutation cases;
- competing explanations;
- missing, duplicated, stale, or truncated observations;
- denominator manipulation;
- activity inflation and semantic emptiness;
- unsigned actors impersonating an eligible identity;
- evaluator or fixture changes;
- protected-path and untracked-file escapes.

## Anti-Goodhart checklist

Before unattended ranking, answer yes to all:

- Does the objective correspond to an outcome users actually value?
- Can the candidate increase it without improving that outcome?
- Are numerator and denominator both candidate-controlled?
- Is a zero or minimum denominator artificially inflating the score?
- Can repeated or nonsubstantive actions count as progress?
- Can an unsigned or ineligible actor impersonate a counted participant?
- Is the measurement incremental rather than cumulative?
- Does missing attribution fail closed?
- Is there enough independent data to distinguish noise from improvement?
- Does the verifier contain a fixture for every known gaming route?
- Can a human understand why the current best beat the previous best?

If a historical winner is invalidated, preserve the original ledger. Append an
`evaluation_invalidated` event, state the evaluator defect, and rebaseline from
the last demonstrably valid candidate or a freshly evaluated safe revision.

## No-action is evidence

An honest no-action result should record why:

- no new problem;
- duplicate/superseded work;
- insufficient sample;
- observer unavailable;
- policy or budget gate;
- no candidate beat the current best.

This prevents an idle system from looking identical to a broken one.
