# Operations and Observability

## Deterministic fast loop, slower judgment loop

Run deterministic sensors, scorers, reconciliation, heartbeats, and deployment
checks directly under the operating-system scheduler. Invoke an LLM only when
the task requires judgment or synthesis. A provider outage should not prevent
the system from noticing that the provider or scheduler is down.

## Progress, not liveness

A scheduler that fires on time proves only that it fired. Every loop declares a
**progress budget**: the maximum time it may go without a meaningful
transition. Meaningful means the loop's own unit of progress, for example:

- an accepted candidate;
- a merged, resolved, or explicitly superseded work item;
- a verified outcome;
- an honest, reasoned `no_action` when the loop has nothing to do.

Attempts, retries, scheduler exits, and log lines do not count. Declare the
budget per loop (`progress_budget_seconds` in `ecosystem.json`) and have a
monitor outside the loop alert when it is exceeded. A loop that is running but
stuck is a failure, not a quiet day.

`scripts/progress-check.py` is a minimal reference monitor: it reads the event
log and the manifest and lists loops whose last meaningful transition is older
than their budget (exit 0 healthy, 1 stale, 2 error). Run it from a different
process or host than the loop it checks.

## Required health export

For each loop, expose:

- last scheduled attempt;
- last completed attempt;
- last valid evaluation;
- last accepted candidate;
- last meaningful progress and the declared progress budget;
- current action and status;
- consecutive errors and stall count;
- active lock age;
- observer freshness and completeness;
- accepted, published, deployed, and serving revisions;
- lineage/promotion gap;
- latest outcome verdict;
- budget use and remaining allowance;
- delivery/deadman freshness.

Counters must be derived from durable event identities. Do not reread an entire
history and increment an in-process Prometheus counter on every scrape.

## Alert semantics

- Silent success is acceptable only with an external heartbeat.
- Alert on state transitions rather than every poll.
- Distinguish liveness from successful work.
- Distinguish observer failure from zero findings.
- Preserve explicit open and resolved incident state.
- Deduplicate with durable state outside `/tmp`.
- Put the deadman on a different host or provider and, when possible, a
  different delivery channel.

## Retention

Define limits for:

- raw observations;
- signatures and incident memory;
- run artifacts;
- candidate worktrees;
- model output;
- logs and database growth;
- rejected evidence and accepted lineage.

Retention must not erase the evidence needed to reproduce why a candidate won.
Repeated signatures need an explicit expiry or incident lifecycle; permanent
"seen once" memory can hide genuine recurrence.

## Operational review

At least daily, a meta-auditor should compare agent claims with actual Git,
CI, artifact, service, deployment, and monitoring state. It may repair
mechanical state inconsistencies within declared authority. Semantic,
security, identity, spending, and irreversible changes go to the appropriate
human gate.

At least periodically:

- replay the current best evaluation;
- test reward-hacking fixtures;
- reconcile every accepted-but-unpromoted candidate;
- exercise rollback in a non-production environment;
- verify external deadman delivery;
- review model cost, failure rate, and stagnation;
- confirm backups can actually restore non-regenerable state.
