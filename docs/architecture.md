# Architecture

## The unit of design is a claim

A self-improving ecosystem does not merely run agents repeatedly. It makes and
tests claims:

> Given evidence E and base revision B, candidate C is correct, improves metric
> M under evaluator V, was promoted as artifact P, and changed outcome O.

Every important component exists to make that claim falsifiable and
reconstructable.

## Planes

### 1. Evidence

Sensors collect observations without deciding what to change. Deterministic
collection should run without an LLM. Every read classifies its result as:

- `observed_ok`
- `observed_problem`
- `observer_failed`
- `unobserved`

An empty result is never enough to distinguish those states.

### 2. Experiment

The experiment kernel creates a candidate outside canonical state. The builder
may iterate internally, but it cannot accept its own work. A scorer first
decides correctness, then emits a quality objective. A would-be winner is
independently challenged before it enters accepted lineage.

AVO-lite is the reference kernel. It intentionally does not own sensors,
publication, deployment, credentials, or production policy.

### 3. Promotion

Promotion consumes an accepted candidate and advances it through explicit
states. It derives truth from exact Git, CI, artifact, and deployment
identities—not from a local filename, branch name, prompt assertion, or
successful scheduler exit.

### 4. Outcome

The outcome evaluator checks the reason for the change. Tests prove that the
candidate is internally valid; outcome evidence proves that the change solved
the motivating problem without unacceptable regressions.

### 5. Governance

A machine-enforced authority policy defines who may observe, build, publish,
deploy, roll back, spend, change identity, or alter the policy itself. Prompts
may be stricter than policy but cannot expand it.

### 6. External health

Another process or host observes scheduler freshness, evaluator validity,
promotion reconciliation, sensor lag, lineage gaps, delivery health, and
resource budgets. The deadman must not share every failure domain with the
system it watches.

## Role separation

| Role | Reads | Writes | Must not own |
| --- | --- | --- | --- |
| Observer | Production/evidence sources | Evidence events | Product repo or deploy credentials |
| Builder | Base revision, evidence, pins | Disposable candidate | Canonical branch or production |
| Scorer | Candidate and fixtures | Score artifacts | Acceptance state |
| Verifier | Candidate, score, controls | Verification verdict | Candidate edits |
| Publisher | Accepted revision, policy | Branch/PR metadata | Deployment credentials |
| Deployer | Approved immutable artifact | Runtime placement | Evaluator or acceptance state |
| Outcome evaluator | Deployment identity, telemetry | Outcome event | Product mutation |
| Deadman | Exported health | Alerts/status | Same host and delivery-only path |

Small installations may colocate processes, but they should keep separate
identities, capabilities, state directories, and auditable transitions.

## State principles

1. Events are append-only; derived state is rebuildable.
2. Every attempt has a stable ID and idempotency key.
3. Every artifact is content-addressed or carries a digest.
4. Multiple candidates and explicit supersession are normal.
5. Role checkouts are stable; candidates use disposable worktrees.
6. External systems are reconciled before mutation.
7. Interrupted transitions are either resumable or safely repeatable.
8. A scheduler exit code reflects the domain result, not merely that it wrote
   an error into a ledger.

## Reference lifecycle

```text
observed
  -> proposed | no_action
  -> built
  -> scored
  -> rejected | verification_failed | accepted
  -> awaiting_approval
  -> promoted
  -> deployed
  -> evaluating
  -> resolved | regressed | quarantined | rolled_back | superseded
```

Infrastructure failures are events alongside domain transitions. They do not
masquerade as candidate rejection or successful no-action.
