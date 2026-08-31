# Implementation Checklist

## Before mutation

- Inspect repository/worktree status, running jobs, locks, state, and recent
  evidence.
- Resolve the exact files, identities, and scheduler authority.
- Back up non-Git state with timestamp, mode, and ownership preserved.
- Define rollback and stopping conditions.
- Avoid triggering an autonomous run merely to test controller code.

## Implementation

- Add historical and adversarial fixtures first.
- Use atomic writes or transactions for state.
- Preserve append-only evidence and add migration/repair events.
- Use stable role worktrees and disposable candidates.
- Add idempotency keys and exact provider reconciliation.
- Represent multiple candidates and supersession.
- Keep generated findings separate from durable controller lessons and compose
  their agent-facing view atomically.
- Make domain failure visible in process status.
- Keep deterministic sensors and deadmen outside LLM turns.
- Separate secrets and role credentials.

## Verification

- Replay the current best and known bad candidates.
- Prove reward-hacking fixtures are rejected.
- Run concurrent or interrupted-transition tests.
- Dry-run promotion against exact remote refs.
- Verify accepted, promoted, deployed, and serving revisions.
- Exercise no-action, observer-failed, stale, quarantined, and rollback states.
- Confirm external health sees a missed heartbeat.
- Check that logs, diffs, fixtures, and Git remotes contain no secrets.

## Handoff

Report exact files and commits, state migrations, tests, scheduler reloads,
rollback steps, live next-run evidence, remaining authority concentration, and
unclosed failure classes. Do not equate a loaded timer with a healthy loop.
