---
name: self-improving-ecosystem
description: Design, audit, or extend evaluator-driven self-improving ecosystems with isolated candidates, hard correctness gates, adversarial verification, evidence lineage, reconciled promotion, rollback, and external health. Use for recurring autonomous improvement loops; not for one-shot agent work without a repeatable evaluator.
---

# Self-Improving Ecosystem

Treat the ecosystem as a chain of falsifiable claims, not a recurring prompt.
The implementation must be able to reconstruct why a candidate was accepted,
which artifact was promoted and deployed, and whether the motivating outcome
improved.

## First classify the work

- **Audit:** inspect the live loop, evidence, evaluator, lineage, promotion,
  authorities, and external health. Do not mutate unless explicitly asked.
- **Design:** write the evaluator and authority boundaries before the agent or
  scheduler.
- **Implement:** preserve evidence, use isolated role worktrees, add fixtures,
  and make state migration append-only and rollback-ready.
- **Operate:** reconcile provider truth first; do not infer success from a
  scheduler exit, local branch, filename, or agent claim.

For architecture and state-machine decisions, read
[references/design.md](references/design.md). For scorer or verifier work, read
[references/evaluator-review.md](references/evaluator-review.md). For live
implementation and migration, read
[references/implementation-checklist.md](references/implementation-checklist.md).

## Non-negotiable invariants

1. Correctness is a hard gate and cannot be traded for objective value.
2. Candidate work occurs outside canonical state; only accepted work enters
   accepted lineage.
3. Every accept, reject, verification verdict, invalidation, supersession, and
   infrastructure error remains in durable evidence.
4. A would-be winner is independently challenged before trust.
5. Promotion uses exact remote Git, artifact, deployment, and outcome truth.
6. Multiple candidates and explicit supersession are supported.
7. Deterministic sensing and reconciliation do not require an LLM.
8. Silence is classified as healthy, no-action, failed, stale, or unobserved.
9. Observer, builder, evaluator, publisher, and deployer authority are separate.
10. Production-capable loops have a known-good rollback target and external
    deadman.

## AVO-lite boundary

Use AVO-lite only when the candidate can be scored repeatedly and mechanically.
Prefer an existing `avo` command and inspect its installed revision. If absent,
do not install or execute remote code without authorization. The canonical
repository is <https://github.com/Git-on-my-level/avo-lite>.

AVO owns disposable candidates, scoring, verification hooks, accepted lineage,
ledger, and stagnation. Keep sensors, publication, deployment, credentials,
production policy, and rollback outside the kernel.

## Required output for designs and audits

State clearly:

- system boundary and intended outcome;
- roles, identities, capabilities, and human gates;
- evidence provenance and absence classifications;
- correctness gate, objective, counterfactual, sample requirements, and known
  gaming routes;
- candidate and accepted lineage;
- promotion, canary, outcome, quarantine, and rollback states;
- idempotency, locks, stable worktrees, supersession, and reconciliation;
- external health, deadman, budgets, retention, and remaining blind spots.

Keep product-specific sensors, tests, thresholds, and provider identifiers as
adapters. Extract protocols and schemas, not private prompts or infrastructure.
