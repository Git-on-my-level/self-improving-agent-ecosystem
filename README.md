# Self-Improving Ecosystems

A public reference kit for building evaluator-driven systems that can observe,
propose, test, promote, and learn without confusing activity with improvement.

This repository is intentionally not an out-of-the-box autonomous agent. It
contains the contracts, schemas, skills, examples, and small deterministic
helpers that future agents would otherwise have to rediscover:

- correctness and quality are separate;
- candidates are isolated from canonical state;
- a would-be winner is adversarially verified;
- every attempt retains exact evidence and lineage;
- promotion follows external Git and deployment truth;
- post-deploy outcomes close the loop;
- silence is classified, never assumed healthy;
- authority, budgets, rollback, and human gates are explicit.

## Architecture in one picture

```text
Sensors -> Evidence -> Candidate -> Hard Gate -> Quality Objective
                                      |                |
                                      |         Adversarial Verify
                                      |                |
                                      +-------> Accept / Reject
                                                       |
                              Approve -> Promote -> Deploy -> Evaluate
                                                       |
                                  Resolve / Supersede / Quarantine / Roll back

External health observes every transition and can distinguish healthy,
no-action, failed, stale, and unobserved.
```

The reference architecture has four deliberately separate planes:

1. **Experiment kernel** — AVO-lite provides disposable worktrees, hard scoring,
   verification hooks, accepted-only lineage, an append-only ledger, and
   stagnation handling.
2. **Workload control plane** — domain-owned sensors, evaluators, promotion,
   deployment, outcome checks, and rollback.
3. **Authority and distribution** — reviewed policy and portable agent skills;
   no prompt silently grants deployment or credential authority.
4. **External observation** — another process or host checks loop freshness,
   lineage gaps, observer blindness, and delivery health.

## Start here

- [Architecture](docs/architecture.md)
- [Evaluator contract](docs/evaluator-contract.md)
- [Event and state model](docs/event-model.md)
- [Promotion and rollback](docs/promotion.md)
- [Operations and observability](docs/operations.md)
- [Authority and security](docs/authority.md)
- [Adoption guide](docs/adoption-guide.md)
- [Failure patterns](docs/failure-patterns.md)
- [AVO-lite integration](docs/avo-lite.md)

Agents can use the included
[`self-improving-ecosystem`](skills/self-improving-ecosystem/SKILL.md) skill.

## Quick start

Requirements: Git, Python 3.10+, and a POSIX shell. The validation helpers use
only the Python standard library.

```bash
git clone https://github.com/Git-on-my-level/self-improving-agent-ecosystem.git
cd self-improving-agent-ecosystem

# Optional: install the known AVO-lite revision without executing it.
./scripts/install-avo-lite.sh --prefix .tools/avo-lite

# Create a small local scaffold from the public templates.
./scripts/init-ecosystem.sh ../my-ecosystem my-ecosystem

# Validate its manifest, policy, and example event stream.
python3 scripts/validate.py ../my-ecosystem
```

The generated scaffold fails closed: validation reports the owner, backup,
deadman, and command stubs until they are deliberately configured.

The AVO-lite installer defaults to a reviewed commit rather than a moving
branch. Inspect the checkout and its current documentation before running it.
The canonical upstream is <https://github.com/Git-on-my-level/avo-lite>.

## What belongs in the baseline

Portable:

- role and capability declarations;
- evaluator and verifier contracts;
- event vocabulary and lineage fields;
- worktree, locking, idempotency, supersession, and reconciliation rules;
- promotion, canary, quarantine, and rollback states;
- loop-health metrics and external deadman requirements;
- runbooks, review checklists, and agent skills.

Keep as adapters:

- product-specific telemetry queries;
- private endpoints and credentials;
- business thresholds and domain fixtures;
- deployment-provider identifiers;
- model prompts containing proprietary context;
- application-specific test commands.

## Non-goals

- A universal objective function.
- A fleet-wide write agent.
- An excuse to give an LLM production credentials.
- A replacement for domain tests, incident response, or human approval.
- A claim that worktree isolation is a security sandbox.

## Repository map

```text
docs/       Human architecture and operating guides
schemas/    JSON Schemas for manifests, policy, and events
templates/  Copyable ecosystem skeleton
examples/   Small evaluator and verifier examples
scripts/    Zero-dependency installer, scaffold, and validator
skills/     Portable agent skill and focused references
tests/      Contract tests and reward-hacking regression fixtures
```

## License

MIT. See [LICENSE](LICENSE).
