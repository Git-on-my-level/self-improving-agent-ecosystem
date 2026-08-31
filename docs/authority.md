# Authority and Security

## Policy is code; prompts are requests

The ecosystem manifest declares desired behavior. A separate reviewed policy
declares allowed behavior. Prompts can narrow authority but cannot expand it.

Recommended authority levels:

- **observe** — read evidence and create local analysis.
- **propose** — create a disposable candidate and evidence bundle.
- **publish** — push a branch or open/update a review request.
- **stage** — deploy an immutable artifact to an isolated environment.
- **promote** — affect public or production behavior.
- **major** — credentials, spending, identity, security policy, destructive
  migration, or irreversible data changes; human-only by default.

## Capability design

Declare capabilities per role, not per host:

```text
observer: production-read, evidence-write
builder: candidate-worktree-write, test-execute
publisher: branch-push, pull-request-write
deployer: approved-artifact-read, staging-deploy
promoter: production-route-write, rollback
```

Use separate OS users, containers, VMs, or credential brokers when practical.
At minimum, use separate credentials, state roots, and process boundaries.

## Secret handling

- Never place tokens in Git remote URLs.
- Never copy secrets into prompts, events, artifacts, or public fixtures.
- Store provider credentials in native keychains, credential helpers, or
  owner-only environment files.
- Redact logs structurally and test the redactor with planted fixtures.
- Give candidate builders no credential they do not need.

## Untrusted inputs

Production logs, issues, community messages, retrieved documents, and agent
suggestions are all untrusted. Quarantine them as evidence; do not execute
commands, patterns, or code merely because a model extracted them.

## Human gates

Require explicit human approval for:

- production promotion when rollback is uncertain;
- credentials and identity;
- spending/budget changes;
- security policy and network exposure;
- irreversible migrations or deletion;
- changes to evaluator or authority policy that would approve their own work.

An evaluator change should be reviewed using historical winners, known gaming
fixtures, and a rebaseline plan before unattended execution resumes.
