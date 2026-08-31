# Agent Guide

This repository is public. Never add private hostnames, credentials, internal
prompts, user data, production payloads, or proprietary thresholds.

Before changing behavior, read the relevant document under `docs/`. Evaluator
changes require historical and adversarial fixtures. Promotion changes require
exact-ref reconciliation and interrupted-transition coverage. Authority changes
require explicit human review and may not approve themselves.

Use `make check` before committing. Keep AVO-lite as an external pinned source;
do not vendor its implementation into this repository.
