#!/usr/bin/env python3
"""Publish loop ledgers to Agent Nexus as run receipts.

Reads this repo's event stream, an AVO-lite ledger, or lite ``LOOP_RECEIPT``
rows and prints one ``anx work receipt`` argv per run. A loop manifest becomes
``anx work cadence`` and, when asked, ``anx work goal``.

Dry-run is the default: each command is one JSON array on stdout and nothing
is executed. ``--apply`` runs those argv lists. Arguments are never joined
into a shell command.

See docs/anx.md for the mapping tables and idempotency rules.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import pathlib
import re
import subprocess
import sys
from typing import Any

SUMMARY_LIMIT = 280
RECEIPT_PREFIX = "LOOP_RECEIPT "
OUTCOMES = ("acted", "measured", "no_op", "infra_error")
DECISIONS = ("kept", "reverted", "rejected")

# outcome, experiment decision or None. Intermediate types live separately.
EVENT_OUTCOMES: dict[str, tuple[str, str | None]] = {
    "observation_recorded": ("measured", None),
    "observer_failed": ("infra_error", None),
    "no_action": ("no_op", None),
    "candidate_rejected": ("measured", "rejected"),
    "candidate_failed": ("measured", "rejected"),
    "verification_failed": ("measured", "rejected"),
    "candidate_accepted": ("acted", "kept"),
    "evaluation_invalidated": ("measured", None),
    "candidate_superseded": ("no_op", None),
    "approval_granted": ("measured", None),
    "human_decision_recorded": ("measured", None),
    "autonomy_changed": ("measured", None),
    "promotion_reconciled": ("measured", None),
    "promotion_failed": ("infra_error", None),
    "artifact_promoted": ("acted", "kept"),
    "deployment_observed": ("measured", None),
    "outcome_evaluated": ("measured", None),
    "incident_resolved": ("acted", None),
    "regression_detected": ("measured", None),
    "candidate_quarantined": ("acted", None),
    "rollback_completed": ("acted", "reverted"),
    "loop_stalled": ("infra_error", None),
    "loop_resumed": ("no_op", None),
    "budget_exhausted": ("infra_error", None),
    "deadman_missed": ("infra_error", None),
    "state_repaired": ("acted", None),
}

# Not a run of their own. Emitted only when they alone carry a candidate's objective.
INTERMEDIATE_EVENT_TYPES = frozenset({
    "candidate_started",
    "candidate_built",
    "candidate_scored",
    "approval_requested",
    "promotion_started",
    "rollback_started",
})

# error follows scripts/avo-to-event.py: error -> candidate_failed -> measured/rejected.
# rebaseline resets the incumbent score and carries no experiment decision.
AVO_ACTIONS: dict[str, tuple[str, str | None]] = {
    "baseline": ("measured", None),
    "rebaseline": ("measured", None),
    "accept": ("acted", "kept"),
    "reject": ("measured", "rejected"),
    "error": ("measured", "rejected"),
}

# Attempt lifecycle. Skipped unless the row alone carries that candidate's objective.
INTERMEDIATE_AVO_ACTIONS = frozenset({"candidate", "verify", "budget"})
# diff_hash values AVO writes for non-attempt rows.
_AVO_PLACEHOLDER_DIFFS = frozenset({"", "none", "baseline", "rebaseline"})

_DURATION_RE = re.compile(r"^[1-9][0-9]*[smhd]$")
_ISO_TZ_FIX_RE = re.compile(r"([+-]\d{2})(\d{2})$")
_TYPED_REF_RE = re.compile(r"^[a-z][a-z0-9_-]*:[A-Za-z0-9][A-Za-z0-9._~:/?#@!$&'()*+,;=%-]*$")
_NAMED_CRON = {
    "@hourly": "1h",
    "@daily": "1d",
    "@midnight": "1d",
    "@weekly": "7d",
}


class PublishError(Exception):
    def __init__(self, message: str, code: int = 2) -> None:
        super().__init__(message)
        self.code = code


def parse_time(value: Any) -> dt.datetime | None:
    """Parse an ISO-8601 timestamp to aware UTC. Naive values are UTC.

    Colonless offsets (``+0700``) are accepted. Returns None when the value
    is not a timestamp.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    normalized = _ISO_TZ_FIX_RE.sub(r"\1:\2", text)
    try:
        parsed = dt.datetime.fromisoformat(normalized.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def has_zone(value: str) -> bool:
    text = value.strip()
    if text.endswith(("Z", "z")):
        return True
    parts = re.split(r"[Tt]", text, maxsplit=1)
    if len(parts) != 2:
        return False
    return re.search(r"[+-]\d{2}:?\d{2}$", parts[1]) is not None


def parse_since(value: str) -> dt.datetime:
    if not isinstance(value, str) or not has_zone(value):
        raise PublishError("--since must be RFC3339 with a timezone, for example 2026-01-01T00:00:00Z")
    parsed = parse_time(value)
    if parsed is None:
        raise PublishError("--since must be RFC3339 with a timezone, for example 2026-01-01T00:00:00Z")
    return parsed


def format_rfc3339(value: Any) -> str | None:
    parsed = parse_time(value)
    if parsed is None:
        return None
    if parsed.microsecond:
        text = parsed.isoformat(timespec="microseconds")
    else:
        text = parsed.isoformat(timespec="seconds")
    return text.replace("+00:00", "Z")


def is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if isinstance(value, float) and not math.isfinite(value):
        return False
    return True


def format_number(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PublishError(f"not a number: {value!r}")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PublishError(f"not a finite number: {value!r}")
        if value.is_integer() and abs(value) < 2**53:
            return str(int(value))
        return format(value, ".12g")
    return str(value)


def valid_metric_name(name: Any) -> bool:
    return (
        isinstance(name, str)
        and bool(name)
        and name == name.strip()
        and "=" not in name
        and "\n" not in name
        and "\r" not in name
        and "\t" not in name
    )


def summarize(*candidates: Any, fallback: str) -> str:
    text = ""
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            text = " ".join(candidate.split())
            break
    if not text:
        text = fallback
    if len(text) > SUMMARY_LIMIT:
        text = text[:SUMMARY_LIMIT]
    return text


def safe_ref(value: Any) -> str | None:
    """Keep https URLs and typed refs. Drop local paths and file URIs."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or any(char in text for char in "\n\r\t "):
        return None
    lower = text.lower()
    if lower.startswith(("https://", "http://")):
        return text
    if lower.startswith(("file:", "/", "~", "./", "../")) or "\\" in text or "//" in text:
        return None
    if _TYPED_REF_RE.fullmatch(text):
        return text
    return None


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def numeric_metrics(raw: Any) -> dict[str, int | float]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise PublishError("metrics must be an object")
    found: dict[str, int | float] = {}
    for key, value in raw.items():
        if not valid_metric_name(key) or not is_finite_number(value):
            continue
        found[key] = value
    return found


def format_seconds(seconds: int) -> str:
    if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds <= 0:
        raise PublishError("progress_budget_seconds must be a positive integer or null")
    if seconds % 86400 == 0:
        return f"{seconds // 86400}d"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def validate_duration(value: str, flag: str) -> str:
    if not isinstance(value, str) or not _DURATION_RE.fullmatch(value):
        raise PublishError(f"{flag} must be a positive integer followed by s, m, h, or d")
    return value


def _cron_step(field: str, limit: int) -> int | None:
    match = re.fullmatch(r"\*/([1-9][0-9]*)", field)
    if not match:
        return None
    number = int(match.group(1))
    if 1 <= number <= limit:
        return number
    return None


def _cron_value(field: str, limit: int) -> bool:
    if not re.fullmatch(r"\d{1,2}", field):
        return False
    return int(field) <= limit


def derive_every(cron: Any) -> str | None:
    """Derive a duration from a simple cron expression.

    Returns None for lists, ranges, month-day schedules, job ids, and prose.
    A trailing ``# comment`` is ignored. ``--every`` overrides this result.
    """
    if not isinstance(cron, str):
        return None
    text = cron.split("#", 1)[0].strip()
    if not text:
        return None
    named = _NAMED_CRON.get(text)
    if named:
        return named
    parts = text.split()
    if len(parts) != 5:
        return None
    minute, hour, dom, month, dow = parts
    if any("," in part or "-" in part for part in parts):
        return None
    if any("/" in part and not part.startswith("*/") for part in parts):
        return None
    if month != "*" or dom != "*":
        return None
    if dow != "*":
        if re.fullmatch(r"[0-7]", dow) and _cron_value(minute, 59) and _cron_value(hour, 23):
            return "7d"
        return None
    if minute == "*" and hour == "*":
        return "1m"
    step = _cron_step(minute, 59)
    if step is not None and hour == "*":
        return f"{step}m"
    if _cron_value(minute, 59) and hour == "*":
        return "1h"
    hour_step = _cron_step(hour, 23)
    if hour_step is not None and _cron_value(minute, 59):
        return format_seconds(hour_step * 3600)
    if _cron_value(minute, 59) and _cron_value(hour, 23):
        return "1d"
    return None


def with_anx(anx: str, workspace: str | None, tail: list[str]) -> list[str]:
    argv = [anx]
    if workspace:
        argv.extend(["--workspace", workspace])
    argv.extend(tail)
    return argv


def receipt_tail(
    card: str,
    run_id: str,
    outcome: str,
    summary: str,
    *,
    metrics: dict[str, int | float] | None = None,
    candidate: str | None = None,
    decision: str | None = None,
    score_before: int | float | None = None,
    score_after: int | float | None = None,
    refs: list[str] | None = None,
    started_at: str | None = None,
) -> list[str]:
    if outcome not in OUTCOMES:
        raise PublishError(f"unknown outcome: {outcome}")
    if not run_id or any(char in run_id for char in "\n\r"):
        raise PublishError("run-id must be a single line")
    argv = [
        "work", "receipt", card,
        "--run-id", run_id,
        "--outcome", outcome,
        "--summary", summary,
    ]
    for name in sorted(metrics or {}):
        argv.extend(["--metric", f"{name}={format_number((metrics or {})[name])}"])
    if decision is not None:
        if decision not in DECISIONS:
            raise PublishError(f"unknown decision: {decision}")
        if not candidate or any(char in candidate for char in "\n\r"):
            raise PublishError("experiment decision requires a single-line candidate")
        argv.extend(["--candidate", candidate, "--decision", decision])
        if score_before is not None:
            argv.extend(["--score-before", format_number(score_before)])
        if score_after is not None:
            argv.extend(["--score-after", format_number(score_after)])
    for ref in refs or []:
        argv.extend(["--ref", ref])
    if started_at:
        argv.extend(["--started-at", started_at])
    return argv


def objective_of(event: dict[str, Any]) -> int | float | None:
    result = event.get("result")
    if not isinstance(result, dict):
        return None
    value = result.get("objective")
    if is_finite_number(value):
        return value
    return None


def event_decision(event: dict[str, Any], mapped: str | None) -> str | None:
    if event.get("type") != "human_decision_recorded":
        return mapped
    result = event.get("result") if isinstance(event.get("result"), dict) else {}
    authority = event.get("authority") if isinstance(event.get("authority"), dict) else {}
    if result.get("status") == "rejected" or authority.get("decision") == "denied":
        return "rejected"
    return None


def sole_objective_carriers(events: list[dict[str, Any]]) -> set[str]:
    """Candidate ids whose only numeric objective sits on an intermediate event."""
    non_intermediate: set[str] = set()
    intermediate: set[str] = set()
    for event in events:
        candidate = event.get("candidate_id")
        if not isinstance(candidate, str) or not candidate or objective_of(event) is None:
            continue
        kind = event.get("type")
        if kind in INTERMEDIATE_EVENT_TYPES:
            intermediate.add(candidate)
        elif kind in EVENT_OUTCOMES:
            non_intermediate.add(candidate)
    return intermediate - non_intermediate


def event_command(
    event: dict[str, Any],
    *,
    card: str,
    goal_metric: str | None,
    sole_carriers: set[str],
    where: str,
) -> list[str] | None:
    kind = event.get("type")
    if not isinstance(kind, str):
        raise PublishError(f"{where}: event type is missing")
    if kind not in EVENT_OUTCOMES and kind not in INTERMEDIATE_EVENT_TYPES:
        raise PublishError(f"{where}: unknown event type {kind}")
    event_id = event.get("event_id")
    if not isinstance(event_id, str) or not event_id.strip():
        raise PublishError(f"{where}: event_id is missing")
    intermediate = kind in INTERMEDIATE_EVENT_TYPES
    candidate_id = event.get("candidate_id")
    carries_only = (
        intermediate
        and isinstance(candidate_id, str)
        and candidate_id in sole_carriers
        and objective_of(event) is not None
    )
    if intermediate and not carries_only:
        return None
    if intermediate:
        outcome, decision = "measured", None
    else:
        outcome, decision = EVENT_OUTCOMES[kind]
        decision = event_decision(event, decision)
    result = event.get("result")
    if result is None:
        result = {}
    if not isinstance(result, dict):
        raise PublishError(f"{where}: result must be an object")
    metrics = numeric_metrics(result.get("metrics"))
    objective = objective_of(event)
    if goal_metric and objective is not None:
        metrics[goal_metric] = objective
    candidate = None
    if decision is not None:
        if isinstance(candidate_id, str) and candidate_id.strip():
            candidate = candidate_id.strip()
        else:
            candidate = f"event:{event_id.strip()}"
    score_after = objective if decision is not None else None
    refs = []
    evidence = event.get("evidence")
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, dict):
                ref = safe_ref(item.get("uri"))
                if ref:
                    refs.append(ref)
    reason = result.get("reason")
    return receipt_tail(
        card,
        event_id.strip(),
        outcome,
        summarize(reason, fallback=kind),
        metrics=metrics,
        candidate=candidate,
        decision=decision,
        score_after=score_after,
        refs=dedupe(refs),
        started_at=format_rfc3339(event.get("occurred_at")),
    )


def avo_identity(row: dict[str, Any]) -> str:
    commit = row.get("commit")
    if isinstance(commit, str) and commit.strip():
        return commit.strip()
    diff_hash = row.get("diff_hash")
    if isinstance(diff_hash, str) and diff_hash.strip() and diff_hash.strip() != "none":
        return diff_hash.strip()
    return "none"


def avo_candidate_key(row: dict[str, Any]) -> str | None:
    """Group AVO rows that belong to one attempt.

    An attempt is ``tick`` plus a real ``diff_hash``. Placeholder hashes
    (``baseline``, ``rebaseline``) are not attempts; those rows group by commit.
    """
    diff = row.get("diff_hash")
    if isinstance(diff, str) and diff.strip() not in _AVO_PLACEHOLDER_DIFFS:
        return f"{avo_tick_token(row)}:{diff.strip()}"
    commit = row.get("commit")
    if isinstance(commit, str) and commit.strip():
        return f"commit:{commit.strip()}"
    return None


def avo_tick_token(row: dict[str, Any]) -> str:
    tick = row.get("tick")
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) or (
        isinstance(tick, float) and not tick.is_integer()
    ):
        return "na"
    return str(int(tick))


def sole_avo_objective_carriers(rows: list[dict[str, Any]]) -> set[str]:
    """Attempt keys whose only numeric objective sits on a lifecycle row."""
    non_intermediate: set[str] = set()
    intermediate: set[str] = set()
    for row in rows:
        key = avo_candidate_key(row)
        if key is None or not is_finite_number(row.get("objective")):
            continue
        action = row.get("action")
        if action in INTERMEDIATE_AVO_ACTIONS:
            intermediate.add(key)
        elif action in AVO_ACTIONS:
            non_intermediate.add(key)
    return intermediate - non_intermediate


def avo_tick(row: dict[str, Any], where: str) -> str:
    tick = row.get("tick")
    if tick is None:
        return "na"
    if isinstance(tick, bool) or not isinstance(tick, (int, float)):
        raise PublishError(f"{where}: tick must be an integer")
    if isinstance(tick, float) and not tick.is_integer():
        raise PublishError(f"{where}: tick must be an integer")
    return str(int(tick))


def avo_command(
    row: dict[str, Any],
    *,
    card: str,
    goal_metric: str | None,
    loop: str | None,
    where: str,
    sole_carriers: set[str],
) -> list[str] | None:
    action = row.get("action")
    if action in INTERMEDIATE_AVO_ACTIONS:
        key = avo_candidate_key(row)
        if key is None or key not in sole_carriers or not is_finite_number(row.get("objective")):
            return None
        outcome, decision = "measured", None
    elif action not in AVO_ACTIONS:
        raise PublishError(f"{where}: unknown AVO action {action!r}")
    else:
        outcome, decision = AVO_ACTIONS[action]
    loop_id = row.get("loop")
    if isinstance(loop_id, str) and loop_id.strip():
        loop_name = loop_id.strip()
    elif loop:
        loop_name = loop
    else:
        loop_name = "avo"
    tick = avo_tick(row, where)
    identity = avo_identity(row)
    if any(char in identity for char in "\n\r") or any(char in loop_name for char in "\n\r"):
        raise PublishError(f"{where}: loop id and commit must be single-line")
    run_id = f"avo:{loop_name}:{tick}:{identity}:{action}"
    objective = row.get("objective")
    delta = row.get("delta")
    metrics = numeric_metrics(row.get("metrics"))
    if goal_metric and is_finite_number(objective):
        metrics[goal_metric] = objective
    score_before = None
    score_after = None
    candidate = None
    if decision is not None:
        candidate = identity if identity != "none" else f"tick-{tick}"
        if action == "accept":
            if is_finite_number(objective):
                score_after = objective
            if is_finite_number(objective) and is_finite_number(delta):
                if isinstance(objective, int) and isinstance(delta, int):
                    score_before = objective - delta
                else:
                    score_before = float(objective) - float(delta)
    return receipt_tail(
        card,
        run_id,
        outcome,
        summarize(row.get("note"), fallback=f"{action} tick {tick}"),
        metrics=metrics,
        candidate=candidate,
        decision=decision,
        score_before=score_before,
        score_after=score_after,
        started_at=format_rfc3339(row.get("ts") if row.get("ts") is not None else row.get("occurred_at")),
    )


def loop_command(
    row: dict[str, Any],
    *,
    card: str,
    goal_metric: str | None,
    where: str,
) -> list[str]:
    loop_id = row.get("loop")
    run = row.get("run")
    outcome = row.get("outcome")
    if not isinstance(loop_id, str) or not loop_id.strip():
        raise PublishError(f"{where}: loop receipt needs a loop id")
    if not isinstance(run, str) or parse_time(run) is None:
        raise PublishError(f"{where}: loop receipt run is missing or not ISO-8601")
    if outcome not in OUTCOMES:
        raise PublishError(f"{where}: outcome must be one of {', '.join(OUTCOMES)}")
    effects = row.get("effects", [])
    if effects is None:
        effects = []
    if not isinstance(effects, list):
        raise PublishError(f"{where}: effects must be a list")
    metrics = numeric_metrics(row.get("metrics"))
    refs: list[str] = []
    last_after: int | float | None = None
    for effect in effects:
        if not isinstance(effect, dict):
            raise PublishError(f"{where}: each effect must be an object")
        ref = safe_ref(effect.get("ref"))
        if ref:
            refs.append(ref)
        if is_finite_number(effect.get("metric_after")):
            last_after = effect["metric_after"]
    if goal_metric and goal_metric not in metrics and last_after is not None:
        metrics[goal_metric] = last_after
    return receipt_tail(
        card,
        f"{loop_id.strip()}:{run.strip()}",
        outcome,
        summarize(row.get("error"), row.get("note"), row.get("reason"), fallback=f"{outcome} {loop_id.strip()}"),
        metrics=metrics,
        refs=dedupe(refs),
        started_at=format_rfc3339(run),
    )


def classify(obj: dict[str, Any], hint: str | None) -> str:
    if hint == "receipt":
        return "receipt"
    kind = obj.get("type")
    if isinstance(kind, str) and (
        kind in EVENT_OUTCOMES or kind in INTERMEDIATE_EVENT_TYPES or "event_id" in obj
    ) and ("event_id" in obj or "schema_version" in obj or "idempotency_key" in obj):
        return "event"
    if obj.get("outcome") in OUTCOMES and "run" in obj:
        return "receipt"
    if isinstance(obj.get("action"), str) and any(
        key in obj for key in ("tick", "objective", "diff_hash", "delta", "commit", "note")
    ):
        return "avo"
    raise PublishError(
        "unrecognized row; expected an ecosystem event, an AVO ledger row, or a loop receipt"
    )


def load_rows(path: pathlib.Path, *, strict: bool) -> list[tuple[int, str, dict[str, Any]]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PublishError(f"cannot read {path}: {exc}") from exc
    rows: list[tuple[int, str, dict[str, Any]]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        raw = line.strip()
        if not raw:
            continue
        where = f"{path}:{lineno}"
        hint = None
        payload = raw
        if raw.startswith(RECEIPT_PREFIX):
            hint = "receipt"
            payload = raw[len(RECEIPT_PREFIX):].strip()
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError as exc:
            if strict:
                raise PublishError(f"{where}: invalid JSON ({exc.msg})") from exc
            print(f"warning: {where}: skipping malformed JSON ({exc.msg})", file=sys.stderr)
            continue
        if not isinstance(obj, dict):
            if strict:
                raise PublishError(f"{where}: expected a JSON object")
            print(f"warning: {where}: skipping malformed JSON (expected an object)", file=sys.stderr)
            continue
        try:
            kind = classify(obj, hint)
        except PublishError as exc:
            raise PublishError(f"{where}: {exc}") from exc
        rows.append((lineno, kind, obj))
    return rows


def _in_since_window(kind: str, obj: dict[str, Any], since: dt.datetime | None) -> bool:
    if since is None:
        return True
    stamped = row_timestamp(kind, obj)
    return stamped is None or stamped >= since


def _skip_unknown(where: str, detail: str, *, strict: bool, visible: bool) -> None:
    if strict:
        raise PublishError(f"{where}: {detail}")
    if visible:
        print(f"warning: {where}: skipping {detail}", file=sys.stderr)


def row_timestamp(kind: str, obj: dict[str, Any]) -> dt.datetime | None:
    if kind == "event":
        return parse_time(obj.get("occurred_at"))
    if kind == "avo":
        return parse_time(obj.get("ts") if obj.get("ts") is not None else obj.get("occurred_at"))
    return parse_time(obj.get("run"))


def build_receipt_commands(
    paths: list[pathlib.Path],
    *,
    card: str,
    goal_metric: str | None,
    since: dt.datetime | None,
    loop: str | None,
    anx: str,
    workspace: str | None,
    strict: bool = False,
) -> list[list[str]]:
    if goal_metric is not None and not valid_metric_name(goal_metric):
        raise PublishError("--goal-metric must be a single-line name without '='")
    loaded: list[tuple[pathlib.Path, int, str, dict[str, Any]]] = []
    for path in paths:
        for lineno, kind, obj in load_rows(path, strict=strict):
            loaded.append((path, lineno, kind, obj))
    events = [obj for _, _, kind, obj in loaded if kind == "event"]
    sole = sole_objective_carriers(events)
    avo_sole = sole_avo_objective_carriers([obj for _, _, kind, obj in loaded if kind == "avo"])
    commands: list[list[str]] = []
    undated = 0
    avo_without_metric = False
    for path, lineno, kind, obj in loaded:
        where = f"{path}:{lineno}"
        visible = _in_since_window(kind, obj, since)
        if kind == "event":
            event_type = obj.get("type")
            if isinstance(event_type, str) and event_type not in EVENT_OUTCOMES and event_type not in INTERMEDIATE_EVENT_TYPES:
                _skip_unknown(
                    where, f"unknown event type {event_type}", strict=strict, visible=visible,
                )
                continue
            tail = event_command(
                obj, card=card, goal_metric=goal_metric, sole_carriers=sole, where=where,
            )
        elif kind == "avo":
            action = obj.get("action")
            if action not in AVO_ACTIONS and action not in INTERMEDIATE_AVO_ACTIONS:
                _skip_unknown(
                    where, f"unknown AVO action {action!r}", strict=strict, visible=visible,
                )
                continue
            tail = avo_command(
                obj, card=card, goal_metric=goal_metric, loop=loop, where=where, sole_carriers=avo_sole,
            )
        else:
            tail = loop_command(obj, card=card, goal_metric=goal_metric, where=where)
        if tail is None:
            continue
        stamped = row_timestamp(kind, obj)
        if since is not None:
            if stamped is None:
                undated += 1
            elif stamped < since:
                continue
        if kind == "avo" and goal_metric is None:
            avo_without_metric = True
        commands.append(with_anx(anx, workspace, tail))
    if since is not None and undated:
        if undated == 1:
            print("warning: 1 row had no timestamp and was included despite --since", file=sys.stderr)
        else:
            print(
                f"warning: {undated} rows had no timestamp and were included despite --since",
                file=sys.stderr,
            )
    if avo_without_metric:
        print(
            "warning: AVO rows omit the hill-climb metric unless --goal-metric is set",
            file=sys.stderr,
        )
    return commands


def load_manifest(path: pathlib.Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PublishError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PublishError(f"{path}: invalid JSON ({exc.msg})") from exc
    if not isinstance(data, dict):
        raise PublishError(f"{path}: manifest must be a JSON object")
    if data.get("schema_version") != 1:
        raise PublishError(f"{path}: schema_version must be 1")
    stop = data.get("stop_rule")
    if not isinstance(stop, str) or not stop.strip():
        raise PublishError(f"{path}: stop_rule must be a nonempty string")
    if "progress_budget_seconds" not in data:
        raise PublishError(f"{path}: progress_budget_seconds is missing")
    return data


def canonical_flag_number(value: str, flag: str) -> str:
    try:
        number = float(value)
    except ValueError as exc:
        raise PublishError(f"{flag} must be a finite number") from exc
    if not math.isfinite(number):
        raise PublishError(f"{flag} must be a finite number")
    text = value.strip()
    if re.fullmatch(r"-?[0-9]+", text):
        return str(int(text, 10))
    return format_number(number)


def build_manifest_commands(
    path: pathlib.Path,
    *,
    card: str,
    every: str | None,
    goal_metric: str | None,
    direction: str | None,
    target: str | None,
    baseline: str | None,
    unit: str | None,
    anx: str,
    workspace: str | None,
) -> list[list[str]]:
    if (goal_metric is None) != (direction is None):
        raise PublishError("pass both --goal-metric and --direction to publish an ANX goal, or neither")
    if goal_metric is not None and not valid_metric_name(goal_metric):
        raise PublishError("--goal-metric must be a single-line name without '='")
    if direction is not None and direction not in ("up", "down"):
        raise PublishError("--direction must be up or down")
    if unit is not None and (not isinstance(unit, str) or not unit.strip() or any(c in unit for c in "\n\r")):
        raise PublishError("--unit must be a single-line string")
    manifest = load_manifest(path)
    chosen = validate_duration(every, "--every") if every else derive_every(manifest.get("cron"))
    if not chosen:
        raise PublishError(
            "cron is not a simple schedule; pass --every with a duration such as 30m, 1h, or 1d"
        )
    tail = ["work", "cadence", card, "--every", chosen]
    budget = manifest.get("progress_budget_seconds")
    if budget is not None:
        if isinstance(budget, bool) or not isinstance(budget, int):
            raise PublishError("progress_budget_seconds must be a positive integer or null")
        tail.extend(["--budget", format_seconds(budget)])
    tail.extend(["--stop-rule", manifest["stop_rule"]])
    commands = [with_anx(anx, workspace, tail)]
    if goal_metric and direction:
        goal = ["work", "goal", card, "--metric", goal_metric, "--direction", direction]
        if target is not None:
            goal.extend(["--target", canonical_flag_number(target, "--target")])
        if baseline is not None:
            goal.extend(["--baseline", canonical_flag_number(baseline, "--baseline")])
        if unit is not None:
            goal.extend(["--unit", unit.strip()])
        commands.append(with_anx(anx, workspace, goal))
    return commands


def emit(commands: list[list[str]], *, apply: bool) -> int:
    if not apply:
        for command in commands:
            sys.stdout.write(json.dumps(command, ensure_ascii=False) + "\n")
        return 0
    for command in commands:
        try:
            completed = subprocess.run(command, check=False)
        except FileNotFoundError:
            print(f"anx binary not found: {command[0]}", file=sys.stderr)
            return 1
        if completed.returncode != 0:
            return completed.returncode
    return 0


def _require_text(value: str | None, flag: str) -> str:
    if value is None or not str(value).strip() or any(char in str(value) for char in "\n\r"):
        raise PublishError(f"{flag} must be a single-line nonempty string")
    return str(value)


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--anx", default="anx", help="ANX binary (default: anx)")
    common.add_argument("--workspace", help="pass-through workspace alias")
    common.add_argument(
        "--apply",
        action="store_true",
        help="execute the argv lists; default prints them as JSON and runs nothing",
    )
    parser = argparse.ArgumentParser(
        description="Publish loop ledgers to Agent Nexus. Dry-run unless --apply.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    receipts = sub.add_parser("receipts", parents=[common], help="publish run receipts from a ledger")
    receipts.add_argument("--card", required=True, help="ANX card ref, for example card:example")
    receipts.add_argument("--input", action="append", required=True, type=pathlib.Path, help="JSONL ledger; repeatable")
    receipts.add_argument("--goal-metric", help="metric name for AVO objectives and receipt effects")
    receipts.add_argument("--since", help="include rows at or after this RFC3339 timestamp")
    receipts.add_argument("--loop", help="loop id used in AVO run ids when a row omits one")
    receipts.add_argument(
        "--strict",
        action="store_true",
        help="fail on an unknown action, an unknown event type, or a malformed JSON line",
    )

    manifest = sub.add_parser("manifest", parents=[common], help="publish cadence and an optional goal")
    manifest.add_argument("--card", required=True, help="ANX card ref, for example card:example")
    manifest.add_argument("--manifest", required=True, type=pathlib.Path)
    manifest.add_argument("--every", help="duration override (30m, 1h, 1d) when cron is not simple")
    manifest.add_argument("--goal-metric", help="with --direction, publish anx work goal")
    manifest.add_argument("--direction", choices=("up", "down"))
    manifest.add_argument("--target")
    manifest.add_argument("--baseline")
    manifest.add_argument("--unit")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        card = _require_text(args.card, "--card")
        anx = _require_text(args.anx, "--anx")
        workspace = args.workspace
        if workspace is not None:
            workspace = _require_text(workspace, "--workspace")
        if args.cmd == "receipts":
            since = parse_since(args.since) if args.since else None
            commands = build_receipt_commands(
                list(args.input),
                card=card,
                goal_metric=args.goal_metric,
                since=since,
                loop=args.loop,
                anx=anx,
                workspace=workspace,
                strict=args.strict,
            )
        else:
            commands = build_manifest_commands(
                args.manifest,
                card=card,
                every=args.every,
                goal_metric=args.goal_metric,
                direction=args.direction,
                target=args.target,
                baseline=args.baseline,
                unit=args.unit,
                anx=anx,
                workspace=workspace,
            )
        return emit(commands, apply=args.apply)
    except PublishError as exc:
        print(str(exc), file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    raise SystemExit(main())
