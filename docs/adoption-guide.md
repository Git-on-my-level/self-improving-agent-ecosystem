# Adoption Guide

## 1. Choose one bounded loop

Start with a task that has a repeatable mechanical evaluator. Avoid combining
monitoring, product changes, deployment, and policy mutation in the first loop.

Good first candidates:

- performance optimization with a benchmark and correctness tests;
- adding independently testable tools from a demand queue;
- monitoring-check improvement with healthy/failure fixtures;
- coverage growth where each accepted item is independently validated.

## 2. Write the evaluator before the agent

Create historical and adversarial fixtures. Score the current baseline. If the
metric can be increased without delivering the intended outcome, redesign it
before scheduling candidates.

## 3. Declare authority

Fill in `ecosystem.json` and `policy.json`. Give the first loop only observe,
candidate, and local-test capabilities. Add publication or deployment only
after evidence supports it.

## 4. Initialize AVO-lite

Use an existing reviewed installation or the explicit pinned installer in this
repository. Read the installed revision's README and `SKILL.md`. Configure an
agent adapter, scorer, and adversarial verifier. Keep publication and
deployment outside the AVO kernel.

## 5. Add promotion as a separate state machine

Use exact commits and artifacts, stable role worktrees, idempotency keys,
provider reconciliation, explicit supersession, and human review. Preserve a
known-good rollback target.

## 6. Close the outcome loop

Name the motivating signal before promotion. After deployment, verify both the
serving revision and the signal. A merged PR or green deployment is not proof
that the change worked.

## 7. Add external health

Export loop freshness and lineage gaps. Put a deadman outside the loop's host
and delivery path. Test failure, observer blindness, stalled scheduling, and
rollback—not just the happy path.

## 8. Earn additional authority

Expand one capability at a time after a review window. Good evidence includes:

- replayable evaluation;
- several valid accepts and honest rejects;
- no shared-checkout or state-reconciliation failures;
- complete promotion lineage;
- successful canary and rollback drills;
- bounded cost and understandable alerts.

## Exit criteria for a reusable ecosystem

- Another agent can reconstruct why the current best won.
- Every accepted candidate maps to its promoted and deployed artifact.
- The evaluator rejects all known gaming fixtures.
- The system distinguishes healthy, no-action, failed, stale, and unobserved.
- A provider or model outage does not disable deterministic sensing.
- A real rollback drill has succeeded.
- A clean machine can reconstruct configuration from reviewed, non-secret
  sources without copying runtime state.
