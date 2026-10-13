#!/usr/bin/env python3
"""Tests for the `loop` tick runner: outcome classes, receipt handling,
ledger semantics, preflight, stall escalation, and status output."""
from __future__ import annotations

import datetime as dt
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

LOOP_PATH = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "loop"
spec = importlib.util.spec_from_loader(
    "loop_runner",
    importlib.machinery.SourceFileLoader("loop_runner", str(LOOP_PATH)),
)
loop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loop)


def receipt(loop_id="test-loop", outcome="no_op", run=None, effects=None, **extra):
    payload = {
        "loop": loop_id,
        "run": run or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "outcome": outcome,
        "effects": effects if effects is not None else [],
        "open_items": 0,
        "oldest_open_days": 0,
        "preflight": {"git": True},
    }
    payload.update(extra)
    return payload


def receipt_line(**kwargs):
    return loop.RECEIPT_PREFIX + json.dumps(receipt(**kwargs))


def sh_quote(text):
    """Quote a string for literal use inside a /bin/sh script."""
    return "'" + text.replace("'", "'\\''") + "'"


def echo_receipt_cmd(dirpath, body_lines, name):
    """A tick command whose script prints fixed lines (receipts already quoted)."""
    helper = dirpath / name
    helper.write_text("#!/bin/sh\n" + "\n".join(body_lines) + "\n")
    helper.chmod(0o755)
    return [str(helper)]


def receipt_echo_line(**kwargs):
    return "echo " + sh_quote(receipt_line(**kwargs))


def write_manifest(dirpath, **overrides):
    data = {
        "schema_version": 1,
        "loop": "test-loop",
        "host": "test-host",
        "archetype": "maintain",
        "goal_metric": "median minutes from alert to resolved",
        "authority": "pr",
        "ledger": str(dirpath / "ledger" / "receipts.jsonl"),
        "effect_probe": "re-run the alert-age query",
        "finisher": "issue closed or superseded",
        "progress_budget_seconds": 604800,
        "stop_rule": "2 stalled escalations -> pause and ask",
        "requires": [],
    }
    data.update(overrides)
    path = dirpath / "manifest.json"
    path.write_text(json.dumps(data))
    return path


def run_loop(*args, env_path=None):
    env = dict(os.environ)
    if env_path is not None:
        env["PATH"] = env_path
    return subprocess.run(
        [sys.executable, str(LOOP_PATH), *args],
        capture_output=True, text=True, env=env,
    )


def script_cmd(dirpath, body, name="tick.sh"):
    """A tick command as a list, with an executable helper script."""
    helper = dirpath / name
    helper.write_text(body)
    helper.chmod(0o755)
    return [str(helper)]


class HelperUnitTests(unittest.TestCase):
    def test_parse_time(self):
        self.assertIsNotNone(loop.parse_time("2026-10-13T04:05:06+00:00"))
        self.assertIsNotNone(loop.parse_time("2026-10-13T04:05:06Z"))
        self.assertIsNotNone(loop.parse_time("2026-10-13T04:05:06"))
        self.assertIsNotNone(loop.parse_time("2026-10-13T04:05:06+0700"),
                             "strftime('%z') stamps are colonless; 3.9 fromisoformat rejects them")
        self.assertEqual(loop.parse_time("2026-10-13T04:05:06+0700"),
                         loop.parse_time("2026-10-13T04:05:06+07:00"))
        self.assertIsNone(loop.parse_time("not-a-time"))
        self.assertIsNone(loop.parse_time(None))
        self.assertIsNone(loop.parse_time(42))

    def test_extract_receipt_last_line_wins(self):
        stdout = "\n".join([
            "noise before",
            receipt_line(outcome="no_op", run="2026-10-13T01:00:00+00:00"),
            "noise between",
            receipt_line(outcome="acted", run="2026-10-13T02:00:00+00:00",
                         effects=[{"ref": "https://example/pr/1", "metric_before": 5, "metric_after": 3}]),
        ])
        got, problem = loop.extract_receipt(stdout)
        self.assertIsNone(problem)
        self.assertEqual(got["outcome"], "acted")
        self.assertEqual(got["effects"][0]["ref"], "https://example/pr/1")

    def test_extract_receipt_missing(self):
        got, problem = loop.extract_receipt("hello\nworld\n")
        self.assertIsNone(got)
        self.assertIn("no LOOP_RECEIPT", problem)

    def test_extract_receipt_invalid_json(self):
        got, problem = loop.extract_receipt("LOOP_RECEIPT {broken")
        self.assertIsNone(got)
        self.assertIn("not JSON", problem)

    def test_validate_receipt_rejects_bad_outcome(self):
        got, problem = loop.validate_receipt(json.dumps(receipt(outcome="ok")))
        self.assertIsNone(got)
        self.assertIn("outcome", problem)

    def test_validate_receipt_rejects_bad_run(self):
        got, problem = loop.validate_receipt(json.dumps(receipt(run="yesterday")))
        self.assertIsNone(got)
        self.assertIn("run", problem)

    def test_validate_receipt_rejects_bad_effect(self):
        got, problem = loop.validate_receipt(json.dumps(receipt(effects=[{"metric_before": 1}])))
        self.assertIsNone(got)
        self.assertIn("ref", problem)

    def test_validate_receipt_rejects_bool_metric(self):
        got, problem = loop.validate_receipt(
            json.dumps(receipt(effects=[{"ref": "x", "metric_before": True, "metric_after": None}])))
        self.assertIsNone(got)
        self.assertIn("metric_before", problem)

    def test_validate_receipt_accepts_null_metrics(self):
        got, problem = loop.validate_receipt(
            json.dumps(receipt(effects=[{"ref": "x", "metric_before": None, "metric_after": None}])))
        self.assertIsNone(problem)
        self.assertIsNotNone(got)

    def test_has_effects(self):
        self.assertTrue(loop.has_effects(receipt(outcome="acted", effects=[{"ref": "x"}])))
        self.assertTrue(loop.has_effects(receipt(outcome="measured", effects=[{"ref": "x"}])))
        self.assertFalse(loop.has_effects(receipt(outcome="acted", effects=[])))
        self.assertFalse(loop.has_effects(receipt(outcome="no_op", effects=[{"ref": "x"}])))


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_manifest(self):
        path = write_manifest(self.dir)
        data, errors = loop.load_manifest(path)
        self.assertEqual(errors, [])
        self.assertEqual(data["loop"], "test-loop")

    def test_missing_required_fields(self):
        path = self.dir / "m.json"
        path.write_text(json.dumps({"schema_version": 1, "loop": "x"}))
        _, errors = loop.load_manifest(path)
        joined = " ".join(errors)
        for field in ("host", "archetype", "goal_metric", "authority", "ledger",
                      "progress_budget_seconds", "stop_rule"):
            self.assertIn(field, joined)

    def test_bad_archetype(self):
        path = write_manifest(self.dir, archetype="grind")
        _, errors = loop.load_manifest(path)
        self.assertTrue(any("archetype" in e for e in errors))

    def test_bad_authority(self):
        path = write_manifest(self.dir, authority="root")
        _, errors = loop.load_manifest(path)
        self.assertTrue(any("authority" in e for e in errors))

    def test_scratch_ledger_rejected(self):
        path = write_manifest(self.dir, ledger="/Volumes/scratch/loops/x.jsonl")
        _, errors = loop.load_manifest(path)
        self.assertTrue(any("scratch" in e for e in errors))

    def test_non_jsonl_ledger_rejected(self):
        path = write_manifest(self.dir, ledger="/tmp/ledgers/x.json")
        _, errors = loop.load_manifest(path)
        self.assertTrue(any("jsonl" in e for e in errors))

    def test_bad_budget(self):
        path = write_manifest(self.dir, progress_budget_seconds=0)
        _, errors = loop.load_manifest(path)
        self.assertTrue(any("progress_budget_seconds" in e for e in errors))

    def test_requires_must_be_list(self):
        path = write_manifest(self.dir, requires="git")
        _, errors = loop.load_manifest(path)
        self.assertTrue(any("requires" in e for e in errors))

    def test_command_must_be_list(self):
        path = write_manifest(self.dir, command="tick.sh")
        _, errors = loop.load_manifest(path)
        self.assertTrue(any("command" in e for e in errors))


class TickOutcomeTests(unittest.TestCase):
    """Every outcome class, driven through `loop tick` as a subprocess."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.manifest = write_manifest(self.dir)
        self.ledger = self.dir / "ledger" / "receipts.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def ledger_lines(self):
        if not self.ledger.exists():
            return []
        return [json.loads(l[len(loop.RECEIPT_PREFIX):]) for l in
                self.ledger.read_text().splitlines() if l.startswith(loop.RECEIPT_PREFIX)]

    def test_acted_receipt_appended_exit_zero(self):
        cmd = echo_receipt_cmd(self.dir, ["echo doing work",
                                          receipt_echo_line(outcome="acted",
                                                            effects=[{"ref": "u"}])], "t.sh")
        proc = run_loop("tick", str(self.manifest), "--", *cmd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = self.ledger_lines()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], "acted")
        self.assertIn("PATH=", proc.stderr)
        self.assertIn("doing work", proc.stdout, "child stdout must be forwarded verbatim")
        self.assertIn(loop.RECEIPT_PREFIX, proc.stdout)

    def test_receipt_not_leaked_into_chat_stderr(self):
        """Runner bookkeeping never prints the receipt to stderr (noise control)."""
        proc = run_loop("tick", str(self.manifest), "--",
                        *echo_receipt_cmd(self.dir, [receipt_echo_line(outcome="no_op")], "t2.sh"))
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn(loop.RECEIPT_PREFIX, proc.stderr)

    def test_measured_receipt_appended_exit_zero(self):
        effects = [{"ref": "q", "metric_before": 9, "metric_after": 4}]
        cmd = echo_receipt_cmd(self.dir, [receipt_echo_line(outcome="measured", effects=effects)], "t.sh")
        proc = run_loop("tick", str(self.manifest), "--", *cmd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.ledger_lines()[0]["outcome"], "measured")

    def test_no_op_receipt_appended_exit_zero(self):
        cmd = echo_receipt_cmd(self.dir, [receipt_echo_line(outcome="no_op")], "t.sh")
        proc = run_loop("tick", str(self.manifest), "--", *cmd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.ledger_lines()[0]["outcome"], "no_op")

    def test_silent_exit_zero_noop_command_is_infra_error(self):
        """The classic silent no-op: exit 0, no receipt, nothing on stdout."""
        cmd = script_cmd(self.dir, "#!/bin/sh\nexit 0\n")
        proc = run_loop("tick", str(self.manifest), "--", *cmd)
        self.assertEqual(proc.returncode, loop.EXIT_INFRA)
        rows = self.ledger_lines()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], "infra_error")
        self.assertIn("infra_error", proc.stderr)

    def test_silent_exit_zero_with_self_appended_fresh_row_is_accepted(self):
        """Transitional loops self-append and print nothing (stdout is chat)."""
        def self_appender():
            helper = self.dir / "selfappend.py"
            helper.write_text(
                "import datetime as dt, json, pathlib\n"
                f"ledger = pathlib.Path({str(self.ledger)!r})\n"
                "ledger.parent.mkdir(parents=True, exist_ok=True)\n"
                "r = {'loop': 'test-loop', 'run': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),"
                " 'outcome': 'no_op', 'effects': [], 'open_items': 0, 'oldest_open_days': 0,"
                " 'preflight': {}}\n"
                "with ledger.open('a') as f:\n"
                "    f.write('LOOP_RECEIPT ' + json.dumps(r) + chr(10))\n"
                "print('chat delivery payload')\n"
            )
            return [sys.executable, str(helper)]

        proc = run_loop("tick", str(self.manifest), "--", *self_appender())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = self.ledger_lines()
        self.assertEqual(len(rows), 1, "runner must not double-append a self-appended receipt")
        self.assertIn("chat delivery payload", proc.stdout)

    def test_self_append_with_older_run_timestamp_is_accepted(self):
        """Self-appended rows stamp the scheduled slot, which may be older than now."""
        old_run = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)).isoformat(timespec="seconds")
        helper = self.dir / "oldrun.py"
        helper.write_text(
            "import json, pathlib\n"
            f"ledger = pathlib.Path({str(self.ledger)!r})\n"
            "ledger.parent.mkdir(parents=True, exist_ok=True)\n"
            f"r = {{'loop': 'test-loop', 'run': {old_run!r},"
            " 'outcome': 'acted', 'effects': [{'ref': 'u'}], 'open_items': 0,"
            " 'oldest_open_days': 0, 'preflight': {}}\n"
            "with ledger.open('a') as f:\n"
            "    f.write('LOOP_RECEIPT ' + json.dumps(r) + chr(10))\n"
            "print('scheduled-slot chat')\n"
        )
        proc = run_loop("tick", str(self.manifest), "--", sys.executable, str(helper))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = self.ledger_lines()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["run"], old_run)
        self.assertEqual(rows[0]["outcome"], "acted")
        self.assertIn("scheduled-slot chat", proc.stdout)

    def test_silent_tick_does_not_reuse_recent_or_future_prior_row(self):
        """Fallback requires a row written this tick, not a close or future run stamp."""
        now = dt.datetime.now(dt.timezone.utc)
        for label, run in (
            ("recent", now.isoformat(timespec="seconds")),
            ("future", (now + dt.timedelta(days=1)).isoformat(timespec="seconds")),
        ):
            with self.subTest(label=label):
                self.ledger.parent.mkdir(parents=True, exist_ok=True)
                self.ledger.write_text(
                    loop.RECEIPT_PREFIX + json.dumps(receipt(outcome="no_op", run=run)) + "\n")
                proc = run_loop("tick", str(self.manifest), "--",
                                *script_cmd(self.dir, "#!/bin/sh\nexit 0\n", f"{label}.sh"))
                self.assertEqual(proc.returncode, loop.EXIT_INFRA)
                rows = self.ledger_lines()
                self.assertEqual(len(rows), 2)
                self.assertEqual(rows[-1]["outcome"], "infra_error")

    def test_invalid_receipt_not_rescued_by_fresh_looking_row(self):
        fresh = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        self.ledger.write_text(
            loop.RECEIPT_PREFIX + json.dumps(receipt(outcome="no_op", run=fresh)) + "\n")
        cmd = script_cmd(self.dir, "#!/bin/sh\necho 'LOOP_RECEIPT {not json}'\n")
        proc = run_loop("tick", str(self.manifest), "--", *cmd)
        self.assertEqual(proc.returncode, loop.EXIT_INFRA)
        rows = self.ledger_lines()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]["outcome"], "infra_error")

    def test_same_run_on_later_tick_is_still_appended(self):
        slot = "2026-10-13T12:00:00+00:00"
        first = run_loop("tick", str(self.manifest), "--",
                         *echo_receipt_cmd(self.dir, [receipt_echo_line(run=slot, outcome="no_op")], "a.sh"))
        self.assertEqual(first.returncode, 0, first.stderr)
        second = run_loop("tick", str(self.manifest), "--",
                          *echo_receipt_cmd(self.dir, [receipt_echo_line(
                              run=slot, outcome="acted", effects=[{"ref": "u"}])], "b.sh"))
        self.assertEqual(second.returncode, 0, second.stderr)
        rows = self.ledger_lines()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["outcome"], "no_op")
        self.assertEqual(rows[1]["outcome"], "acted")
        self.assertEqual(rows[1]["effects"][0]["ref"], "u")

    def test_self_append_and_print_same_receipt_is_not_duplicated(self):
        slot = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        payload = receipt(outcome="no_op", run=slot)
        helper = self.dir / "both.py"
        helper.write_text(
            "import json, pathlib\n"
            f"ledger = pathlib.Path({str(self.ledger)!r})\n"
            "ledger.parent.mkdir(parents=True, exist_ok=True)\n"
            f"r = {payload!r}\n"
            "with ledger.open('a') as f:\n"
            "    f.write('LOOP_RECEIPT ' + json.dumps(r) + chr(10))\n"
            "print('LOOP_RECEIPT ' + json.dumps(r))\n"
        )
        proc = run_loop("tick", str(self.manifest), "--", sys.executable, str(helper))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(self.ledger_lines()), 1)

    def test_nonzero_exit_with_valid_receipt_is_infra_error(self):
        cmd = echo_receipt_cmd(self.dir, [receipt_echo_line(outcome="no_op"), "exit 3"], "t.sh")
        proc = run_loop("tick", str(self.manifest), "--", *cmd)
        self.assertEqual(proc.returncode, loop.EXIT_INFRA)
        rows = self.ledger_lines()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], "infra_error")
        self.assertIn("exited 3", rows[0].get("error", ""))
        status = run_loop("status", str(self.manifest))
        self.assertEqual(status.returncode, 0, status.stderr)
        record = json.loads(status.stdout.strip().splitlines()[0])
        self.assertEqual(record["last_outcome"], "infra_error")
        self.assertEqual(record["fail_streak"], 1)

    def test_infra_error_receipt_exit_nonzero(self):
        cmd = echo_receipt_cmd(self.dir, [
            receipt_echo_line(outcome="infra_error", error="credential missing"),
            "exit 4",
        ], "t.sh")
        proc = run_loop("tick", str(self.manifest), "--", *cmd)
        self.assertEqual(proc.returncode, loop.EXIT_INFRA)
        rows = self.ledger_lines()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], "infra_error")
        self.assertEqual(rows[0].get("error"), "credential missing")

    def test_self_appended_row_rewritten_on_nonzero_exit(self):
        """A crashed self-appending loop's row is rewritten infra_error in place."""
        def self_appender_crash():
            helper = self.dir / "selfappend_crash.py"
            helper.write_text(
                "import datetime as dt, json, pathlib, sys\n"
                f"ledger = pathlib.Path({str(self.ledger)!r})\n"
                "ledger.parent.mkdir(parents=True, exist_ok=True)\n"
                "r = {'loop': 'test-loop', 'run': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),"
                " 'outcome': 'no_op', 'effects': [], 'open_items': 0, 'oldest_open_days': 0,"
                " 'preflight': {}}\n"
                "with ledger.open('a') as f:\n"
                "    f.write('LOOP_RECEIPT ' + json.dumps(r) + chr(10))\n"
                "sys.exit(7)\n"
            )
            return [sys.executable, str(helper)]

        proc = run_loop("tick", str(self.manifest), "--", *self_appender_crash())
        self.assertEqual(proc.returncode, loop.EXIT_INFRA)
        rows = self.ledger_lines()
        self.assertEqual(len(rows), 1, "rewrite in place; never a second row")
        self.assertEqual(rows[0]["outcome"], "infra_error")
        self.assertIn("exited 7", rows[0].get("error", ""))

    def test_extract_receipt_strict_last_line(self):
        """A corrupt final receipt line invalidates the tick even after a valid one."""
        stdout = "\n".join([
            receipt_line(outcome="no_op", run="2026-10-13T01:00:00+00:00"),
            "LOOP_RECEIPT {corrupt",
        ])
        got, problem = loop.extract_receipt(stdout)
        self.assertIsNone(got)
        self.assertIn("not JSON", problem)

    def test_command_stderr_forwarded_on_infra_error(self):
        cmd = script_cmd(self.dir, "#!/bin/sh\necho why-failed >&2\nexit 2\n")
        proc = run_loop("tick", str(self.manifest), "--", *cmd)
        self.assertEqual(proc.returncode, loop.EXIT_INFRA)
        self.assertIn("why-failed", proc.stderr)

    def test_invalid_receipt_is_infra_error(self):
        cmd = script_cmd(self.dir, "#!/bin/sh\necho 'LOOP_RECEIPT {not json'}\n")
        proc = run_loop("tick", str(self.manifest), "--", *cmd)
        self.assertEqual(proc.returncode, loop.EXIT_INFRA)
        self.assertEqual(self.ledger_lines()[0]["outcome"], "infra_error")

    def test_missing_binary_fails_loudly_before_running(self):
        path = write_manifest(self.dir, requires=["definitely-not-on-path-binary"])
        cmd = script_cmd(self.dir, "#!/bin/sh\necho SHOULD_NOT_RUN > side_effect.txt\n")
        proc = run_loop("tick", str(path), "--", *cmd)
        self.assertEqual(proc.returncode, loop.EXIT_MISSING_BIN)
        self.assertIn("preflight FAILED", proc.stderr)
        self.assertIn("PATH=", proc.stderr)
        self.assertFalse((self.dir / "side_effect.txt").exists())
        rows = self.ledger_lines()
        self.assertEqual(rows[0]["outcome"], "infra_error")
        self.assertFalse(rows[0]["preflight"]["definitely-not-on-path-binary"])

    def test_manifest_error_exits_manifest_code(self):
        proc = run_loop("tick", str(self.dir / "nope.json"), "--", "/bin/echo")
        self.assertEqual(proc.returncode, loop.EXIT_MANIFEST)

    def test_no_command_at_all(self):
        proc = run_loop("tick", str(self.manifest))
        self.assertEqual(proc.returncode, loop.EXIT_MANIFEST)

    def test_manifest_default_command_used_when_no_dashdash(self):
        cmd = echo_receipt_cmd(self.dir, [receipt_echo_line(outcome="no_op")], "t.sh")
        path = write_manifest(self.dir, command=cmd)
        proc = run_loop("tick", str(path))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(self.ledger_lines()), 1)


class StallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.ledger = self.dir / "ledger" / "receipts.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def write_ledger(self, rows):
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger.open("w") as f:
            for r in rows:
                f.write(loop.RECEIPT_PREFIX + json.dumps(r) + "\n")

    def test_compute_state_no_op_only_is_stalled(self):
        now = dt.datetime.now(dt.timezone.utc)
        fresh = receipt(outcome="no_op", run=now.isoformat(timespec="seconds"))
        state = loop.compute_state([fresh], budget_seconds=3600)
        self.assertTrue(state["stalled"])
        self.assertEqual(state["last_outcome"], "no_op")
        self.assertIsNone(state["last_effect_at"])
        self.assertEqual(state["fail_streak"], 0)

    def test_compute_state_fresh_effect_not_stalled(self):
        now = dt.datetime.now(dt.timezone.utc)
        fresh = receipt(outcome="acted", run=now.isoformat(timespec="seconds"),
                        effects=[{"ref": "u", "metric_before": 1, "metric_after": 0}])
        state = loop.compute_state([fresh], budget_seconds=3600)
        self.assertFalse(state["stalled"])
        self.assertEqual(state["effects_7d"], 1)

    def test_compute_state_old_effect_stalled_and_effects_7d_window(self):
        old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).isoformat(timespec="seconds")
        recent_noop = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)).isoformat(timespec="seconds")
        rows = [
            receipt(outcome="measured", run=old, effects=[{"ref": "u"}]),
            receipt(outcome="no_op", run=recent_noop),
        ]
        state = loop.compute_state(rows, budget_seconds=86400)
        self.assertTrue(state["stalled"])
        self.assertEqual(state["last_effect_at"], old)
        self.assertEqual(state["effects_7d"], 0)

    def test_fail_streak_counts_trailing_infra_errors(self):
        ok = receipt(outcome="no_op", run="2026-10-10T00:00:00+00:00")
        bad1 = receipt(outcome="infra_error", run="2026-10-11T00:00:00+00:00", error="x")
        bad2 = receipt(outcome="infra_error", run="2026-10-12T00:00:00+00:00", error="y")
        state = loop.compute_state([ok, bad1, bad2], budget_seconds=86400)
        self.assertEqual(state["fail_streak"], 2)
        state2 = loop.compute_state([ok, bad1, receipt(outcome="no_op", run="2026-10-12T01:00:00+00:00")],
                                    budget_seconds=86400)
        self.assertEqual(state2["fail_streak"], 0)

    def test_escalates_once_on_transition(self):
        manifest = write_manifest(self.dir, progress_budget_seconds=3600, loop="stall-test",
                                  ledger=str(self.ledger))
        # Seed: an acted effect 2h ago (budget 3600s) -> the loop is already
        # over budget before the first wrapped tick.
        stale_effect = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)).isoformat(timespec="seconds")
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger.open("w") as f:
            f.write(loop.RECEIPT_PREFIX + json.dumps(
                receipt(outcome="acted", run=stale_effect, effects=[{"ref": "u"}])) + "\n")

        # Tick 1: no_op -> first observation of stalled -> prints once.
        p1 = run_loop("tick", str(manifest), "--",
                      *echo_receipt_cmd(self.dir, [receipt_echo_line(outcome="no_op")], "t1.sh"))
        self.assertEqual(p1.returncode, 0, p1.stderr)
        self.assertIn("LOOP_STALLED", p1.stdout)
        self.assertIn("stop_rule", p1.stdout)

        # Tick 2: still stalled -> must NOT repeat the escalation.
        p2 = run_loop("tick", str(manifest), "--",
                      *echo_receipt_cmd(self.dir, [receipt_echo_line(outcome="no_op")], "t2.sh"))
        self.assertEqual(p2.returncode, 0)
        self.assertNotIn("LOOP_STALLED", p2.stdout)

    def test_no_escalation_while_within_budget(self):
        manifest = write_manifest(self.dir, progress_budget_seconds=3600, loop="healthy-test",
                                  ledger=str(self.ledger))
        p1 = run_loop("tick", str(manifest), "--",
                      *echo_receipt_cmd(self.dir, [receipt_echo_line(outcome="acted",
                                                                     effects=[{"ref": "u"}])], "h1.sh"))
        self.assertEqual(p1.returncode, 0, p1.stderr)
        self.assertNotIn("LOOP_STALLED", p1.stdout)
        p2 = run_loop("tick", str(manifest), "--",
                      *echo_receipt_cmd(self.dir, [receipt_echo_line(outcome="no_op")], "h2.sh"))
        self.assertEqual(p2.returncode, 0)
        self.assertNotIn("LOOP_STALLED", p2.stdout)

    def test_stall_state_file_written_next_to_ledger(self):
        manifest = write_manifest(self.dir, progress_budget_seconds=1, loop="stall-file-test",
                                  ledger=str(self.ledger))
        run_loop("tick", str(manifest), "--",
                 *echo_receipt_cmd(self.dir, [receipt_echo_line(outcome="no_op")], "t4.sh"))
        stall_file = self.ledger.with_name("receipts.stall.json")
        self.assertTrue(stall_file.exists())
        self.assertTrue(json.loads(stall_file.read_text())["stalled"])


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.ledger = self.dir / "ledger" / "receipts.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_status_json_shape(self):
        now = dt.datetime.now(dt.timezone.utc)
        rows = [
            receipt(outcome="acted", run=(now - dt.timedelta(days=1)).isoformat(timespec="seconds"),
                    effects=[{"ref": "u"}, {"ref": "v"}]),
            receipt(outcome="infra_error", run=(now - dt.timedelta(hours=1)).isoformat(timespec="seconds"),
                    error="boom"),
        ]
        self.ledger.parent.mkdir(parents=True)
        with self.ledger.open("w") as f:
            for r in rows:
                f.write(loop.RECEIPT_PREFIX + json.dumps(r) + "\n")
        manifest = write_manifest(self.dir, progress_budget_seconds=86400 * 7)
        proc = run_loop("status", str(manifest))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        record = json.loads(proc.stdout.strip().splitlines()[0])
        for field in ("loop", "manifest", "archetype", "last_run", "last_outcome",
                      "last_effect_at", "effects_7d", "fail_streak", "stalled"):
            self.assertIn(field, record)
        self.assertEqual(record["last_outcome"], "infra_error")
        self.assertEqual(record["fail_streak"], 1)
        self.assertEqual(record["effects_7d"], 2)
        self.assertFalse(record["stalled"])
        self.assertIsNotNone(record["last_effect_at"])

    def test_status_empty_ledger(self):
        manifest = write_manifest(self.dir)
        proc = run_loop("status", str(manifest))
        self.assertEqual(proc.returncode, 0)
        record = json.loads(proc.stdout.strip().splitlines()[0])
        self.assertIsNone(record["last_run"])
        self.assertIsNone(record["last_outcome"])
        self.assertIsNone(record["last_effect_at"])
        self.assertEqual(record["effects_7d"], 0)
        self.assertEqual(record["fail_streak"], 0)
        self.assertTrue(record["stalled"])

    def test_validate_reports_bad_manifest(self):
        bad = self.dir / "bad.json"
        bad.write_text(json.dumps({"schema_version": 1}))
        proc = run_loop("validate", str(bad))
        self.assertEqual(proc.returncode, 1)
        proc2 = run_loop("validate", str(write_manifest(self.dir, loop="good-loop")))
        self.assertEqual(proc2.returncode, 0)
        self.assertIn("ok", proc2.stdout)


class LedgerReaderTests(unittest.TestCase):
    def test_reads_bare_json_rows_and_skips_corrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "l.jsonl"
            good = receipt(outcome="no_op")
            path.write_text("\n".join([
                loop.RECEIPT_PREFIX + json.dumps(good),
                "LOOP_RECEIPT {corrupt",
                json.dumps({"loop": "x", "run": "2026-10-13T00:00:00+00:00", "outcome": "acted",
                            "effects": [{"ref": "u"}], "preflight": {}}),
                "",
            ]))
            rows, corrupt = loop.read_ledger(path)
            self.assertEqual(len(rows), 2)
            self.assertEqual(corrupt, 1)

    def test_missing_ledger_is_empty(self):
        rows, corrupt = loop.read_ledger(pathlib.Path("/nonexistent/receipts.jsonl"))
        self.assertEqual((rows, corrupt), ([], 0))


if __name__ == "__main__":
    unittest.main()
