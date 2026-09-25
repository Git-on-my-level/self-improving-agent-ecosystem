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

## Upstream merge wedged recovery

A wrapper merged upstream into the task branch before each attempt. After an
interrupted run, recovery saw a HEAD it did not expect and refused to continue
on every later fire, while the scheduler kept reporting success.

Remedy: the kernel owns upstream sync under its own lock; recovery accepts
advancement made only of merge commits along the first parent; a refusal is a
loud stall, not a quiet exit.

## Recovery that never ran

A repair job took a lock with a zero timeout. A sibling job held the lock on
every fire, so the repair lost the race each time and exited silently.

Remedy: bounded wait, record "busy" as an event, and alert when the repair
itself has not run within its budget.

## Work hosted inside a restartable gateway

Long attempts ran as child processes of a chat or agent gateway. Every gateway
restart or upgrade killed whatever attempt was in flight.

Remedy: the operating-system scheduler runs attempts; gateways only notify.

## Single-slot deadlock

A builder paused while its own pull request was open. One unreviewed pull
request stopped the loop for weeks, and nothing reported it as stuck.

Remedy: maximum item age, escalation past the deadline, and supersession, so
no single item can block the queue; a progress budget on the loop.

## Model-summarized silence

A model read a script's failure output and reported "nothing to report". The
failure was never delivered.

Remedy: parse outcomes deterministically and route failures without a model in
the path. Models narrate; they never decide whether a failure is delivered.

## Silent coverage cap

A sensor paginated to a fixed item limit while the queue was much larger. A
large fraction of items was never processed, and every run looked complete.

Remedy: page to completion and export coverage (processed / total); treat
truncation as `observed_problem`, not success.

## Stale-cache digest

A daily digest counted open items from a local cache and reported several times
the real number. Readers acted on the digest, not on the provider.

Remedy: reconcile against provider truth before reporting, and state the
source and freshness of every count.
