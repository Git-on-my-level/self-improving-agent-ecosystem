# Failure Patterns

These anonymized patterns were observed in real self-improving systems. They
are included because a future agent should not have to rediscover them.

## Correct loop, wrong objective

A live engagement loop rewarded responders divided by a minimum denominator of
one. Nonsubstantive activity could therefore score higher than substantive
work. The verifier covered explicit spam relaxation but not semantic emptiness
or denominator manipulation.

Remedy: fail closed on incomplete attribution, require substantive treatment,
measure incremental outcomes, add adversarial historical fixtures, invalidate
the compromised best append-only, and rebaseline.

## Accepted locally, absent remotely

A promoter decided a generated tool was already published because the file
existed in a shared checkout. Another scheduler had left that checkout on a
feature branch; the file never reached remote main.

Remedy: stable promotion worktree, exact remote-ref/content verification,
provider reconciliation, and explicit pending-promotion state.

## Deployment failed but scheduler succeeded

A staged candidate passed a shallow smoke test, became active, then failed a
deeper flow. The script wrote failure state but exited successfully and left
traffic on the new color.

Remedy: explicit `degraded_active` or `quarantined` state, nonzero domain exit,
preserved previous color, one-shot alerting, and tested rollback policy.

## Strong experiment kernel, weak controller

Candidates were correctly isolated, scored, and verified, but publisher,
gardener, and improver branch-switched one checkout and stored promotion in a
single mutable JSON object. Merged and superseded work became stale.

Remedy: separate role worktrees, typed multi-candidate event state, explicit
supersession, and reconciliation from external Git truth.

## Scheduler health mistaken for knowledge freshness

A sync task ran successfully hundreds of times while the source material it
copied had not changed for weeks.

Remedy: publish source revision, semantic-update timestamp, coverage, and stale
section findings. Scheduler completion proves only execution.

## Metrics inflate on every scrape

An exporter reread historical records and incremented Prometheus counters each
time it was scraped. The counter measured scrape frequency, not model usage.

Remedy: export durable cumulative values as gauges or persist event IDs and
increment counters once per new event.

## Deadman shares the failure domain

The monitor, scheduler, agent provider, delivery gateway, and deadman all ran
on one host. Total host or gateway failure silenced every reporter.

Remedy: external deadman on a different host/provider and preferably a second
delivery path.
