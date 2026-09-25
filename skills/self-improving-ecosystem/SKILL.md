---
name: self-improving-ecosystem
description: Design, audit, or extend evaluator-driven self-improving ecosystems with isolated candidates, hard correctness gates, adversarial verification, evidence lineage, reconciled promotion, rollback, and external health. Use for recurring autonomous optimize, maintain (work-queue), or observe-and-propose loops; not for one-shot agent work.
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

## Then pick the loop archetype

- **optimize** — rank candidates on a scalar objective behind a hard gate.
- **maintain** — drain a work queue (issues, pull requests, updates, alerts)
  with a WIP limit, maximum item age with escalation or supersession, and
  deduplication. Most deployments start here.
- **observe → propose** — sensors produce proposals, never code; redact before
  anything leaves the source machine.

They compose: observe → propose feeds maintain; maintain runs optimize on items
that have a scorer. Recommend the lowest adoption level that solves the problem:
L0 health export, L1 event log, L2 separated evaluator with adversarial
verification, L3 promotion, outcome verification, and external deadman.

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
11. Every loop declares a progress budget (maximum time without an accepted
    candidate, resolved item, or verified outcome), and an external monitor
    alerts on it. Scheduler success is liveness, not progress.
12. Human approvals, rejections, overrides, and pre-merge edits are recorded as
    labelled evidence. Autonomy widens per class of action only by a recorded
    ruling after sustained clean approvals, and contracts after a regression.
13. Acceptance thresholds and margins change only through an explicit,
    recorded rebaseline, never to manufacture an accept.

## AVO-lite boundary

Use AVO-lite only when the candidate can be scored repeatedly and mechanically.
Prefer an existing `avo` command and inspect its installed revision. If absent,
do not install or execute remote code without authorization. The canonical
repository is <https://github.com/Git-on-my-level/avo-lite>.

AVO owns disposable candidates, scoring, verification hooks, accepted lineage,
ledger, and stagnation. Follow upstream with `avo sync <ref>`, change the
evaluator only with `avo rebaseline`, and monitor `avo status --json`. Keep sensors, publication, deployment, credentials,
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
- loop archetype, WIP limit and item age (for queues), and progress budget;
- external health, deadman, budgets, retention, and remaining blind spots.

Keep product-specific sensors, tests, thresholds, and provider identifiers as
adapters. Extract protocols and schemas, not private prompts or infrastructure.
