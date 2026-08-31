# Promotion and Rollback

Acceptance, publication, deployment, and successful outcome are different
facts. The control plane must not collapse them into one `success` bit.

## Recommended states

```text
accepted
  -> awaiting_approval
  -> publishing
  -> published
  -> staging
  -> l0_passed
  -> canary
  -> l1_passed
  -> soaking
  -> promoted
  -> outcome_verified
```

Failure states include:

- `publication_failed`
- `staging_failed`
- `quarantined`
- `degraded_active`
- `rollback_pending`
- `rolled_back`
- `outcome_regressed`
- `superseded`

A failed L1 check must not produce generic process success while leaving the
candidate active. If automatic rollback is unsafe, enter `degraded_active` or
`quarantined`, exit nonzero, preserve the previous artifact, and escalate.

## Promotion truth

Verify all of:

1. Exact accepted candidate or content digest.
2. Exact remote commit or PR lineage.
3. Required reviews and CI conclusions.
4. Immutable built artifact digest.
5. Exact staging/canary deployment identity.
6. L0 and L1 evidence.
7. Serving production revision.
8. Motivating signal after deployment.

Do not use local branch names, filenames, scheduler status, or agent prose as
authority for any of these facts.

## Reconciliation and idempotency

Before an external write:

- query provider truth;
- look up the stable idempotency key;
- detect merged, closed, superseded, or already-deployed states;
- compare exact revisions or content hashes;
- append the reconciliation result;
- perform at most the missing transition.

Multiple accepted candidates are normal. A newer cumulative candidate should
explicitly supersede an older one so reviewers, gardeners, and pollers stop
churning obsolete work.

## Rollback contract

Every production-capable ecosystem must name:

- previous known-good artifact;
- state that cannot be regenerated and its backup;
- rollback authority;
- rollback command or provider operation;
- verification after rollback;
- conditions that forbid automatic rollback;
- a recurring rollback drill.

The deployment controller should retain the previous color/artifact until the
new candidate finishes its soak and outcome evaluation.
