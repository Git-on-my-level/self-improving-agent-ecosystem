# Adopting the loop standard: the lite profile

The full reference kit (`ecosystem.json` + roles, identities, planes, promotion
stages) is for systems you build from scratch. Most real loops are an existing
cron that already does useful work. The **lite profile** makes one of those
provable in one file and one wrapper — about fifteen lines — without adopting
roles, identities, or promotion machinery.

## The contract

Every loop proves its effect with three things:

1. **One receipt per tick.** The last line of the tick's stdout is:

   ```
   LOOP_RECEIPT {"loop":"<id>","run":"<iso8601>","outcome":"acted|measured|no_op|infra_error",
   "effects":[{"ref":"<url>","metric_before":<n|null>,"metric_after":<n|null>}],
   "open_items":<n>,"oldest_open_days":<n>,"preflight":{"<bin>":true}}
   ```

   - `acted` — this tick changed something (merged, deployed, applied) and
     says so in `effects`.
   - `measured` — this tick re-measured the goal metric and put the numbers
     in `effects` (`metric_before`/`metric_after`).
   - `no_op` — nothing to do this tick. Healthy, but **not progress**.
   - `infra_error` — the loop could not do its job (missing binary, missing
     credential, unreadable source). A missing or invalid receipt counts as
     `infra_error`, never ok. Exit 0 is never evidence of a healthy tick.

   Optional on any receipt: `"metrics": {"<name>": <number>}`. Watch loops
   with a `health` SLO are judged on the named metric, not on `effects`.

   Optional on any receipt: `"invalidates_effects":[{"run":"<iso8601>","ref":"<url>"}]`.
   A later row uses this to drop earlier effects from counting, matched on
   `loop` + `run` + `ref`. The historical row stays as written. Dropped
   effects no longer count toward `effects_7d` or `last_effect_at`. A
   successful correction-only row (not `infra_error`, not a measurement) is
   not a health sample. An `infra_error` or a failing measurement that also
   carries `invalidates_effects` is still the sample.

2. **A durable ledger.** `~/.hermes/state/loops/<loop-id>/receipts.jsonl` (or
   the owning repo) — never an ephemeral scratch volume.

3. **A progress budget, or a health SLO.** A loop that claims to move a
   metric is **stalled** when it goes `progress_budget_seconds` without a
   receipt whose outcome is `acted` or `measured` and whose `effects` is
   nonempty. Liveness (the cron fired) is not progress (the metric moved).
   A watch that only samples a signal sets `health` instead
   (`metric`, `op`, `threshold`, `max_age_seconds`) and may set
   `progress_budget_seconds` to null. Each receipt then carries
   `"metrics": {"<metric>": <number>}`. Stalled means the latest sample
   missed the threshold, is `infra_error`, omitted the metric, or is older
   than `max_age_seconds`. A fresh passing sample is not stalled, even with
   `effects: []`. A failing or missing sample must not read healthy. The
   sample is the last row in append order. A timestamp more than 300s in
   the future is invalid. Metric values and the threshold are finite
   numbers; an unparseable latest row fails closed instead of revealing
   an older pass. A successful correction-only row does not become that
   sample.

The manifest carries the declarations; `scripts/loop` enforces the mechanics.

## The manifest (lite)

```json
{
  "$schema": "https://raw.githubusercontent.com/Git-on-my-level/self-improving-agent-ecosystem/main/schemas/loop-manifest.schema.json",
  "schema_version": 1,
  "loop": "example-watch",
  "host": "workstation-1",
  "archetype": "maintain",
  "goal_metric": "median time from alert to resolved",
  "authority": "pr",
  "ledger": "~/.hermes/state/loops/example-watch/receipts.jsonl",
  "effect_probe": "re-run the alert-age query after each merge; deltas go in effects",
  "finisher": "issue closed or superseded; else escalate to the owner queue",
  "progress_budget_seconds": 604800,
  "stop_rule": "2 stalled escalations with no accepted change -> pause and ask the owner",
  "requires": ["git"]
}
```

Fields: `archetype` (`optimize | maintain | observe_propose`), `goal_metric`,
`authority` (`propose | pr | merge | deploy`), `ledger` (durable path),
`effect_probe`, `finisher`, `progress_budget_seconds`, `stop_rule`,
`requires` (binaries such as `gh`, `gcloud`). The full `ecosystem.json` roles
and identities stay optional; add them only when a loop earns autonomy.

## The wrapper

```sh
loop tick ~/.hermes/loops/example-watch.json -- /path/to/existing-tick.sh
```

The runner: prints the PATH it saw, fails loudly (exit 6) when a `requires`
binary is missing — before the loop can silently no-op — runs the command,
captures the `LOOP_RECEIPT` line, appends it to the ledger, computes
`last_effect_at` and stall state, prints `LOOP_STALLED ...` once on the
transition into stalled, and exits nonzero on `infra_error` so the scheduler's
failure delivery fires.

Collectors (dashboards, fleet sync) read state without ticking:

```sh
loop status ~/.hermes/loops/*.json
# {"loop":"example-watch","manifest":"...","archetype":"maintain",
#  "last_run":"...","last_outcome":"no_op","last_effect_at":"...",
#  "effects_7d":0,"fail_streak":0,"stalled":false}
```

## Picking an archetype

| Archetype | Unit of work | Progress is | Concrete examples |
| --- | --- | --- | --- |
| **optimize** | a candidate change | an accepted candidate that beat the baseline on the scored objective | [AVO-lite](avo-lite.md) tasks: a perf hill-climb against a latency scorer; a battery-drain hill-climb against per-build drain readouts; a storage-reclaim loop scored on bytes reclaimed with a safety gate |
| **maintain** | a queue item | an item merged/resolved/superseded, outcome verified | a prod-error fixer that opens and merges fix PRs; a PR completion monitor that lands review feedback; a dependency-update queue |
| **observe_propose** | a signal | a proposal accepted into a queue, or a finding resolved | cost-autoresearch that files cost-cut proposals; an anomaly monitor that files incidents; a canary watch that files failures |

When in doubt: a backlog with a review process → maintain; a trusted scorer →
optimize; signals without owners → observe_propose (and cap the proposal
queue).

The archetypes compose: observe_propose feeds a maintain queue; a maintain
loop can run optimize on any item that has a scorer.

## Lessons baked into the standard

These come from post-mortems of real loops (2026-10-13 fleet review):

- **Merged is not improved.** A merge is an output; the goal metric moving is
  the outcome. Every loop needs an `effect_probe` that re-measures
  `goal_metric` after a change ships, and receipts that carry the delta. A
  "verified" fix that recurs must be visible in the ledger.
- **Exit 0 is not progress.** Silent success is the failure mode that survives
  longest. Missing receipt = `infra_error`, nonzero exit, failure delivery.
  `no_op` is honest but never counts toward the progress budget.
- **PATH drift silently kills crons.** Cron runners inherit a reduced PATH;
  `gh`/`gcloud` in `/opt/homebrew/bin` vanish and ticks "succeed" while doing
  nothing. The preflight checks `requires` on the PATH it saw and prints that
  PATH every tick.
- **Durable ledgers.** A ledger on erasable scratch erases the evidence that
  would have shown the loop was stalling. Ledgers live under
  `~/.hermes/state/loops/` or in a repo.
- **Score the goal, not the work.** An optimize loop whose score counts
  attempts, PRs, or messages optimizes activity. Score the goal metric; the
  receipt's `effects` are the score.
- **Propose-only queues need cap + expiry.** An observe_propose loop without a
  proposal cap and an expiry rule grows an unread queue forever; conversion
  silently goes to zero. Encode the cap in `stop_rule` (or `notes`) and in the
  loop itself.

## Where the manifests live

Per-host manifests belong in the private per-host config registry (for the
fleet that uses hostctl-config: `loops/<host>/<loop-id>.json`), because they
name private hosts, job ids, and internal paths. This public repo holds the
schema, the template, the runner, and generic examples only.
