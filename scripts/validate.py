#!/usr/bin/env python3
"""Zero-dependency structural and invariant validator for the reference kit."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import pathlib
import re
import sys
from typing import Any


NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
EVENT_TYPES = {
    "observation_recorded", "observer_failed", "no_action",
    "candidate_started", "candidate_built", "candidate_scored",
    "candidate_rejected", "verification_failed", "candidate_accepted",
    "evaluation_invalidated", "candidate_superseded", "approval_requested",
    "approval_granted", "promotion_started", "promotion_reconciled",
    "promotion_failed", "artifact_promoted", "deployment_observed",
    "outcome_evaluated", "incident_resolved", "regression_detected",
    "candidate_quarantined", "rollback_started", "rollback_completed",
    "loop_stalled", "loop_resumed", "budget_exhausted", "deadman_missed",
    "state_repaired",
}
CANDIDATE_EVENTS = {
    name for name in EVENT_TYPES
    if name.startswith("candidate_") or name in {
        "verification_failed", "evaluation_invalidated", "approval_requested",
        "approval_granted", "promotion_started", "promotion_reconciled",
        "promotion_failed", "artifact_promoted", "deployment_observed",
        "outcome_evaluated", "regression_detected", "rollback_started",
        "rollback_completed",
    }
}


class Findings:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def load_json(path: pathlib.Path, findings: Findings) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError:
        findings.error(f"missing {path.name}")
        return None
    except (OSError, json.JSONDecodeError) as exc:
        findings.error(f"cannot read {path.name}: {exc}")
        return None
    if not isinstance(value, dict):
        findings.error(f"{path.name} must contain one JSON object")
        return None
    return value


def has_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        return "replace-" in value or "declare-" in value or "__ECOSYSTEM_NAME__" in value
    if isinstance(value, dict):
        return any(has_placeholder(item) for item in value.values())
    if isinstance(value, list):
        return any(has_placeholder(item) for item in value)
    return False


def validate_manifest(data: dict[str, Any], findings: Findings, allow_placeholders: bool) -> None:
    if data.get("schema_version") != 1:
        findings.error("ecosystem.json schema_version must be 1")
    name = data.get("name")
    if name == "__ECOSYSTEM_NAME__" and allow_placeholders:
        findings.warn("ecosystem.json still contains template name")
    elif not isinstance(name, str) or not NAME_RE.fullmatch(name):
        findings.error("ecosystem.json name must be lowercase kebab-case")

    roles = data.get("roles")
    if not isinstance(roles, dict) or len(roles) < 3:
        findings.error("ecosystem.json must declare at least three roles")
        roles = {}
    identities: dict[str, str] = {}
    roots: dict[str, str] = {}
    for role, spec in roles.items():
        if not isinstance(spec, dict):
            findings.error(f"role {role} must be an object")
            continue
        capabilities = spec.get("capabilities")
        if not isinstance(capabilities, list) or not capabilities:
            findings.error(f"role {role} must declare capabilities")
        identity = spec.get("identity")
        state_root = spec.get("state_root")
        if not isinstance(identity, str) or not identity:
            findings.error(f"role {role} must declare identity")
        elif identity in identities:
            findings.warn(f"roles {identities[identity]} and {role} share identity {identity}")
        else:
            identities[identity] = role
        if not isinstance(state_root, str) or not state_root:
            findings.error(f"role {role} must declare state_root")
        elif state_root in roots:
            findings.error(f"roles {roots[state_root]} and {role} share state_root {state_root}")
        else:
            roots[state_root] = role

    loops = data.get("loops")
    if not isinstance(loops, list) or not loops:
        findings.error("ecosystem.json must declare at least one loop")
        loops = []
    seen_loops: set[str] = set()
    for index, loop in enumerate(loops):
        prefix = f"loops[{index}]"
        if not isinstance(loop, dict):
            findings.error(f"{prefix} must be an object")
            continue
        loop_id = loop.get("id")
        if not isinstance(loop_id, str) or not NAME_RE.fullmatch(loop_id):
            findings.error(f"{prefix}.id must be lowercase kebab-case")
        elif loop_id in seen_loops:
            findings.error(f"duplicate loop id {loop_id}")
        else:
            seen_loops.add(loop_id)
        schedule = loop.get("schedule", {})
        if not isinstance(schedule, dict) or int(schedule.get("max_concurrency", 0)) < 1:
            findings.error(f"{prefix} must set max_concurrency >= 1")
        evaluator = loop.get("evaluator")
        if not isinstance(evaluator, dict):
            findings.error(f"{prefix} must declare evaluator")
        else:
            gates = evaluator.get("hard_gates")
            if not isinstance(gates, list) or not gates:
                findings.error(f"{prefix} evaluator needs at least one hard gate")
            if not evaluator.get("verifier"):
                findings.error(f"{prefix} evaluator must declare an adversarial verifier")
            if int(evaluator.get("minimum_samples", 0)) < 1:
                findings.error(f"{prefix} evaluator minimum_samples must be >= 1")
            if evaluator.get("attribution_required") is not True:
                findings.warn(f"{prefix} does not fail closed on incomplete attribution")
        for sensor in loop.get("sensors", []):
            if isinstance(sensor, dict) and sensor.get("kind") == "agent":
                findings.warn(f"{prefix} sensor {sensor.get('id', '?')} depends on an agent; prefer deterministic collection")
        budgets = loop.get("budgets")
        if not isinstance(budgets, dict) or "max_cost_per_day" not in budgets:
            findings.error(f"{prefix} must declare attempt and cost budgets")
        authority = loop.get("authority")
        if authority in {"publish", "stage", "promote"} and not loop.get("promotion"):
            findings.error(f"{prefix} has {authority} authority without a promotion contract")

    state = data.get("state")
    if not isinstance(state, dict):
        findings.error("ecosystem.json must declare state")
    elif not state.get("offsite_backup"):
        findings.warn("state has no offsite backup declaration")
    health = data.get("health")
    if not isinstance(health, dict) or not health.get("deadman"):
        findings.error("ecosystem.json must declare an external deadman")
    if has_placeholder(data):
        message = "ecosystem.json contains unresolved replace/declare placeholders"
        findings.warn(message) if allow_placeholders else findings.error(message)


def validate_policy(data: dict[str, Any], findings: Findings, allow_placeholders: bool) -> None:
    if data.get("schema_version") != 1:
        findings.error("policy.json schema_version must be 1")
    if data.get("default") != "deny":
        findings.error("policy.json default must be deny")
    human_only = set(data.get("human_only", []))
    required = {
        "credential-change", "identity-change", "security-policy-change",
        "spending-limit-change", "irreversible-data-change", "policy-change",
    }
    missing = sorted(required - human_only)
    if missing:
        findings.error(f"policy.json human_only is missing: {', '.join(missing)}")
    policy_change = data.get("policy_change", {})
    if policy_change.get("requires_human_review") is not True:
        findings.error("policy changes must require human review")
    if policy_change.get("self_approval_forbidden") is not True:
        findings.error("policy self-approval must be forbidden")
    if has_placeholder(data) and not allow_placeholders:
        findings.error("policy.json contains unresolved placeholders")


def parse_datetime(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def validate_events(path: pathlib.Path, manifest_name: str | None, findings: Findings, allow_placeholders: bool) -> None:
    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError:
        findings.error("missing events.jsonl")
        return
    except OSError as exc:
        findings.error(f"cannot read events.jsonl: {exc}")
        return
    seen_events: set[str] = set()
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            findings.error(f"events.jsonl:{line_number}: invalid JSON: {exc}")
            continue
        if not isinstance(event, dict):
            findings.error(f"events.jsonl:{line_number}: event must be an object")
            continue
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or len(event_id) < 8:
            findings.error(f"events.jsonl:{line_number}: invalid event_id")
        elif event_id in seen_events:
            findings.error(f"events.jsonl:{line_number}: duplicate event_id {event_id}")
        else:
            seen_events.add(event_id)
        event_type = event.get("type")
        if event_type not in EVENT_TYPES:
            findings.error(f"events.jsonl:{line_number}: unknown event type {event_type!r}")
        if not parse_datetime(event.get("occurred_at")):
            findings.error(f"events.jsonl:{line_number}: occurred_at must be timezone-aware ISO-8601")
        ecosystem = event.get("ecosystem")
        if ecosystem == "__ECOSYSTEM_NAME__" and allow_placeholders:
            pass
        elif manifest_name and ecosystem != manifest_name:
            findings.error(f"events.jsonl:{line_number}: ecosystem does not match manifest")
        if event_type in CANDIDATE_EVENTS and not event.get("candidate_id"):
            findings.error(f"events.jsonl:{line_number}: {event_type} requires candidate_id")
        if not event.get("idempotency_key"):
            findings.error(f"events.jsonl:{line_number}: missing idempotency_key")
        result = event.get("result")
        if not isinstance(result, dict) or not result.get("status") or not result.get("reason"):
            findings.error(f"events.jsonl:{line_number}: result needs status and reason")
        elif event_type == "candidate_accepted":
            objective = result.get("objective")
            if result.get("correct") is not True:
                findings.error(f"events.jsonl:{line_number}: accepted candidate must be correct")
            if not isinstance(objective, (int, float)) or not math.isfinite(float(objective)):
                findings.error(f"events.jsonl:{line_number}: accepted candidate needs finite objective")


def validate_schemas(repo_root: pathlib.Path, findings: Findings) -> None:
    for path in sorted((repo_root / "schemas").glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            findings.error(f"invalid schema {path.name}: {exc}")
            continue
        if data.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            findings.error(f"schema {path.name} must use JSON Schema 2020-12")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", type=pathlib.Path, help="ecosystem directory")
    parser.add_argument("--allow-placeholders", action="store_true", help="validate repository templates")
    args = parser.parse_args()
    target = args.target.resolve()
    findings = Findings()
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    validate_schemas(repo_root, findings)
    manifest = load_json(target / "ecosystem.json", findings)
    policy = load_json(target / "policy.json", findings)
    if manifest is not None:
        validate_manifest(manifest, findings, args.allow_placeholders)
    if policy is not None:
        validate_policy(policy, findings, args.allow_placeholders)
    manifest_name = manifest.get("name") if manifest else None
    validate_events(target / "events.jsonl", manifest_name, findings, args.allow_placeholders)

    for message in findings.warnings:
        print(f"warning: {message}")
    for message in findings.errors:
        print(f"error: {message}", file=sys.stderr)
    if findings.errors:
        print(f"invalid: {len(findings.errors)} error(s), {len(findings.warnings)} warning(s)", file=sys.stderr)
        return 1
    print(f"valid: {target} ({len(findings.warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
