#!/usr/bin/env python3
"""Example hard-gated, incremental outcome scorer."""

from __future__ import annotations

import json
import math
import pathlib
import sys


MINIMUM_SAMPLES = 20


def result(correct: bool, objective: float | None, note: str, **metrics: object) -> dict[str, object]:
    return {
        "correct": correct,
        "objective": objective,
        "metrics": metrics,
        "note": note,
        "artifacts": ["observation.json"],
    }


def score(candidate: pathlib.Path) -> dict[str, object]:
    data = json.loads((candidate / "observation.json").read_text())

    required = {
        "tests_passed",
        "attribution_complete",
        "eligible_identity_verified",
        "substantive_actions",
        "candidate_successes",
        "candidate_opportunities",
        "baseline_successes",
        "baseline_opportunities",
    }
    missing = sorted(required - data.keys())
    if missing:
        return result(False, None, f"missing fields: {', '.join(missing)}", missing=missing)
    if not data["tests_passed"]:
        return result(False, None, "hard tests failed")
    if not data["attribution_complete"]:
        return result(False, None, "attribution is incomplete or truncated")
    if not data["eligible_identity_verified"]:
        return result(False, None, "counted outcome identity is unsigned or ineligible")
    if int(data["substantive_actions"]) <= 0:
        return result(False, None, "no substantive candidate action")

    candidate_n = int(data["candidate_opportunities"])
    baseline_n = int(data["baseline_opportunities"])
    if candidate_n < MINIMUM_SAMPLES or baseline_n < MINIMUM_SAMPLES:
        return result(
            False,
            None,
            "insufficient treatment or control sample",
            candidate_samples=candidate_n,
            baseline_samples=baseline_n,
        )

    candidate_successes = int(data["candidate_successes"])
    baseline_successes = int(data["baseline_successes"])
    if not (0 <= candidate_successes <= candidate_n and 0 <= baseline_successes <= baseline_n):
        return result(False, None, "success count exceeds its fixed opportunity count")

    candidate_rate = candidate_successes / candidate_n
    baseline_rate = baseline_successes / baseline_n
    objective = candidate_rate - baseline_rate
    if not math.isfinite(objective):
        return result(False, None, "objective is non-finite")
    return result(
        True,
        objective,
        "incremental attributed success rate",
        candidate_rate=candidate_rate,
        baseline_rate=baseline_rate,
        candidate_samples=candidate_n,
        baseline_samples=baseline_n,
        attribution_complete=True,
        substantive_actions=int(data["substantive_actions"]),
    )


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: score.py CANDIDATE_DIR", file=sys.stderr)
        return 2
    try:
        print(json.dumps(score(pathlib.Path(sys.argv[1])), sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"evaluation infrastructure failure: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
