# Design Reference

## Start from the claim

Write the claim the loop must prove:

```text
Given evidence E and base B, candidate C is correct, improves objective M
under evaluator V, was promoted as artifact P, and changed outcome O.
```

If any noun lacks an exact identifier or evidence source, the loop is not ready
for unattended authority.

## Separate planes

- Evidence: deterministic observation and explicit observer failure.
- Experiment: isolated candidate, hard score, adversarial verification.
- Promotion: exact Git/artifact/deployment reconciliation.
- Outcome: verify the motivating signal after the serving revision changes.
- Governance: machine-enforced role capabilities and human-only domains.
- Health: external freshness, lineage, budget, and deadman observation.

## State vocabulary

Use typed append-only events such as:

```text
observed -> proposed -> built -> scored -> accepted/rejected
-> awaiting_approval -> promoted -> deployed -> evaluated
-> resolved/regressed/quarantined/rolled_back/superseded
```

Derived current state must be rebuildable. Do not let several single-slot JSON
files become competing authorities.

## Role workspaces

- Give optimizer, publisher, gardener/reviewer, and serving/main operations
  stable separate checkouts or worktrees.
- Give each candidate a disposable worktree.
- Use exact remote refs and content digests for publication truth.
- Hold a lock across each state transition and update derived state atomically.
- Reconcile merged, closed, deployed, or superseded work before retrying.

## Authority ladder

- observe: evidence only;
- propose: candidate and local evaluation;
- publish: branch or review request;
- stage: isolated deployment;
- promote: public/production routing;
- major: credentials, identity, spending, security policy, destructive or
  irreversible changes; human-only by default.

Prompts may narrow these levels but cannot expand them.
