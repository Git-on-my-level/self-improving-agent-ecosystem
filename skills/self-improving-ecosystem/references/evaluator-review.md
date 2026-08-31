# Evaluator Review

## Hard gate

Require tests, invariants, scope, protected paths, evidence freshness,
completeness, minimum samples, policy compliance, and evaluator integrity.
Incorrect candidates have no winning objective.

When a candidate adds tests, run those tests against the parent and require
them to fail there.

## Objective

Measure incremental attributable outcome against a baseline or control. Avoid
cumulative repository size, raw activity, artifact counts, or a denominator
the candidate can shrink.

Require:

- observation window;
- treatment and control;
- fixed opportunity counts;
- attribution completeness;
- authenticated and eligible observation identities;
- minimum samples and uncertainty;
- novelty versus current best.

## Adversarial verification

For a would-be winner, try:

- parent/control reproduction;
- alternate environment or cold start;
- mutation and boundary cases;
- semantic emptiness and activity inflation;
- unsigned or ineligible actors impersonating counted identities;
- denominator manipulation;
- stale, missing, duplicated, or truncated evidence;
- evaluator/fixture modification;
- untracked or protected-path escapes;
- competing causal explanations.

Known reward-hacking incidents become permanent regression fixtures.

## Invalid historical best

Do not rewrite the ledger. Preserve evidence, append an invalidation event,
name the evaluator defect and affected candidates, and rebaseline from the last
demonstrably valid candidate or freshly evaluated safe revision.

Pause unattended acceptance until historical gaming fixtures fail closed.
