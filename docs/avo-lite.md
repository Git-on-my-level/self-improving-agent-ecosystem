# AVO-lite Integration

AVO-lite is the reference experiment kernel, not the whole ecosystem. It owns
candidate worktrees, scoring, verification hooks, accepted lineage, ledger,
memory, and stagnation. Sensors, publication, deployment, production
credentials, outcome evaluation, and rollback remain outside the kernel.

Canonical repository: <https://github.com/Git-on-my-level/avo-lite>

## Source installer

`scripts/install-avo-lite.sh` clones the latest default branch and does not
execute it, add it to `PATH`, or modify a project. It prints the exact commit it
installed. To pin a reviewed commit or tag instead:

```bash
./scripts/install-avo-lite.sh \
  --prefix .tools/avo-lite \
  --ref FULL_REVIEWED_COMMIT
```

After installation:

1. Inspect that revision's `README.md`, `SKILL.md`, scorer contract, and agent
   adapter guidance.
2. Record the exact commit you will run; unattended jobs should run a known
   commit, whichever way it was chosen.
3. Add its `scripts/` directory to `PATH` explicitly for the intended job.
4. Keep agent CLI routing in an adapter; AVO remains acceptance authority.
5. Do not give AVO implicit permission to publish, deploy, or alter credentials.

To upgrade, install into a new prefix, review the upstream diff, run AVO's
tests and one isolated reject/accept/interruption fixture, then switch the job
to the new path. Keep the old checkout until the new one has run cleanly.

## Kernel features the ecosystem relies on

- **`avo sync <ref>`** — follow a moving upstream. The kernel merges under its
  own task lock, records the merge in lineage, and aborts cleanly on conflict.
  Do not merge upstream in a wrapper behind the kernel's back.
- **Evaluator revision and `avo rebaseline`** — the scorer, verifier, margin,
  and acceptance rule are fingerprinted. A change blocks attempts until an
  explicit rebaseline rescores the current best and records why. See
  [goalposts move only explicitly](evaluator-contract.md#goalposts-move-only-explicitly).
- **`avo status --json`** — the health export. Feed `last_accept_at`, active run
  age, and evaluator drift to an external monitor; alert on progress, not on
  the scheduler succeeding.

## Event bridge

`scripts/avo-to-event.py` converts terminal AVO ledger records into the ecosystem event contract without making the ecosystem a second source of truth for AVO state. Supply the evaluator revision explicitly:

```bash
python3 scripts/avo-to-event.py \
  --ledger /path/to/project/.avo/ledger.jsonl \
  --ecosystem ./ecosystem.json \
  --loop improve \
  --evaluator-revision eval-2026-09-04 \
  --output events.jsonl
```

AVO remains authoritative for attempts and accepted commits. Ecosystem events add promotion, deployment, outcome, and authority state. Replaying the same AVO terminal record yields the same idempotency key.
