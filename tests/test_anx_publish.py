"""Tests for the optional ANX receipt publisher.

Apply cases use a temporary fake binary. They never invoke a real ANX workspace.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import pathlib
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "anx-publish.py"
FIXTURES = ROOT / "tests" / "fixtures" / "anx"
SCHEMA = ROOT / "schemas" / "event.schema.json"

EXPECTED_EVENTS = {
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
INTERMEDIATE = {
    "candidate_started",
    "candidate_built",
    "candidate_scored",
    "approval_requested",
    "promotion_started",
    "rollback_started",
}


def load_publisher():
    spec = importlib.util.spec_from_file_location("anx_publish", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load anx-publish.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


anx = load_publisher()


def flag(argv, name):
    if name not in argv:
        return None
    return argv[argv.index(name) + 1]


def flags(argv, name):
    found = []
    for index, item in enumerate(argv):
        if item == name:
            found.append(argv[index + 1])
    return found


def by_run(commands):
    return {flag(command, "--run-id"): command for command in commands}


def minimal_event(event_id, kind, **overrides):
    event = {
        "schema_version": 1,
        "event_id": event_id,
        "type": kind,
        "occurred_at": "2026-06-01T00:00:00Z",
        "ecosystem": "example",
        "loop": "improve",
        "idempotency_key": event_id,
        "candidate_id": f"cand-{kind}",
        "actor": {"role": "observer", "implementation": "fixture"},
        "lineage": {},
        "evidence": [],
        "result": {"status": "ok", "reason": f"reason for {kind}"},
        "authority": {"level": "observe", "decision": "allowed"},
    }
    event.update(overrides)
    return event


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


class MappingTests(unittest.TestCase):
    def test_schema_types_are_classified(self):
        schema = json.loads(SCHEMA.read_text())
        types = set(schema["properties"]["type"]["enum"])
        self.assertEqual(types, set(EXPECTED_EVENTS) | INTERMEDIATE)
        self.assertEqual(anx.EVENT_OUTCOMES, EXPECTED_EVENTS)
        self.assertEqual(set(anx.INTERMEDIATE_EVENT_TYPES), INTERMEDIATE)

    def test_mapping_table(self):
        rows = [minimal_event(f"event-{kind}", kind) for kind in EXPECTED_EVENTS]
        rows.extend(minimal_event(f"skip-{kind}", kind) for kind in INTERMEDIATE)
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "mapping.jsonl"
            write_jsonl(path, rows)
            commands = anx.build_receipt_commands(
                [path], card="card:x", goal_metric=None, since=None, loop=None, anx="anx", workspace=None,
            )
        found = by_run(commands)
        self.assertEqual(set(found), {f"event-{kind}" for kind in EXPECTED_EVENTS})
        for kind, (outcome, decision) in EXPECTED_EVENTS.items():
            command = found[f"event-{kind}"]
            self.assertEqual(flag(command, "--outcome"), outcome, kind)
            self.assertEqual(flag(command, "--decision"), decision, kind)
            self.assertEqual(flag(command, "--summary"), f"reason for {kind}")
            if decision:
                self.assertEqual(flag(command, "--candidate"), f"cand-{kind}")
            else:
                self.assertNotIn("--candidate", command)
                self.assertNotIn("--score-after", command)

    def test_intermediate_events_publish_only_the_sole_objective(self):
        for kind in INTERMEDIATE:
            alone = minimal_event(
                f"only-{kind}", kind,
                candidate_id="solo",
                result={"status": "ok", "reason": "scored", "objective": 5},
            )
            with tempfile.TemporaryDirectory() as tmp:
                path = pathlib.Path(tmp) / "one.jsonl"
                write_jsonl(path, [alone])
                commands = anx.build_receipt_commands(
                    [path], card="card:x", goal_metric="objective", since=None, loop=None,
                    anx="anx", workspace=None,
                )
            self.assertEqual(len(commands), 1, kind)
            self.assertEqual(flag(commands[0], "--outcome"), "measured")
            self.assertIsNone(flag(commands[0], "--decision"))
            self.assertEqual(flag(commands[0], "--metric"), "objective=5")

            covered = [
                alone,
                minimal_event(
                    "event-accepted", "candidate_accepted",
                    candidate_id="solo",
                    result={"status": "ok", "reason": "kept", "objective": 6, "correct": True},
                ),
            ]
            with tempfile.TemporaryDirectory() as tmp:
                path = pathlib.Path(tmp) / "both.jsonl"
                write_jsonl(path, covered)
                commands = anx.build_receipt_commands(
                    [path], card="card:x", goal_metric=None, since=None, loop=None,
                    anx="anx", workspace=None,
                )
            runs = set(by_run(commands))
            self.assertNotIn(f"only-{kind}", runs, kind)
            self.assertIn("event-accepted", runs)

    def test_scored_event_without_candidate_id_stays_skipped(self):
        row = minimal_event(
            "event-noscope", "candidate_scored",
            candidate_id=None,
            result={"status": "ok", "reason": "orphan score", "objective": 1},
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "score.jsonl"
            write_jsonl(path, [row])
            commands = anx.build_receipt_commands(
                [path], card="card:x", goal_metric=None, since=None, loop=None, anx="anx", workspace=None,
            )
        self.assertEqual(commands, [])

    def test_human_rejection_is_an_experiment_decision(self):
        denied = minimal_event(
            "event-denied", "human_decision_recorded",
            candidate_id=None,
            result={"status": "rejected", "reason": "needs a smaller change"},
            authority={"level": "publish", "decision": "denied", "approver": "reviewer"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "human.jsonl"
            write_jsonl(path, [denied])
            commands = anx.build_receipt_commands(
                [path], card="card:x", goal_metric=None, since=None, loop=None, anx="anx", workspace=None,
            )
        self.assertEqual(flag(commands[0], "--outcome"), "measured")
        self.assertEqual(flag(commands[0], "--decision"), "rejected")
        self.assertEqual(flag(commands[0], "--candidate"), "event:event-denied")

    def test_checked_in_event_fixture_matches_the_table(self):
        commands = anx.build_receipt_commands(
            [FIXTURES / "events.jsonl"],
            card="card:x", goal_metric="latency_ms", since=None, loop=None, anx="anx", workspace=None,
        )
        found = by_run(commands)
        self.assertNotIn("evt-started", found)
        self.assertNotIn("evt-scored-kept", found)
        self.assertEqual(flag(found["evt-scored-only"], "--outcome"), "measured")
        self.assertIsNone(flag(found["evt-scored-only"], "--decision"))
        self.assertEqual(flag(found["evt-accepted"], "--outcome"), "acted")
        self.assertEqual(flag(found["evt-accepted"], "--decision"), "kept")
        self.assertEqual(flag(found["evt-accepted"], "--score-after"), "12")
        self.assertNotIn("--score-before", found["evt-accepted"])
        self.assertEqual(flag(found["evt-rejected"], "--decision"), "rejected")
        self.assertEqual(flag(found["evt-rollback"], "--decision"), "reverted")
        self.assertEqual(flag(found["evt-noop"], "--outcome"), "no_op")
        self.assertEqual(flag(found["evt-observer-failed"], "--outcome"), "infra_error")
        self.assertEqual(flag(found["evt-deadman"], "--outcome"), "infra_error")
        self.assertEqual(flag(found["evt-promoted"], "--decision"), "kept")
        self.assertEqual(flags(found["evt-observed"], "--ref"), ["https://example.com/obs/1", "card:example"])
        self.assertNotIn("/tmp/fixture", json.dumps(found["evt-observed"]))
        self.assertNotIn("file://", json.dumps(found["evt-observed"]))
        self.assertIn("latency_ms=3", flags(found["evt-observed"], "--metric"))
        self.assertEqual(len(flag(found["evt-long"], "--summary")), 280)
        self.assertTrue(flag(found["evt-long"], "--summary").startswith("R" * 280))


class AvoAndReceiptTests(unittest.TestCase):
    def test_avo_fixture_mapping_scores_and_run_ids(self):
        commands = anx.build_receipt_commands(
            [FIXTURES / "avo.jsonl"],
            card="card:x", goal_metric="latency_ms", since=None, loop="improve", anx="anx", workspace=None,
        )
        found = by_run(commands)
        baseline = found["avo:improve:0:none:baseline"]
        self.assertEqual(flag(baseline, "--outcome"), "measured")
        self.assertIsNone(flag(baseline, "--decision"))
        self.assertEqual(flag(baseline, "--metric"), "latency_ms=10")
        self.assertEqual(flag(baseline, "--summary"), "baseline score")

        accepted = found["avo:improve:1:abc123def456:accept"]
        self.assertEqual(flag(accepted, "--outcome"), "acted")
        self.assertEqual(flag(accepted, "--decision"), "kept")
        self.assertEqual(flag(accepted, "--candidate"), "abc123def456")
        self.assertEqual(flag(accepted, "--score-before"), "10")
        self.assertEqual(flag(accepted, "--score-after"), "12")
        self.assertEqual(flags(accepted, "--metric"), ["latency_ms=12", "samples=2"])

        rejected = found["avo:improve:2:fff999aaa000:reject"]
        self.assertEqual(flag(rejected, "--outcome"), "measured")
        self.assertEqual(flag(rejected, "--decision"), "rejected")
        self.assertNotIn("--score-before", rejected)
        self.assertNotIn("--score-after", rejected)
        self.assertEqual(flag(rejected, "--metric"), "latency_ms=9")

        failed = found["avo:improve:3:ccc333:error"]
        self.assertEqual(flag(failed, "--outcome"), "measured")
        self.assertEqual(flag(failed, "--decision"), "rejected")
        self.assertEqual(flag(failed, "--summary"), "scorer timeout")

    def test_avo_run_ids_are_deterministic_and_ignore_note_edits(self):
        row = {
            "tick": 1, "action": "accept", "objective": 12, "delta": 2,
            "commit": "abc123def456", "note": "first", "loop": "improve",
        }
        edited = dict(row, note="second wording")
        with tempfile.TemporaryDirectory() as tmp:
            first = pathlib.Path(tmp) / "a.jsonl"
            second = pathlib.Path(tmp) / "b.jsonl"
            write_jsonl(first, [row])
            write_jsonl(second, [edited])
            one = anx.build_receipt_commands(
                [first], card="card:x", goal_metric="latency_ms", since=None, loop=None, anx="anx", workspace=None,
            )
            two = anx.build_receipt_commands(
                [second], card="card:x", goal_metric="latency_ms", since=None, loop=None, anx="anx", workspace=None,
            )
            again = anx.build_receipt_commands(
                [first], card="card:x", goal_metric="latency_ms", since=None, loop=None, anx="anx", workspace=None,
            )
        self.assertEqual(flag(one[0], "--run-id"), flag(two[0], "--run-id"))
        self.assertEqual(one, again)
        self.assertNotEqual(flag(one[0], "--summary"), flag(two[0], "--summary"))

    def test_negative_delta_uses_objective_minus_delta(self):
        row = {"tick": 8, "action": "accept", "objective": 9, "delta": -1, "commit": "abc", "note": "down"}
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "delta.jsonl"
            write_jsonl(path, [row])
            command = anx.build_receipt_commands(
                [path], card="card:x", goal_metric="score", since=None, loop="improve", anx="anx", workspace=None,
            )[0]
        self.assertEqual(flag(command, "--score-before"), "10")
        self.assertEqual(flag(command, "--score-after"), "9")

    def test_loop_receipt_fixture(self):
        commands = anx.build_receipt_commands(
            [FIXTURES / "receipts.jsonl"],
            card="card:x", goal_metric="latency ms", since=None, loop=None, anx="anx", workspace=None,
        )
        found = by_run(commands)
        acted = found["example-watch:2026-04-02T00:00:00Z"]
        self.assertEqual(flag(acted, "--outcome"), "acted")
        self.assertEqual(flag(acted, "--summary"), "merged the fixture change")
        self.assertEqual(flags(acted, "--ref"), ["https://example.com/pr/1", "card:example"])
        self.assertNotIn("/tmp/local-only", json.dumps(acted))
        self.assertEqual(flags(acted, "--metric"), ["latency ms=12", "samples=12"])
        self.assertNotIn("--decision", acted)

        quiet = found["example-watch:2026-04-02T01:00:00Z"]
        self.assertEqual(flag(quiet, "--outcome"), "no_op")
        self.assertEqual(flag(quiet, "--summary"), "no_op example-watch")

        broken = found["example-watch:2026-04-02T02:00:00+00:00"]
        self.assertEqual(flag(broken, "--outcome"), "infra_error")
        self.assertEqual(len(flag(broken, "--summary")), 280)
        self.assertEqual(flag(broken, "--summary"), "E" * 280)
        self.assertEqual(flag(broken, "--started-at"), "2026-04-02T02:00:00Z")

    def test_summary_truncation_counts_characters(self):
        reason = "é" * 281
        row = minimal_event("event-unicode", "no_action", result={"status": "no_action", "reason": reason})
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "wide.jsonl"
            write_jsonl(path, [row])
            command = anx.build_receipt_commands(
                [path], card="card:x", goal_metric=None, since=None, loop=None, anx="anx", workspace=None,
            )[0]
        self.assertEqual(flag(command, "--summary"), "é" * 280)
        self.assertEqual(len(flag(command, "--summary")), 280)

    def test_summary_collapses_whitespace(self):
        row = minimal_event(
            "event-space", "no_action",
            result={"status": "no_action", "reason": "hello\nworld   there"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "space.jsonl"
            write_jsonl(path, [row])
            command = anx.build_receipt_commands(
                [path], card="card:x", goal_metric=None, since=None, loop=None, anx="anx", workspace=None,
            )[0]
        self.assertEqual(flag(command, "--summary"), "hello world there")

    def test_since_is_inclusive_and_keeps_undated_rows(self):
        since = anx.parse_since("2026-04-01T02:00:00Z")
        commands = anx.build_receipt_commands(
            [FIXTURES / "avo.jsonl", FIXTURES / "events.jsonl"],
            card="card:x", goal_metric="latency_ms", since=since, loop="improve", anx="anx", workspace=None,
        )
        runs = set(by_run(commands))
        self.assertIn("avo:improve:2:fff999aaa000:reject", runs)
        self.assertIn("avo:improve:5:undated0001:accept", runs)
        self.assertNotIn("avo:improve:1:abc123def456:accept", runs)
        self.assertNotIn("avo:improve:0:none:baseline", runs)
        self.assertNotIn("evt-old", runs)
        self.assertIn("evt-accepted", runs)
        offset = anx.parse_since("2026-06-01T01:00:00+01:00")
        self.assertEqual(offset, anx.parse_since("2026-06-01T00:00:00Z"))

    def test_nonfinite_and_boolean_metrics_are_dropped(self):
        row = {
            "loop": "example-watch",
            "run": "2026-04-02T00:00:00Z",
            "outcome": "measured",
            "effects": [],
            "metrics": {"samples": 1, "ready": True, "bad": float("nan")},
            "note": "sample",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "metrics.jsonl"
            path.write_text(json.dumps(row) + "\n")
            command = anx.build_receipt_commands(
                [path], card="card:x", goal_metric=None, since=None, loop=None, anx="anx", workspace=None,
            )[0]
        self.assertEqual(flags(command, "--metric"), ["samples=1"])

    def test_lifecycle_fixture_maps_rebaseline_and_skips_attempt_rows(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            commands = anx.build_receipt_commands(
                [FIXTURES / "avo-lifecycle.jsonl"],
                card="card:x", goal_metric="latency_ms", since=None, loop="improve",
                anx="anx", workspace=None,
            )
        found = by_run(commands)
        rendered = json.dumps(commands)
        self.assertNotIn("runs/", rendered)
        self.assertNotIn("1111aaaa2222", rendered)
        self.assertNotIn("avo:improve:5:c0ffee01:candidate", found)
        self.assertNotIn("avo:improve:5:c0ffee01:verify", found)
        self.assertNotIn("avo:improve:5:c0ffee01:budget", found)

        accepted = found["avo:improve:5:abc123def456:accept"]
        self.assertEqual(flag(accepted, "--outcome"), "acted")
        self.assertEqual(flag(accepted, "--decision"), "kept")
        self.assertEqual(flag(accepted, "--score-before"), "10")
        self.assertEqual(flag(accepted, "--score-after"), "12")

        lone = found["avo:improve:6:onlyhash01:candidate"]
        self.assertEqual(flag(lone, "--outcome"), "measured")
        self.assertIsNone(flag(lone, "--decision"))
        self.assertNotIn("--candidate", lone)
        self.assertEqual(flag(lone, "--metric"), "latency_ms=4")
        self.assertEqual(flag(lone, "--summary"), "only score for this attempt")

        reset = found["avo:improve:7:bbbbccccdddd:rebaseline"]
        self.assertEqual(flag(reset, "--outcome"), "measured")
        self.assertIsNone(flag(reset, "--decision"))
        self.assertNotIn("--candidate", reset)
        self.assertNotIn("--score-before", reset)
        self.assertNotIn("--score-after", reset)
        self.assertEqual(flags(reset, "--metric"), ["latency_ms=11", "samples=4"])
        self.assertEqual(
            flag(reset, "--summary"),
            "evaluator eval-v1 -> eval-v2 (changed: score); previous best 10",
        )

        budget = found["avo:improve:9:budgetonly1:budget"]
        self.assertEqual(flag(budget, "--outcome"), "measured")
        self.assertEqual(flag(budget, "--metric"), "latency_ms=3")
        self.assertEqual(flag(budget, "--summary"), "only budget sample")
        verify = found["avo:improve:10:verifyonly1:verify"]
        self.assertEqual(flag(verify, "--outcome"), "measured")
        self.assertEqual(flag(verify, "--metric"), "latency_ms=6")
        self.assertEqual(flag(verify, "--summary"), "only verification score")

        warning = stderr.getvalue()
        self.assertIn("avo-lifecycle.jsonl:6", warning)
        self.assertIn("unknown AVO action 'reflect'", warning)
        self.assertEqual(warning.count("warning:"), 1)

    def test_unknown_action_and_event_skip_unless_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            ledger = root / "odd.jsonl"
            write_jsonl(ledger, [
                {"tick": 1, "action": "reflect", "note": "old", "ts": "2026-01-01T00:00:00Z"},
                {"tick": 2, "action": "frobnicate", "note": "later", "ts": "2026-06-01T00:00:00Z"},
                {
                    "tick": 3, "action": "accept", "objective": 2, "delta": 1, "commit": "abc",
                    "note": "kept", "ts": "2026-06-01T01:00:00Z",
                },
            ])
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                commands = anx.build_receipt_commands(
                    [ledger], card="card:x", goal_metric="score", since=anx.parse_since("2026-04-01T00:00:00Z"),
                    loop="improve", anx="anx", workspace=None,
                )
            self.assertEqual(list(by_run(commands)), ["avo:improve:3:abc:accept"])
            warning = stderr.getvalue()
            self.assertIn("odd.jsonl:2", warning)
            self.assertIn("unknown AVO action 'frobnicate'", warning)
            self.assertNotIn("reflect", warning)
            with self.assertRaises(anx.PublishError) as caught:
                anx.build_receipt_commands(
                    [ledger], card="card:x", goal_metric=None, since=None, loop=None,
                    anx="anx", workspace=None, strict=True,
                )
            self.assertIn("odd.jsonl:1", str(caught.exception))
            self.assertIn("reflect", str(caught.exception))

            events = root / "events.jsonl"
            write_jsonl(events, [
                minimal_event("event-widget", "widget_spun"),
                minimal_event("event-quiet", "no_action"),
            ])
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                commands = anx.build_receipt_commands(
                    [events], card="card:x", goal_metric=None, since=None, loop=None,
                    anx="anx", workspace=None,
                )
            self.assertEqual(list(by_run(commands)), ["event-quiet"])
            self.assertIn("unknown event type widget_spun", stderr.getvalue())
            with self.assertRaises(anx.PublishError) as caught:
                anx.build_receipt_commands(
                    [events], card="card:x", goal_metric=None, since=None, loop=None,
                    anx="anx", workspace=None, strict=True,
                )
            self.assertIn("widget_spun", str(caught.exception))


class ManifestTests(unittest.TestCase):
    def test_simple_schedules(self):
        cases = {
            "*/15 * * * *": "15m",
            "*/5 * * * *": "5m",
            "0 * * * *": "1h",
            "0 */2 * * *": "2h",
            "30 */6 * * *": "6h",
            "0 0 * * *": "1d",
            "15 3 * * *": "1d",
            "30 4 * * 1": "7d",
            "0 0 * * 0": "7d",
            "* * * * *": "1m",
            "@hourly": "1h",
            "@daily": "1d",
            "@midnight": "1d",
            "@weekly": "7d",
            "0 0 * * * # nightly": "1d",
        }
        for cron, duration in cases.items():
            self.assertEqual(anx.derive_every(cron), duration, cron)
        for cron in (
            "@monthly",
            "0 0 1 * *",
            "1,15 * * * *",
            "0-5 * * * *",
            "0 0 * * 1-5",
            "example: the scheduler that fires this every 30 minutes",
            "*/15 * * * * echo hi",
            "60 * * * *",
            "0 */24 * * *",
            "",
            None,
        ):
            self.assertIsNone(anx.derive_every(cron), cron)

    def test_budget_durations(self):
        self.assertEqual(anx.format_seconds(90), "90s")
        self.assertEqual(anx.format_seconds(120), "2m")
        self.assertEqual(anx.format_seconds(3600), "1h")
        self.assertEqual(anx.format_seconds(7200), "2h")
        self.assertEqual(anx.format_seconds(86400), "1d")
        self.assertEqual(anx.format_seconds(259200), "3d")
        self.assertEqual(anx.format_seconds(90000), "25h")

    def test_manifest_fixture_emits_cadence_and_optional_goal(self):
        cadence = anx.build_manifest_commands(
            FIXTURES / "manifest.json",
            card="card:x", every=None, goal_metric=None, direction=None,
            target=None, baseline=None, unit=None, anx="anx", workspace="example",
        )
        self.assertEqual(len(cadence), 1)
        self.assertEqual(cadence[0][:4], ["anx", "--workspace", "example", "work"])
        self.assertEqual(flag(cadence[0], "--every"), "15m")
        self.assertEqual(flag(cadence[0], "--budget"), "2h")
        self.assertEqual(flag(cadence[0], "--stop-rule"), "stop after 14 days without an accepted improvement")
        self.assertNotIn("example-host", json.dumps(cadence[0]))
        self.assertNotIn("receipts.jsonl", json.dumps(cadence[0]))

        both = anx.build_manifest_commands(
            FIXTURES / "manifest.json",
            card="card:x", every="1h", goal_metric="latency ms", direction="down",
            target="10", baseline="30", unit="ms", anx="anx", workspace=None,
        )
        self.assertEqual(flag(both[0], "--every"), "1h")
        self.assertEqual(both[1][1:4], ["work", "goal", "card:x"])
        self.assertEqual(flag(both[1], "--metric"), "latency ms")
        self.assertEqual(flag(both[1], "--direction"), "down")
        self.assertEqual(flag(both[1], "--target"), "10")
        self.assertEqual(flag(both[1], "--baseline"), "30")
        self.assertEqual(flag(both[1], "--unit"), "ms")

    def test_prose_cron_requires_every(self):
        with self.assertRaises(anx.PublishError) as caught:
            anx.build_manifest_commands(
                FIXTURES / "manifest-prose.json",
                card="card:x", every=None, goal_metric=None, direction=None,
                target=None, baseline=None, unit=None, anx="anx", workspace=None,
            )
        self.assertIn("--every", str(caught.exception))
        commands = anx.build_manifest_commands(
            FIXTURES / "manifest-prose.json",
            card="card:x", every="30m", goal_metric=None, direction=None,
            target=None, baseline=None, unit=None, anx="anx", workspace=None,
        )
        self.assertEqual(flag(commands[0], "--every"), "30m")
        self.assertEqual(flag(commands[0], "--budget"), "1d")

    def test_goal_flags_must_be_paired_and_null_budget_is_omitted(self):
        with self.assertRaises(anx.PublishError):
            anx.build_manifest_commands(
                FIXTURES / "manifest.json",
                card="card:x", every=None, goal_metric="latency ms", direction=None,
                target=None, baseline=None, unit=None, anx="anx", workspace=None,
            )
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "health.json"
            path.write_text(json.dumps({
                "schema_version": 1,
                "loop": "example-watch",
                "stop_rule": "stop when the owner retires it",
                "progress_budget_seconds": None,
                "cron": "@daily",
            }))
            command = anx.build_manifest_commands(
                path, card="card:x", every=None, goal_metric=None, direction=None,
                target=None, baseline=None, unit=None, anx="anx", workspace=None,
            )[0]
        self.assertEqual(flag(command, "--every"), "1d")
        self.assertNotIn("--budget", command)

    def test_example_manifest_does_not_leak_host_or_ledger(self):
        command = anx.build_manifest_commands(
            ROOT / "templates" / "loop-manifest.example.json",
            card="card:x", every="30m", goal_metric=None, direction=None,
            target=None, baseline=None, unit=None, anx="anx", workspace=None,
        )[0]
        rendered = json.dumps(command)
        self.assertNotIn("hermes", rendered)
        self.assertNotIn("docs-ci-runner", rendered)
        self.assertEqual(flag(command, "--every"), "30m")
        self.assertEqual(flag(command, "--budget"), "3d")
        self.assertIn("14 days", flag(command, "--stop-rule"))


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True, capture_output=True, check=False,
        )

    def test_dry_run_prints_json_argv_and_never_executes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            marker = root / "executed"
            binary = root / "anx"
            binary.write_text("#!/bin/sh\n" + f"touch {marker}\n")
            binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
            missing = root / "missing anx"
            result = self.run_cli(
                "receipts", "--card", "card:x", "--input", str(FIXTURES / "avo.jsonl"),
                "--goal-metric", "latency_ms", "--loop", "improve",
                "--anx", str(missing), "--workspace", "example",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(marker.exists())
            self.assertFalse(missing.exists())
            commands = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertGreaterEqual(len(commands), 4)
            for command in commands:
                self.assertIsInstance(command, list)
                self.assertEqual(command[:4], [str(missing), "--workspace", "example", "work"])
                self.assertNotIn("shell", command)
            touched = self.run_cli(
                "receipts", "--card", "card:x", "--input", str(FIXTURES / "receipts.jsonl"),
                "--anx", str(binary),
            )
            self.assertEqual(touched.returncode, 0, touched.stderr)
            self.assertFalse(marker.exists())
            self.assertIn("improved the fixture", result.stdout)

    def test_dry_run_does_not_call_subprocess(self):
        def boom(*_args, **_kwargs):
            raise AssertionError("subprocess.run was called")

        original = anx.subprocess.run
        anx.subprocess.run = boom
        stdout = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                code = anx.main([
                    "receipts", "--card", "card:x", "--input", str(FIXTURES / "events.jsonl"),
                    "--anx", "definitely-not-anx",
                ])
        finally:
            anx.subprocess.run = original
        self.assertEqual(code, 0)
        self.assertIn("definitely-not-anx", stdout.getvalue())

    def test_apply_uses_an_argv_list_against_a_fake_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            log = root / "argv.jsonl"
            binary = root / "anx"
            binary.write_text(textwrap.dedent(f"""\
                #!/usr/bin/env python3
                import json, pathlib, sys
                pathlib.Path({str(log)!r}).open("a").write(json.dumps(sys.argv) + "\\n")
                """))
            binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
            note = 'say "hello"; touch should-not-run'
            ledger = root / "ledger.jsonl"
            ledger.write_text(json.dumps({
                "tick": 1, "action": "accept", "objective": 2, "delta": 1,
                "commit": "abc", "note": note,
            }) + "\n")
            result = self.run_cli(
                "receipts", "--card", "card:x", "--input", str(ledger),
                "--goal-metric", "score", "--loop", "improve",
                "--anx", str(binary), "--apply",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            recorded = json.loads(log.read_text().strip())
            self.assertEqual(recorded[0], str(binary))
            self.assertEqual(recorded[1:4], ["work", "receipt", "card:x"])
            self.assertIn(note, recorded)
            self.assertFalse((root / "should-not-run").exists())

    def test_apply_stops_on_the_first_nonzero_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            log = root / "seen"
            binary = root / "anx"
            binary.write_text(textwrap.dedent(f"""\
                #!/bin/sh
                echo "$1" >> {log}
                exit 3
                """))
            binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
            result = self.run_cli(
                "manifest", "--card", "card:x", "--manifest", str(FIXTURES / "manifest.json"),
                "--goal-metric", "latency ms", "--direction", "down",
                "--anx", str(binary), "--apply",
            )
            self.assertEqual(result.returncode, 3)
            self.assertEqual(log.read_text().splitlines(), ["work"])

    def test_malformed_json_skips_and_strict_does_not_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            marker = root / "executed"
            log = root / "argv.jsonl"
            binary = root / "anx"
            binary.write_text(textwrap.dedent(f"""\
                #!/usr/bin/env python3
                import json, pathlib, sys
                pathlib.Path({str(log)!r}).open("a").write(json.dumps(sys.argv) + "\\n")
                pathlib.Path({str(marker)!r}).touch()
                """))
            binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
            ledger = root / "bad.jsonl"
            kept = {
                "tick": 1, "action": "accept", "objective": 2, "delta": 1,
                "commit": "abc", "note": "kept going", "ts": "2026-04-02T00:00:00Z",
            }
            ledger.write_text(json.dumps(kept) + "\n{not json\n" + json.dumps(dict(kept, tick=2, commit="def")) + "\n")
            result = self.run_cli(
                "receipts", "--card", "card:x", "--input", str(ledger),
                "--loop", "improve", "--goal-metric", "score",
                "--anx", str(binary), "--apply",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("bad.jsonl:2", result.stderr)
            self.assertIn("malformed JSON", result.stderr)
            recorded = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(
                [flag(command, "--run-id") for command in recorded],
                ["avo:improve:1:abc:accept", "avo:improve:2:def:accept"],
            )
            log.unlink()
            marker.unlink()
            strict = self.run_cli(
                "receipts", "--card", "card:x", "--input", str(ledger),
                "--anx", str(binary), "--apply", "--strict",
            )
            self.assertEqual(strict.returncode, 2)
            self.assertIn("invalid JSON", strict.stderr)
            self.assertEqual(strict.stdout, "")
            self.assertFalse(marker.exists())
            self.assertFalse(log.exists())

    def test_since_cli_and_repeated_dry_run(self):
        args = [
            "receipts", "--card", "card:x", "--input", str(FIXTURES / "avo.jsonl"),
            "--input", str(FIXTURES / "receipts.jsonl"),
            "--since", "2026-04-01T02:00:00Z", "--goal-metric", "latency_ms", "--loop", "improve",
        ]
        first = self.run_cli(*args)
        second = self.run_cli(*args)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertIn("no timestamp", first.stderr)
        runs = {flag(json.loads(line), "--run-id") for line in first.stdout.splitlines()}
        self.assertIn("avo:improve:2:fff999aaa000:reject", runs)
        self.assertNotIn("avo:improve:1:abc123def456:accept", runs)
        self.assertNotIn("example-watch:2026-03-01T00:00:00Z", runs)
        self.assertIn("example-watch:2026-04-02T00:00:00Z", runs)

    def test_manifest_cli_dry_run(self):
        missing = self.run_cli(
            "manifest", "--card", "card:x", "--manifest", str(FIXTURES / "manifest-prose.json"),
        )
        self.assertEqual(missing.returncode, 2)
        self.assertEqual(missing.stdout, "")
        self.assertIn("--every", missing.stderr)
        result = self.run_cli(
            "manifest", "--card", "card:x", "--manifest", str(FIXTURES / "manifest.json"),
            "--every", "30m", "--goal-metric", "latency ms", "--direction", "up",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([command[1:3] for command in commands], [["work", "cadence"], ["work", "goal"]])
        self.assertEqual(flag(commands[0], "--every"), "30m")

    def test_publisher_does_not_build_a_shell_command(self):
        source = SCRIPT.read_text()
        self.assertNotIn("shell=True", source)
        self.assertNotIn("os.system", source)
        self.assertNotIn("shlex", source)

    def test_docs_cover_the_mapping_and_are_linked(self):
        doc = (ROOT / "docs" / "anx.md").read_text()
        for kind in set(EXPECTED_EVENTS) | INTERMEDIATE:
            self.assertIn(f"`{kind}`", doc)
        self.assertIn("candidate_accepted", doc)
        self.assertIn("acted", doc)
        self.assertIn("kept", doc)
        self.assertIn("reverted", doc)
        self.assertIn("anx-publish.py receipts --card card:x --input ledger.jsonl --since", doc)
        self.assertIn("`rebaseline`", doc)
        self.assertIn("`candidate`", doc)
        self.assertIn("`verify`", doc)
        self.assertIn("`budget`", doc)
        self.assertIn("--strict", doc)
        self.assertIn("idempoten", doc.lower())
        readme = (ROOT / "README.md").read_text()
        guide = (ROOT / "docs" / "adoption-guide.md").read_text()
        self.assertIn("docs/anx.md", readme)
        self.assertIn("anx.md", guide)
        self.assertIn("hill-climb", doc)


if __name__ == "__main__":
    unittest.main()
