# AVO-lite Integration

AVO-lite is the reference experiment kernel, not the whole ecosystem. It owns
candidate worktrees, scoring, verification hooks, accepted lineage, ledger,
memory, and stagnation. Sensors, publication, deployment, production
credentials, outcome evaluation, and rollback remain outside the kernel.

Canonical repository: <https://github.com/Git-on-my-level/avo-lite>

## Pinned source installer

`scripts/install-avo-lite.sh` clones source at an explicit revision and does
not execute it, add it to `PATH`, or modify a project. The default revision is
recorded in the script. To install another reviewed commit:

```bash
./scripts/install-avo-lite.sh \
  --prefix .tools/avo-lite \
  --ref FULL_REVIEWED_COMMIT
```

After installation:

1. Inspect that revision's `README.md`, `SKILL.md`, scorer contract, and agent
   adapter guidance.
2. Verify Git status and the exact commit.
3. Add its `scripts/` directory to `PATH` explicitly for the intended job.
4. Keep agent CLI routing in an adapter; AVO remains acceptance authority.
5. Do not give AVO implicit permission to publish, deploy, or alter credentials.

## Pin updates

An update to the default pin should include:

- old and new exact commits;
- upstream diff review;
- AVO unit tests;
- one isolated reject, accept, verifier-failure, interruption, and recovery
  fixture;
- compatibility evidence for the ecosystem adapter;
- rollback to the old source checkout.

Avoid a moving `main` checkout in unattended scheduler configuration.

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
