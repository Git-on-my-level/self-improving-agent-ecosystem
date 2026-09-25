from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
CHECK = ROOT / "scripts" / "progress-check.py"
NOW = "2026-01-10T00:00:00Z"


def event(event_id: str, kind: str, at: str, loop: str = "improve", status: str = "ok") -> dict:
    return {"event_id": event_id, "type": kind, "occurred_at": at, "loop": loop,
            "result": {"status": status, "reason": "test"}}


class ProgressCheckTests(unittest.TestCase):
    def tempdir(self) -> pathlib.Path:
        handle = tempfile.TemporaryDirectory()
        self.addCleanup(handle.cleanup)
        return pathlib.Path(handle.name)

    def run_check(self, events: list[dict], budget: int | None = 86400) -> subprocess.CompletedProcess:
        tmp = self.tempdir()
        manifest = json.loads((ROOT / "templates" / "ecosystem.json").read_text())
        if budget is None:
            manifest["loops"][0].pop("progress_budget_seconds", None)
        else:
            manifest["loops"][0]["progress_budget_seconds"] = budget
        (tmp / "ecosystem.json").write_text(json.dumps(manifest))
        (tmp / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
        return subprocess.run([sys.executable, str(CHECK), str(tmp / "ecosystem.json"), "--now", NOW],
                              text=True, capture_output=True)

    def test_recent_accept_is_healthy(self) -> None:
        result = self.run_check([event("e1", "candidate_accepted", "2026-01-09T12:00:00Z")])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ok: improve", result.stdout)

    def test_attempts_without_progress_are_stale(self) -> None:
        result = self.run_check([
            event("e1", "candidate_accepted", "2026-01-01T00:00:00Z"),
            event("e2", "candidate_started", "2026-01-09T23:00:00Z"),
            event("e3", "candidate_rejected", "2026-01-09T23:30:00Z", status="rejected"),
        ])
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("stale: improve", result.stdout)

    def test_failed_outcome_is_not_progress(self) -> None:
        result = self.run_check([event("e1", "outcome_evaluated", "2026-01-09T23:00:00Z", status="failed")])
        self.assertEqual(result.returncode, 1)

    def test_loop_that_never_progressed_is_stale(self) -> None:
        result = self.run_check([])
        self.assertEqual(result.returncode, 1)
        self.assertIn("never", result.stdout)

    def test_unbudgeted_loop_is_reported_not_failed(self) -> None:
        result = self.run_check([], budget=None)
        self.assertEqual(result.returncode, 0)
        self.assertIn("unbudgeted: improve", result.stdout)

    def test_unreadable_events_is_an_error(self) -> None:
        tmp = self.tempdir()
        (tmp / "ecosystem.json").write_text((ROOT / "templates" / "ecosystem.json").read_text())
        result = subprocess.run([sys.executable, str(CHECK), str(tmp / "ecosystem.json")],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
