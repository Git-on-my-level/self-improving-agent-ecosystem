#!/usr/bin/env python3
"""Report loops whose last meaningful transition is older than their progress budget.

Exit status: 0 every budgeted loop is within budget, 1 at least one loop is
stale, 2 the manifest or event log could not be read. Run it outside the loop
it checks; a scheduler that fires is not evidence of progress.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

# Transitions that represent real progress. Attempts, failures, and retries do not.
MEANINGFUL = {
    "candidate_accepted", "candidate_superseded", "artifact_promoted",
    "outcome_evaluated", "incident_resolved", "no_action",
}
NOT_PROGRESS = {"failed", "stale", "unobserved"}


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp without timezone: {value}")
    return parsed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("manifest", type=pathlib.Path, help="ecosystem.json")
    ap.add_argument("--events", type=pathlib.Path, help="events JSONL (default: manifest state.event_store)")
    ap.add_argument("--now", help="ISO-8601 reference time (default: current UTC)")
    ap.add_argument("--json", action="store_true", help="print one JSON object per loop")
    a = ap.parse_args()
    try:
        manifest = json.loads(a.manifest.read_text())
        events_path = a.events or a.manifest.parent / manifest.get("state", {}).get("event_store", "events.jsonl")
        now = parse_time(a.now) if a.now else dt.datetime.now(dt.timezone.utc)
        last: dict[str, dt.datetime] = {}
        for number, raw in enumerate(events_path.read_text().splitlines(), 1):
            if not raw.strip():
                continue
            event = json.loads(raw)
            if event.get("type") not in MEANINGFUL:
                continue
            if (event.get("result") or {}).get("status") in NOT_PROGRESS:
                continue
            at = parse_time(event["occurred_at"])
            loop = event.get("loop")
            if loop not in last or at > last[loop]:
                last[loop] = at
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    stale = False
    for loop in manifest.get("loops", []):
        loop_id, budget = loop.get("id"), loop.get("progress_budget_seconds")
        seen = last.get(loop_id)
        age = None if seen is None else int((now - seen).total_seconds())
        if not isinstance(budget, int) or isinstance(budget, bool):
            status = "unbudgeted"
        else:
            status = "stale" if age is None or age > budget else "ok"
            stale = stale or status == "stale"
        if a.json:
            print(json.dumps({"loop": loop_id, "status": status, "age_seconds": age,
                              "budget_seconds": budget,
                              "last_progress": seen.isoformat() if seen else None}))
        else:
            shown = "never" if age is None else f"{age}s ago"
            print(f"{status}: {loop_id} last progress {shown} (budget {budget if budget else 'none'})")
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
