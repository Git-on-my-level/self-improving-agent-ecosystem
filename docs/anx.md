# Publishing loop receipts to Agent Nexus

Agent Nexus can compute loop health, a hill-climb chart, and recent effects
from run receipts. This repository stays the source of truth for the ledger.
`scripts/anx-publish.py` is an optional, dry-run-by-default adapter that turns
a ledger you already keep into `anx work receipt` commands, and a loop
manifest into `anx work cadence` plus an optional `anx work goal`.

It does not vendor AVO-lite or Agent Nexus, and it does not grant a loop any
new authority. Nothing is executed unless you pass `--apply`. The publisher
builds an argument list and never joins it into a shell command.

## Receipts

```bash
python3 scripts/anx-publish.py receipts \
  --card card:x \
  --input ledger.jsonl \
  --since 2026-01-01T00:00:00Z
```

That prints one JSON array per run. Every value-taking flag is one token,
`--flag=value`, so a summary or stop rule that looks like `--timeout=...` or
`--base-url=...` stays a value. The card ref is positional. A ref that starts
with `-` is rejected. A cron job that should actually publish
uses the same command with `--apply`:

```bash
python3 scripts/anx-publish.py receipts --card card:x --input ledger.jsonl --since <last> --apply
```

`<last>` is the previous watermark, in RFC3339. A row timestamp equal to
`--since` is included. Rows with no timestamp cannot be bounded, so they are
still sent; publishing them again is a no-op.

Other flags:

- `--goal-metric <name>` — AVO `objective` values, and a loop receipt's
  selected `metric_after` when that name is not already in `metrics`, are
  sent as `--metric <name>=<value>`. Names may contain spaces and may not
  contain `=`.
- `--goal-effect <ref>` — loop receipts only. The goal metric takes
  `metric_after` from the effect whose `ref` equals this value exactly, for
  example `metric:firestore.read_count.24h`. If that effect is absent, or its
  `metric_after` is not finite, that row does not set the goal metric. Without
  this flag, a row sets the goal metric only when exactly one effect has a
  finite `metric_after`. When several do, the goal metric stays unset and the
  process warns once on stderr, not once per row, to pass `--goal-effect`.
  Requires `--goal-metric`. An explicit `metrics` value for the goal name is
  kept. A `metric:<name>` effect whose name equals `--goal-metric` does not
  fill that key: it stays unset until selection succeeds.
- `--loop <id>` — loop id used in AVO run ids when the row does not carry one.
  The default segment is `avo`.
- `--workspace <alias>` — passed through as `anx --workspace <alias> ...`.
- `--anx <path>` — ANX binary. The default is `anx` on `PATH`.
- `--strict` — fail the run on an unknown action, an unknown event type, or a
  malformed JSON line. The default warns and continues.

`--input` may be repeated. Each non-empty line is one record. A loop receipt
line may be prefixed with `LOOP_RECEIPT `.

## Idempotency

`anx work receipt` is idempotent on `(card, run-id)`. Run ids come from the
row, not from the clock:

| Input | Run id |
| --- | --- |
| Ecosystem event | `event_id` |
| AVO ledger row | `avo:<loop>:<tick>:<diff_hash, else base or commit, else sha256>:<action>` |
| Loop receipt | `<loop>:<run>` |

Re-publishing the same ledger does not create a second receipt. `--since` only
limits what this process sends; it is not part of the id. The AVO id uses a
real `diff_hash` when the row has one, otherwise `base` or `commit`. A row
with none of those is identified by the sha256 of its canonical JSON, never
by `none`. The same row therefore keeps the same id across files and reruns.
Two different tick-zero baselines, or two patches that share a base, do not.
Editing a note does not change the id when a patch hash, base, or commit is
present. Summaries are the reason, note, or error text, collapsed to one line
and truncated to 280 characters. An accept that is not kept keeps the marker
`not kept: correct is false` inside that limit. Keep secrets out of those
fields: the publisher copies them and does not redact them.

Local evidence paths and `file:` URIs are not forwarded. A Windows
drive-relative path such as `c:private/report.json` is a local path, not a
typed ref. `http` and `https` URLs and typed refs such as `card:example` are.
A loop-receipt effect whose ref is `metric:<name>` is the exception: it is
recorded as a named metric, not forwarded as a ref.

## Event stream

Ecosystem events use [`schemas/event.schema.json`](../schemas/event.schema.json).
Terminal experiment results become experiment decisions. Finished promotion
and rollback are actions. Observations, evaluations, and governance records
are measurements. Observer blindness, a missed deadman, and an exhausted
budget are infrastructure errors.

| Event | Outcome | Decision |
| --- | --- | --- |
| `observation_recorded` | measured | — |
| `observer_failed` | infra_error | — |
| `no_action` | no_op | — |
| `candidate_started` | skipped | intermediate |
| `candidate_built` | skipped | intermediate |
| `candidate_scored` | skipped | intermediate |
| `candidate_rejected` | measured | rejected |
| `candidate_failed` | measured | rejected |
| `verification_failed` | measured | rejected |
| `candidate_accepted` | acted | kept |
| `evaluation_invalidated` | measured | — |
| `candidate_superseded` | no_op | — |
| `approval_requested` | skipped | intermediate |
| `approval_granted` | measured | — |
| `human_decision_recorded` | measured | rejected when the result is rejected or authority is denied; otherwise none |
| `autonomy_changed` | measured | — |
| `promotion_started` | skipped | intermediate |
| `promotion_reconciled` | measured | — |
| `promotion_failed` | infra_error | — |
| `artifact_promoted` | acted | kept |
| `deployment_observed` | measured | — |
| `outcome_evaluated` | measured | — |
| `incident_resolved` | acted | — |
| `regression_detected` | measured | — |
| `candidate_quarantined` | acted | — |
| `rollback_started` | skipped | intermediate |
| `rollback_completed` | acted | reverted |
| `loop_stalled` | infra_error | — |
| `loop_resumed` | no_op | — |
| `budget_exhausted` | infra_error | — |
| `deadman_missed` | infra_error | — |
| `state_repaired` | acted | — |

An intermediate event is not a run. It is published as `measured`, with no
experiment decision, only when it has a numeric `result.objective`, a
`candidate_id`, and no non-intermediate event for that same candidate in the
same invocation also has a numeric objective. That keeps a lone score on the
hill-climb chart. `--since` filters what is emitted; it does not change which
event carries the objective. An event type outside this table is skipped with
one warning (`file:line` and the type). `--strict` fails the run instead.

When a decision is present and `result.objective` is numeric, the receipt
includes `--score-after`. Events do not carry a delta, so they do not set
`--score-before`. A missing `candidate_id` becomes `event:<event_id>` so the
decision still has a candidate. `--started-at` is `occurred_at`.

`human_decision_recorded` is labelled evidence, so it is a measurement. An
approval is not `kept`: acceptance and promotion already record that.
Quarantine is an action without an experiment decision; `rollback_completed`
is the event that records `reverted`.

## AVO-lite ledger

AVO remains the authority for attempts and accepted commits. This publisher
reads the ledger; it does not import or vendor AVO-lite. Each line is
classified on its own, so a file may mix shapes.

The flat shape is the one `scripts/avo-to-event.py` already consumes:
`action`, `objective`, `delta`, `commit`, `note`, `tick`, `metrics`,
`correct`, plus `ts` and `diff_hash` when present. Newer ledgers use `event`
as the action name and nest `objective`, `delta`, `metrics`, and `correct`
under `score`. `base` names the attempt the same way `commit` does. The
summary is `reason`, then `note`.

| Action | Outcome | Decision | Scores |
| --- | --- | --- | --- |
| `baseline` | measured | — | goal metric = objective |
| `rebaseline` | measured | — | goal metric = objective; summary is the note. Resets the incumbent and carries no experiment decision |
| `accept` | acted | kept | score-before = objective − delta, score-after = objective, goal metric = objective. `correct: false` (flat or under `score`) is measured / rejected, and the summary keeps `not kept: correct is false` inside the 280-character limit |
| `reject` | measured | rejected | goal metric = objective |
| `error` | measured | rejected | same outcome as `candidate_failed`; goal metric when objective is present |
| `candidate` | skipped | lifecycle | published as measured only when it alone carries the attempt's objective |
| `verify` | skipped | lifecycle | same rule as `candidate` |
| `budget` | skipped | lifecycle | same rule as `candidate` |

`error` follows the event bridge (`error` → `candidate_failed` → measured /
rejected) so a ledger and the events derived from it publish the same
decision. Baseline rows are published even when `tick` is 0. The event bridge
skips them because they are not terminal candidate events. `rebaseline` is the
explicit rescore of the current best after an evaluator change. Other numeric
`metrics` are forwarded. When `--goal-metric` names a key that is also in
`metrics`, the objective wins. Without `--goal-metric` the outcome is still
published and a warning names the missing metric. At most 16 metrics are sent
on any receipt. The goal metric is first when it is present; other finite
numbers follow in name order. Booleans, strings, and non-finite values are
dropped, and metrics past the cap are dropped.

`candidate`, `verify`, and `budget` are lifecycle rows for one attempt, the
same kind of marker as `candidate_started` and `candidate_built`. A row is
published as `measured`, with no experiment decision, only when it has a
numeric `objective` and no `baseline`, `rebaseline`, `accept`, `reject`, or
`error` row for that same attempt also has a numeric objective. Grouping is
per loop: a lifecycle row in loop `one` is not hidden by a terminal row in
loop `two`, including when the rows come from different input files. A real
`diff_hash` is the attempt. Rows that use `event` share their `tick` inside
that loop, so a lifecycle line is tied to the baseline or reject on that
tick. Flat rows without a patch hash group by `base` or `commit`. Placeholder
hashes `baseline` and `rebaseline` are not attempt ids. A lifecycle row with
no attempt key stays skipped. A file whose first line is one of these rows is
still published.

Any other action (`reflect`, `preview`, `stalled`, `supervisor_error`, and
anything new) is skipped. Stderr gets one warning line with `file:line` and
the action, and the rest of the file is still published. A malformed JSON
line, and a JSON object that is not an event, an AVO row, or a loop receipt,
are skipped the same way. `--strict` restores fail-fast for all of these.
`--since` still bounds which warnings are printed: a mapped or unmapped row
older than the watermark is silent, including an unrecognized object whose
`ts`, `occurred_at`, or `run` is older than `--since`. A line that is not JSON
has no timestamp, so it always warns.

The experiment candidate is `base` or `commit`, otherwise the diff hash. The
run id prefers the diff hash when both are present, so two patches that share
a base stay distinct receipts. `--started-at` is `ts`. Ledger fields such as
`run_dir` are not forwarded.

## Loop receipts

Lite receipts already use the ANX outcome vocabulary. One JSON object per
line, optionally prefixed with `LOOP_RECEIPT `:

```json
{"loop":"example-watch","run":"2026-04-02T00:00:00Z","outcome":"acted","effects":[{"ref":"https://example.com/pr/1","metric_before":10,"metric_after":12}],"metrics":{"samples":12}}
```

`outcome` is copied. The summary is `error`, then `note`, then `reason`.
`http` and `https` effect refs, and other typed refs such as `card:example`,
are forwarded. A `metric:<name>` ref is not an effect ref: ANX accepts only
http(s) effect refs, so a finite `metric_after` is recorded as the receipt
metric `<name>` (for example `firestore.read_count.24h`). An explicit
`metrics` entry with that name wins; otherwise the first finite value is
kept. The goal metric name is reserved until selection succeeds, so an
effect whose name equals `--goal-metric` does not publish that metric when
the selected effect is absent or the row is ambiguous. An explicit `metrics`
value for the goal name is still kept. Those metrics use the same bounds and
order as any other receipt: at most 16, the goal metric first when it is
present, then the rest by name. `--goal-metric` is filled from effects only
by the `--goal-effect` rule above. `--started-at` is `run`. The run id keeps the original `run` string,
so `Z` and `+00:00` stay distinct ids even though they are the same instant.

## Manifest

```bash
python3 scripts/anx-publish.py manifest --card card:x --manifest loop.json
python3 scripts/anx-publish.py manifest --card card:x --manifest loop.json \
  --every 30m --goal-metric "latency ms" --direction down
```

`anx work cadence` takes:

- `--every` from a simple `cron`, or from `--every` when the cron field is a
  job id or prose. `--every` wins when both are present.
- `--budget` from `progress_budget_seconds`, using the largest of `d`, `h`,
  `m`, and `s` that divides the count. `7200` is `2h`. Null omits `--budget`
  (a health SLO instead of an effect budget).
- `--stop-rule` from the manifest.

Simple crons:

| Schedule | Duration |
| --- | --- |
| `* * * * *` | `1m` |
| `*/N * * * *` | `Nm` |
| `M * * * *` | `1h` |
| `M */N * * *` | `Nh` |
| `M H * * *` | `1d` |
| `M H * * D` | `7d` |
| `@hourly`, `@daily`, `@midnight`, `@weekly` | `1h`, `1d`, `1d`, `7d` |

Lists, ranges, day-of-month schedules, and `@monthly` are not a single
duration. Pass `--every`.

A goal is emitted only when both `--goal-metric` and `--direction` are set.
The manifest records the metric name and not the direction, so the direction
has to be chosen here. Optional `--target`, `--baseline`, and `--unit` are
forwarded. Host names and ledger paths are not sent. Manifest mode does not
read ledger effects. `--goal-effect` is a `receipts` flag: it selects which
effect's `metric_after` fills `--goal-metric` when publishing a loop receipt.
