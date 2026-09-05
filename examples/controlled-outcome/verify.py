#!/usr/bin/env python3
"""Example adversarial recomputation for a would-be winner."""

from __future__ import annotations

import json
import math
import pathlib
import sys


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: verify.py CANDIDATE_DIR SCORE_JSON", file=sys.stderr)
        return 2
    candidate = pathlib.Path(sys.argv[1])
    try:
        observation = json.loads((candidate / "observation.json").read_text())
        score = json.loads(pathlib.Path(sys.argv[2]).read_text())
        reasons: list[str] = []
        for field in ("attribution_complete", "eligible_identity_verified"):
            if not isinstance(observation.get(field), bool):
                reasons.append(f"{field} must be boolean")
        if not isinstance(score.get("correct"), bool):
            reasons.append("score.correct must be boolean")
        if score.get("correct") is not True:
            reasons.append("score did not pass correctness")
        if not observation.get("attribution_complete"):
            reasons.append("attribution incomplete")
        if not observation.get("eligible_identity_verified"):
            reasons.append("unsigned or ineligible outcome identity")
        if int(observation.get("substantive_actions", 0)) <= 0:
            reasons.append("semantic emptiness")
        candidate_n = int(observation.get("candidate_opportunities", 0))
        baseline_n = int(observation.get("baseline_opportunities", 0))
        if candidate_n < 20 or baseline_n < 20:
            reasons.append("undersized sample")
        if not reasons:
            recomputed = (
                int(observation["candidate_successes"]) / candidate_n
                - int(observation["baseline_successes"]) / baseline_n
            )
            objective = float(score["objective"])
            if not math.isclose(recomputed, objective, rel_tol=1e-12, abs_tol=1e-12):
                reasons.append("objective does not reproduce")
        verdict = {
            "pass": not reasons,
            "note": "independent recomputation passed" if not reasons else "; ".join(reasons),
            "evidence": ["observation.json"],
        }
        print(json.dumps(verdict, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"verifier infrastructure failure: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
