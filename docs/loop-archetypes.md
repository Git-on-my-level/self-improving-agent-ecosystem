# Loop Archetypes

Every loop uses the same planes: evidence, experiment, promotion, outcome,
governance, and external health. What differs is the unit of work and what
counts as progress. Pick the archetype that matches the work you already have.

## Optimize

Rank candidates against a scalar objective behind a hard correctness gate.

```text
evidence -> candidate -> hard gate -> objective -> verify -> accept/reject
```

- Needs a repeatable, mechanical scorer and a baseline.
- Accepted lineage is a ratchet: a candidate wins only by beating the current
  best under the same evaluator revision.
- Progress: an accepted candidate.
- Reference kernel: [AVO-lite](avo-lite.md).

Use it when "better" is a number you trust, such as latency, cost, pass rate,
or coverage under fixed fixtures.

## Maintain

Drain a work queue: issues, pull requests, dependency updates, alerts.

```text
intake/triage -> work item -> candidate -> review -> publish
  -> human or policy merge -> outcome check
```

- **WIP limit.** Cap open items per loop so review capacity, not generation
  speed, sets the pace.
- **Maximum item age.** Every item has a deadline; past it, escalate or
  supersede. A loop must never wait indefinitely behind one item.
- **Deduplication.** Key items by a stable identity so the same signal does not
  become several work items or several candidates.
- Progress: an item merged, resolved, or explicitly superseded; an outcome
  verified.

Most real deployments start here. The queue already exists, correctness is the
domain's own tests and review, and the payoff is visible without inventing an
objective.

## Observe → propose

Turn signals into proposals, never code.

```text
sensors -> evidence -> finding -> proposal / issue
```

- Sensors include telemetry, usage traces, agent transcripts, and human
  decisions (approvals, rejections, overrides, edits).
- Output is a proposal or issue with evidence links, not a change.
- Redact before anything leaves the source machine; raw traces and transcripts
  stay local.
- Deduplicate against open proposals; a repeated signal updates the existing one.
- Progress: a proposal accepted into a queue, or a finding resolved.

Use it when you do not yet know what to fix, or when the loop may observe but
must not write.

## Choosing

| If you have… | Start with |
| --- | --- |
| A trusted scorer and fixtures | optimize |
| A backlog and a review process | maintain |
| Signals but no clear work items | observe → propose |
| None of these | observe → propose, locally, with no write authority |

## Composition

Archetypes compose rather than compete:

- observe → propose feeds a maintain queue;
- a maintain loop runs optimize on any item that has a scorer;
- human decisions recorded by maintain become evidence for observe → propose.

Each composed loop keeps its own progress budget, WIP limit, and authority. A
healthy upstream loop does not make a stalled downstream loop healthy.
