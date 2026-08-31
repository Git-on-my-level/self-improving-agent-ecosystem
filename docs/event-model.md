# Event and State Model

Use one append-only event vocabulary and derive dashboards, current state, and
promotion queues from it. Avoid unrelated single-slot JSON files that each
claim to be current truth.

## Required identity

Every event should contain:

- globally unique `event_id`;
- `ecosystem` and `loop`;
- `candidate_id` when the event belongs to a change;
- stable `idempotency_key` for retryable effects;
- UTC `occurred_at`;
- actor role and implementation identity;
- base, candidate, accepted, promoted, deployed, and evaluator revisions when
  applicable;
- evidence and artifact digests;
- result status and machine-readable reason;
- authority decision and approver where applicable.

See [`schemas/event.schema.json`](../schemas/event.schema.json).

## Event vocabulary

Evidence:

- `observation_recorded`
- `observer_failed`
- `no_action`

Experiment:

- `candidate_started`
- `candidate_built`
- `candidate_scored`
- `candidate_rejected`
- `verification_failed`
- `candidate_accepted`
- `evaluation_invalidated`
- `candidate_superseded`

Promotion:

- `approval_requested`
- `approval_granted`
- `promotion_started`
- `promotion_reconciled`
- `promotion_failed`
- `artifact_promoted`

Runtime outcome:

- `deployment_observed`
- `outcome_evaluated`
- `incident_resolved`
- `regression_detected`
- `candidate_quarantined`
- `rollback_started`
- `rollback_completed`

Operations:

- `loop_stalled`
- `loop_resumed`
- `budget_exhausted`
- `deadman_missed`
- `state_repaired`

## Canonical versus derived state

Canonical:

- immutable event records;
- exact run artifacts;
- Git commits and immutable deployment artifacts;
- reviewed policy and manifests.

Derived:

- current best;
- open candidates;
- latest deployment;
- KPI summaries;
- dashboards and queues.

Derived state may be cached for speed but must be rebuildable. A repair tool
should compare the cache with events and external provider truth, append a
repair event, and update the cache atomically.

Generated current findings and durable controller lessons are different kinds
of memory. Store them separately and compose the agent-facing view atomically;
never let a periodic sensor refresh truncate publisher, verifier, or incident
lessons.

## Concurrency

- Use atomic file replacement or a transactional store.
- Hold one task lock for state transitions, not merely candidate generation.
- Give each role a stable checkout/worktree.
- Never use "file exists in current checkout" as publication evidence.
- Reconcile exact remote refs and deployment identities before retrying.
- Store multiple in-flight candidates; do not overwrite the previous one.
- Record `supersedes` edges explicitly.

SQLite with an immutable events table is a practical local authority when
multiple writers exist. JSONL remains useful as an exported audit format, but
plain concurrent appends and independent state files need locking and repair.
