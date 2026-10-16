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


def flag_values(argv, name):
    """Read ``--name=value`` and the older separate-token form."""
    prefix = name + "="
    found = []
    index = 0
    while index < len(argv):
        item = argv[index]
        if item.startswith(prefix):
            found.append(item[len(prefix):])
        elif item == name and index + 1 < len(argv):
            found.append(argv[index + 1])
            index += 1
        index += 1
    return found


def flag(argv, name):
    values = flag_values(argv, name)
    if not values:
        return None
    return values[0]


def flags(argv, name):
    return flag_values(argv, name)


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
                self.assertIsNone(flag(command, "--candidate"))
                self.assertIsNone(flag(command, "--score-after"))

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
        self.assertIsNone(flag(found["evt-accepted"], "--score-before"))
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
        baseline_row = json.loads((FIXTURES / "avo.jsonl").read_text().splitlines()[0])
        baseline_id = f"avo:improve:0:{anx.avo_source_identity(baseline_row)}:baseline"
        self.assertNotIn(":none:", baseline_id)
        self.assertEqual(len(anx.avo_source_identity(baseline_row)), 64)
        baseline = found[baseline_id]
        self.assertEqual(flag(baseline, "--outcome"), "measured")
        self.assertIsNone(flag(baseline, "--decision"))
        self.assertEqual(flag(baseline, "--metric"), "latency_ms=10")
        self.assertEqual(flag(baseline, "--summary"), "baseline score")

        accepted = found["avo:improve:1:aaa111:accept"]
        self.assertEqual(flag(accepted, "--outcome"), "acted")
        self.assertEqual(flag(accepted, "--decision"), "kept")
        self.assertEqual(flag(accepted, "--candidate"), "abc123def456")
        self.assertEqual(flag(accepted, "--score-before"), "10")
        self.assertEqual(flag(accepted, "--score-after"), "12")
        self.assertEqual(flags(accepted, "--metric"), ["latency_ms=12", "samples=2"])

        rejected = found["avo:improve:2:bbb222:reject"]
        self.assertEqual(flag(rejected, "--outcome"), "measured")
        self.assertEqual(flag(rejected, "--decision"), "rejected")
        self.assertIsNone(flag(rejected, "--score-before"))
        self.assertIsNone(flag(rejected, "--score-after"))
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
        self.assertIsNone(flag(acted, "--decision"))

        quiet = found["example-watch:2026-04-02T01:00:00Z"]
        self.assertEqual(flag(quiet, "--outcome"), "no_op")
        self.assertEqual(flag(quiet, "--summary"), "no_op example-watch")

        broken = found["example-watch:2026-04-02T02:00:00+00:00"]
        self.assertEqual(flag(broken, "--outcome"), "infra_error")
        self.assertEqual(len(flag(broken, "--summary")), 280)
        self.assertEqual(flag(broken, "--summary"), "E" * 280)
        self.assertEqual(flag(broken, "--started-at"), "2026-04-02T02:00:00Z")

    def test_goal_effect_picks_the_matching_metric_after(self):
        effects = [
            {
                "ref": "metric:firestore.read_count.24h",
                "metric_before": 806924584,
                "metric_after": 762431713,
            },
            {
                "ref": "metric:firestore.read_count.per_hour_fast",
                "metric_before": 32287839,
                "metric_after": 32425550,
            },
        ]
        matched = {
            "loop": "example-watch",
            "run": "2026-04-02T00:00:00Z",
            "outcome": "measured",
            "note": "reads",
            "metrics": {"samples": 12},
            "effects": effects,
        }
        absent = {
            "loop": "example-watch",
            "run": "2026-04-02T01:00:00Z",
            "outcome": "measured",
            "note": "other series only",
            "effects": [effects[1]],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "firestore.jsonl"
            write_jsonl(path, [matched, absent])
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                commands = anx.build_receipt_commands(
                    [path], card="card:x", goal_metric="reads_24h", since=None, loop=None,
                    anx="anx", workspace=None, goal_effect="metric:firestore.read_count.24h",
                )
        self.assertEqual(stderr.getvalue(), "")
        found = by_run(commands)
        chosen = found["example-watch:2026-04-02T00:00:00Z"]
        self.assertEqual(flags(chosen, "--metric"), [
            "reads_24h=762431713",
            "firestore.read_count.24h=762431713",
            "firestore.read_count.per_hour_fast=32425550",
            "samples=12",
        ])
        self.assertEqual(flags(chosen, "--ref"), [])
        self.assertNotIn("metric:firestore", json.dumps(chosen))
        missed = found["example-watch:2026-04-02T01:00:00Z"]
        self.assertEqual(flags(missed, "--metric"), ["firestore.read_count.per_hour_fast=32425550"])
        self.assertNotIn("reads_24h", json.dumps(missed))

        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "firestore.jsonl"
            write_jsonl(path, [matched])
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                per_hour = anx.build_receipt_commands(
                    [path], card="card:x", goal_metric="reads_24h", since=None, loop=None,
                    anx="anx", workspace=None,
                    goal_effect="metric:firestore.read_count.per_hour_fast",
                )[0]
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(flags(per_hour, "--metric")[0], "reads_24h=32425550")

    def test_several_effects_do_not_guess_the_goal_metric(self):
        effects = [
            {
                "ref": "metric:firestore.read_count.24h",
                "metric_before": 806924584,
                "metric_after": 762431713,
            },
            {
                "ref": "metric:firestore.read_count.per_hour_fast",
                "metric_before": 32287839,
                "metric_after": 32425550,
            },
        ]
        rows = [
            {
                "loop": "example-watch",
                "run": f"2026-04-02T0{index}:00:00Z",
                "outcome": "measured",
                "note": "reads",
                "metrics": {"samples": 12},
                "effects": effects,
            }
            for index in (0, 1)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "firestore.jsonl"
            write_jsonl(path, rows)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                commands = anx.build_receipt_commands(
                    [path], card="card:x", goal_metric="reads_24h", since=None, loop=None,
                    anx="anx", workspace=None,
                )
        warning = stderr.getvalue()
        self.assertEqual(warning.count(anx.AMBIGUOUS_EFFECT_WARNING), 1)
        self.assertIn("--goal-effect", warning)
        self.assertEqual(warning.count("\n"), 1)
        for command in commands:
            self.assertEqual(flags(command, "--metric"), [
                "firestore.read_count.24h=762431713",
                "firestore.read_count.per_hour_fast=32425550",
                "samples=12",
            ])
            self.assertNotIn("reads_24h", json.dumps(command))
            self.assertEqual(flags(command, "--ref"), [])

    def test_single_effect_sets_the_goal_metric(self):
        row = {
            "loop": "example-watch",
            "run": "2026-04-02T00:00:00Z",
            "outcome": "measured",
            "note": "one series",
            "effects": [
                {
                    "ref": "metric:firestore.read_count.24h",
                    "metric_before": 806924584,
                    "metric_after": 762431713,
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "one.jsonl"
            write_jsonl(path, [row])
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                command = anx.build_receipt_commands(
                    [path], card="card:x", goal_metric="reads_24h", since=None, loop=None,
                    anx="anx", workspace=None,
                )[0]
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(flags(command, "--metric"), [
            "reads_24h=762431713",
            "firestore.read_count.24h=762431713",
        ])
        self.assertEqual(flags(command, "--ref"), [])

    def test_metric_ref_becomes_a_named_metric(self):
        row = {
            "loop": "example-watch",
            "run": "2026-04-02T00:00:00Z",
            "outcome": "acted",
            "note": "mixed refs",
            "effects": [
                {"ref": "https://example.com/pr/1", "metric_before": 10, "metric_after": 12},
                {
                    "ref": "metric:firestore.read_count.24h",
                    "metric_before": 806924584,
                    "metric_after": 762431713,
                },
                {"ref": "card:example"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "mixed.jsonl"
            write_jsonl(path, [row])
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                command = anx.build_receipt_commands(
                    [path], card="card:x", goal_metric="reads_24h", since=None, loop=None,
                    anx="anx", workspace=None,
                    goal_effect="metric:firestore.read_count.24h",
                )[0]
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(flags(command, "--ref"), ["https://example.com/pr/1", "card:example"])
        self.assertEqual(flags(command, "--metric"), [
            "reads_24h=762431713",
            "firestore.read_count.24h=762431713",
        ])
        self.assertNotIn("metric:firestore.read_count.24h", json.dumps(command))

        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "mixed.jsonl"
            write_jsonl(path, [row])
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = anx.main([
                    "receipts", "--card", "card:x", "--input", str(path),
                    "--goal-metric", "reads_24h",
                    "--goal-effect", "metric:firestore.read_count.24h",
                ])
            self.assertEqual(code, 0, stderr.getvalue())
            self.assertEqual(stderr.getvalue(), "")
            cli = json.loads(stdout.getvalue())
            self.assertEqual(flags(cli, "--metric")[0], "reads_24h=762431713")
            self.assertEqual(flags(cli, "--ref"), ["https://example.com/pr/1", "card:example"])

            missing = io.StringIO()
            with contextlib.redirect_stderr(missing):
                code = anx.main([
                    "receipts", "--card", "card:x", "--input", str(path),
                    "--goal-effect", "metric:firestore.read_count.24h",
                ])
            self.assertEqual(code, 2)
            self.assertIn("--goal-metric", missing.getvalue())

    def test_same_named_effect_does_not_bypass_goal_selection(self):
        """A metric: effect that shares the goal name is not the goal metric.

        Selection has to succeed. An explicit row metric of that name is kept.
        """
        effects = [
            {"ref": "metric:reads_24h", "metric_before": 806924584, "metric_after": 762431713},
            {"ref": "metric:hourly", "metric_before": 32287839, "metric_after": 32425550},
        ]

        def receipt(run, metrics=None):
            row = {
                "loop": "example-watch",
                "run": run,
                "outcome": "measured",
                "note": "collision",
                "effects": effects,
            }
            if metrics is not None:
                row["metrics"] = metrics
            return "LOOP_RECEIPT " + json.dumps(row)

        def publish(lines, goal_effect=None):
            with tempfile.TemporaryDirectory() as tmp:
                path = pathlib.Path(tmp) / "collision.jsonl"
                path.write_text("".join(line + "\n" for line in lines))
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    commands = anx.build_receipt_commands(
                        [path], card="card:x", goal_metric="reads_24h", since=None, loop=None,
                        anx="anx", workspace=None, goal_effect=goal_effect,
                    )
            return commands, stderr.getvalue()

        missing, missing_err = publish(
            [receipt("2026-04-02T00:00:00Z"), receipt("2026-04-02T01:00:00Z")],
            goal_effect="metric:missing",
        )
        self.assertEqual(missing_err, "")
        for command in missing:
            self.assertEqual(flags(command, "--metric"), ["hourly=32425550"])
            self.assertNotIn("reads_24h", json.dumps(command))
            self.assertNotIn("762431713", json.dumps(command))

        ambiguous, ambiguous_err = publish(
            [receipt("2026-04-02T00:00:00Z"), receipt("2026-04-02T01:00:00Z")],
        )
        self.assertEqual(ambiguous_err.count(anx.AMBIGUOUS_EFFECT_WARNING), 1)
        self.assertEqual(ambiguous_err.count("\n"), 1)
        for command in ambiguous:
            self.assertEqual(flags(command, "--metric"), ["hourly=32425550"])
            self.assertNotIn("reads_24h", json.dumps(command))

        chosen, chosen_err = publish(
            [receipt("2026-04-02T00:00:00Z")],
            goal_effect="metric:reads_24h",
        )
        self.assertEqual(chosen_err, "")
        self.assertEqual(flags(chosen[0], "--metric"), [
            "reads_24h=762431713",
            "hourly=32425550",
        ])

        other, other_err = publish(
            [receipt("2026-04-02T00:00:00Z")],
            goal_effect="metric:hourly",
        )
        self.assertEqual(other_err, "")
        self.assertEqual(flags(other[0], "--metric"), [
            "reads_24h=32425550",
            "hourly=32425550",
        ])
        self.assertNotIn("762431713", json.dumps(other[0]))

        explicit, explicit_err = publish(
            [receipt("2026-04-02T00:00:00Z", metrics={"reads_24h": 111})],
            goal_effect="metric:missing",
        )
        self.assertEqual(explicit_err, "")
        self.assertEqual(flags(explicit[0], "--metric"), [
            "reads_24h=111",
            "hourly=32425550",
        ])

        explicit_ambiguous, explicit_ambiguous_err = publish(
            [receipt("2026-04-02T00:00:00Z", metrics={"reads_24h": 111})],
        )
        self.assertEqual(explicit_ambiguous_err, "")
        self.assertEqual(flags(explicit_ambiguous[0], "--metric")[0], "reads_24h=111")
        self.assertNotIn("762431713", json.dumps(explicit_ambiguous[0]))

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
        self.assertIn("avo:improve:2:bbb222:reject", runs)
        self.assertIn("avo:improve:5:undated0001:accept", runs)
        self.assertNotIn("avo:improve:1:aaa111:accept", runs)
        self.assertFalse(any(":none:" in run for run in runs))
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

        accepted = found["avo:improve:5:c0ffee01:accept"]
        self.assertEqual(flag(accepted, "--outcome"), "acted")
        self.assertEqual(flag(accepted, "--decision"), "kept")
        self.assertEqual(flag(accepted, "--candidate"), "abc123def456")
        self.assertEqual(flag(accepted, "--score-before"), "10")
        self.assertEqual(flag(accepted, "--score-after"), "12")

        lone = found["avo:improve:6:onlyhash01:candidate"]
        self.assertEqual(flag(lone, "--outcome"), "measured")
        self.assertIsNone(flag(lone, "--decision"))
        self.assertIsNone(flag(lone, "--candidate"))
        self.assertEqual(flag(lone, "--metric"), "latency_ms=4")
        self.assertEqual(flag(lone, "--summary"), "only score for this attempt")

        reset = found["avo:improve:7:bbbbccccdddd:rebaseline"]
        self.assertEqual(flag(reset, "--outcome"), "measured")
        self.assertIsNone(flag(reset, "--decision"))
        self.assertIsNone(flag(reset, "--candidate"))
        self.assertIsNone(flag(reset, "--score-before"))
        self.assertIsNone(flag(reset, "--score-after"))
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

    def test_nested_event_ledger_mixes_with_flat_rows(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            commands = anx.build_receipt_commands(
                [FIXTURES / "avo-nested.jsonl"],
                card="card:x", goal_metric="f1", since=None, loop="improve",
                anx="anx", workspace=None,
            )
        found = by_run(commands)
        rendered = json.dumps(commands)
        self.assertNotIn("eval-v1", rendered)
        self.assertNotIn("screen-label", rendered)
        self.assertNotIn("spent_usd", rendered)
        self.assertNotIn("reservation", rendered)
        self.assertNotIn("attempt-slot", rendered)
        self.assertNotIn("supported_threshold_only", rendered)
        self.assertNotIn("checks=", rendered)
        self.assertNotIn("held on the fixture set", rendered)

        baseline = found["avo:improve:1:abc123def456:baseline"]
        self.assertEqual(flag(baseline, "--outcome"), "measured")
        self.assertIsNone(flag(baseline, "--decision"))
        self.assertEqual(
            flags(baseline, "--metric"),
            ["f1=1", "hits=30", "usd_per_1k_screens=4.5"],
        )
        self.assertNotIn("avo:improve:1:abc123def456:verify", found)
        self.assertNotIn("avo:improve:1:abc123def456:candidate", found)
        self.assertNotIn("avo:improve:1:abc123def456:budget", found)

        rejected = found["avo:improve:1:abc123def456:reject"]
        self.assertEqual(flag(rejected, "--outcome"), "measured")
        self.assertEqual(flag(rejected, "--decision"), "rejected")
        self.assertEqual(flag(rejected, "--summary"), "noise margin")
        self.assertEqual(flag(rejected, "--metric"), "f1=1.5")

        failed = found["avo:improve:2:bbbbccccdddd:accept"]
        self.assertEqual(flag(failed, "--outcome"), "measured")
        self.assertEqual(flag(failed, "--decision"), "rejected")
        self.assertEqual(flag(failed, "--score-before"), "2")
        self.assertEqual(flag(failed, "--score-after"), "2.5")
        self.assertIn("not kept: correct is false", flag(failed, "--summary"))
        self.assertIn("gate failed", flag(failed, "--summary"))

        lone = found["avo:improve:4:dddddddddddd:candidate"]
        self.assertEqual(flag(lone, "--outcome"), "measured")
        self.assertIsNone(flag(lone, "--decision"))
        self.assertEqual(flag(lone, "--metric"), "f1=4")

        kept = found["avo:improve:3:flatdiff01:accept"]
        self.assertEqual(flag(kept, "--candidate"), "ccc111ddd222")
        self.assertEqual(flag(kept, "--outcome"), "acted")
        self.assertEqual(flag(kept, "--decision"), "kept")
        self.assertEqual(flag(kept, "--score-before"), "2")
        self.assertEqual(flag(kept, "--score-after"), "3")

        self.assertIn("avo-nested.jsonl:9", stderr.getvalue())
        self.assertIn("skipping unrecognized row", stderr.getvalue())
        with self.assertRaises(anx.PublishError) as caught:
            anx.build_receipt_commands(
                [FIXTURES / "avo-nested.jsonl"],
                card="card:x", goal_metric="f1", since=None, loop="improve",
                anx="anx", workspace=None, strict=True,
            )
        self.assertIn("unrecognized row", str(caught.exception))

    def test_lifecycle_first_line_does_not_abort(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "ledger.jsonl"
            path.write_text(
                "\n".join([
                    json.dumps({
                        "ts": "2026-05-01T00:00:00Z", "tick": 1, "event": "budget",
                        "spent_usd": 0.0, "reservation": "attempt",
                    }),
                    json.dumps({
                        "ts": "2026-05-01T00:01:00Z", "tick": 1, "event": "baseline",
                        "base": "abc123def456",
                        "score": {"correct": True, "objective": 1, "metrics": {"f1": 1}},
                        "note": "baseline score",
                    }),
                    json.dumps({"hello": "world"}),
                    json.dumps({
                        "ts": "2026-05-01T00:02:00Z", "tick": 5, "action": "accept",
                        "correct": False, "objective": 4, "delta": 1, "commit": "eeeeffff0000",
                        "note": "flat gate",
                    }),
                ]) + "\n"
            )
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                commands = anx.build_receipt_commands(
                    [path], card="card:x", goal_metric="f1", since=None, loop="improve",
                    anx="anx", workspace=None,
                )
        found = by_run(commands)
        self.assertIn("avo:improve:1:abc123def456:baseline", found)
        demoted = found["avo:improve:5:eeeeffff0000:accept"]
        self.assertEqual(flag(demoted, "--outcome"), "measured")
        self.assertEqual(flag(demoted, "--decision"), "rejected")
        self.assertIn("flat gate", flag(demoted, "--summary"))
        self.assertIn("not kept: correct is false", flag(demoted, "--summary"))
        self.assertIn("ledger.jsonl:3", stderr.getvalue())
        self.assertIn("skipping unrecognized row", stderr.getvalue())

    def test_metric_cap_keeps_goal_metric_first(self):
        metrics = {f"m{i:02d}": i for i in range(20)}
        metrics["ready"] = True
        metrics["label"] = "drop"
        row = {
            "tick": 1, "action": "baseline", "objective": 9, "note": "capped",
            "commit": "abc123def456", "metrics": metrics, "ts": "2026-05-02T00:00:00Z",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "wide.jsonl"
            write_jsonl(path, [row])
            command = anx.build_receipt_commands(
                [path], card="card:x", goal_metric="zed", since=None, loop="improve",
                anx="anx", workspace=None,
            )[0]
        names = [item.split("=", 1)[0] for item in flags(command, "--metric")]
        self.assertEqual(len(names), 16)
        self.assertEqual(names[0], "zed")
        self.assertEqual(names[1:], [f"m{i:02d}" for i in range(15)])
        self.assertNotIn("ready", names)
        self.assertNotIn("label", names)

    def test_distinct_baselines_and_patches_do_not_share_run_ids(self):
        alpha = {"tick": 0, "action": "baseline", "objective": 1, "note": "alpha"}
        beta = {"tick": 0, "action": "baseline", "objective": 2, "note": "beta"}
        patch_a = {
            "tick": 1, "action": "accept", "loop": "improve", "base": "abc123def456",
            "diff_hash": "patchaaaa", "objective": 3, "delta": 1, "correct": True, "note": "patch a",
        }
        patch_b = dict(patch_a, diff_hash="patchbbbb", objective=4, note="patch b")
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            left = root / "left.jsonl"
            right = root / "right.jsonl"
            again = root / "again.jsonl"
            write_jsonl(left, [alpha])
            write_jsonl(right, [beta])
            write_jsonl(again, [alpha])
            first = anx.build_receipt_commands(
                [left], card="card:x", goal_metric="score", since=None, loop=None, anx="anx", workspace=None,
            )
            second = anx.build_receipt_commands(
                [right], card="card:x", goal_metric="score", since=None, loop=None, anx="anx", workspace=None,
            )
            rerun = anx.build_receipt_commands(
                [again], card="card:x", goal_metric="score", since=None, loop=None, anx="anx", workspace=None,
            )
            patches = root / "patches.jsonl"
            write_jsonl(patches, [patch_a, patch_b])
            both = anx.build_receipt_commands(
                [patches], card="card:x", goal_metric="score", since=None, loop=None, anx="anx", workspace=None,
            )
        alpha_id = flag(first[0], "--run-id")
        beta_id = flag(second[0], "--run-id")
        self.assertNotEqual(alpha_id, beta_id)
        self.assertNotIn(":none:", alpha_id)
        self.assertNotIn(":none:", beta_id)
        self.assertEqual(alpha_id, f"avo:avo:0:{anx.avo_source_identity(alpha)}:baseline")
        self.assertEqual(alpha_id, flag(rerun[0], "--run-id"))
        found = by_run(both)
        self.assertIn("avo:improve:1:patchaaaa:accept", found)
        self.assertIn("avo:improve:1:patchbbbb:accept", found)
        self.assertEqual(flag(found["avo:improve:1:patchaaaa:accept"], "--candidate"), "abc123def456")
        self.assertEqual(flag(found["avo:improve:1:patchbbbb:accept"], "--candidate"), "abc123def456")

    def test_lifecycle_grouping_stays_inside_one_loop(self):
        candidate = {
            "ts": "2026-06-01T00:00:00Z", "tick": 1, "event": "candidate", "loop": "one",
            "score": {"correct": True, "objective": 1.25, "metrics": {"f1": 1.25}},
            "note": "loop one score",
        }
        rejected = {
            "ts": "2026-06-01T00:00:00Z", "tick": 1, "event": "reject", "loop": "two",
            "reason": "other loop",
            "score": {"correct": True, "objective": 2.0},
            "note": "should not hide loop one",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            one = root / "one.jsonl"
            two = root / "two.jsonl"
            write_jsonl(one, [candidate])
            write_jsonl(two, [rejected])
            commands = anx.build_receipt_commands(
                [one, two], card="card:x", goal_metric="f1", since=None, loop=None,
                anx="anx", workspace=None,
            )
        found = by_run(commands)
        cand_id = f"avo:one:1:{anx.avo_source_identity(candidate)}:candidate"
        rej_id = f"avo:two:1:{anx.avo_source_identity(rejected)}:reject"
        self.assertEqual(flag(found[cand_id], "--outcome"), "measured")
        self.assertIsNone(flag(found[cand_id], "--decision"))
        self.assertEqual(flag(found[cand_id], "--summary"), "loop one score")
        self.assertEqual(flag(found[rej_id], "--outcome"), "measured")
        self.assertEqual(flag(found[rej_id], "--decision"), "rejected")
        self.assertEqual(flag(found[rej_id], "--summary"), "other loop")

    def test_drive_relative_refs_are_not_forwarded(self):
        row = {
            "loop": "example-watch",
            "run": "2026-04-02T00:00:00Z",
            "outcome": "acted",
            "note": "refs",
            "effects": [
                {"ref": "c:private/report.json"},
                {"ref": "https://example.com/pr/1"},
                {"ref": "card:example"},
                {"ref": "file:///tmp/fixture"},
                {"ref": "/tmp/fixture"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "refs.jsonl"
            write_jsonl(path, [row])
            command = anx.build_receipt_commands(
                [path], card="card:x", goal_metric=None, since=None, loop=None, anx="anx", workspace=None,
            )[0]
        rendered = json.dumps(command)
        self.assertNotIn("c:private/report.json", rendered)
        self.assertNotIn("file://", rendered)
        self.assertNotIn("/tmp/fixture", rendered)
        self.assertEqual(flags(command, "--ref"), ["https://example.com/pr/1", "card:example"])

    def test_since_silences_old_unrecognized_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "mixed.jsonl"
            write_jsonl(path, [
                {"hello": "world", "ts": "2020-01-01T00:00:00Z"},
                {"hello": "world", "ts": "2026-02-01T00:00:00Z"},
                {
                    "tick": 1, "action": "baseline", "objective": 1, "note": "kept",
                    "commit": "abc123def456", "ts": "2026-02-01T00:00:00Z",
                },
            ])
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                commands = anx.build_receipt_commands(
                    [path], card="card:x", goal_metric="score",
                    since=anx.parse_since("2026-01-01T00:00:00Z"),
                    loop="improve", anx="anx", workspace=None,
                )
            warning = stderr.getvalue()
            self.assertIn("mixed.jsonl:2", warning)
            self.assertIn("skipping unrecognized row", warning)
            self.assertNotIn("mixed.jsonl:1", warning)
            self.assertEqual(list(by_run(commands)), ["avo:improve:1:abc123def456:baseline"])
            with self.assertRaises(anx.PublishError) as caught:
                anx.build_receipt_commands(
                    [path], card="card:x", goal_metric="score",
                    since=anx.parse_since("2026-01-01T00:00:00Z"),
                    loop="improve", anx="anx", workspace=None, strict=True,
                )
        self.assertIn("mixed.jsonl:1", str(caught.exception))
        self.assertIn("unrecognized row", str(caught.exception))

    def test_rejected_accept_keeps_marker_when_note_is_truncated(self):
        note = "N" * 280
        row = {
            "tick": 1, "action": "accept", "correct": False, "objective": 2, "delta": 1,
            "commit": "abc123def456", "note": note,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "long.jsonl"
            write_jsonl(path, [row])
            command = anx.build_receipt_commands(
                [path], card="card:x", goal_metric="score", since=None, loop="improve",
                anx="anx", workspace=None,
            )[0]
        summary = flag(command, "--summary")
        self.assertEqual(flag(command, "--outcome"), "measured")
        self.assertEqual(flag(command, "--decision"), "rejected")
        self.assertEqual(len(summary), 280)
        self.assertTrue(summary.startswith("N"))
        self.assertTrue(summary.endswith("not kept: correct is false"))

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
        self.assertEqual(cadence[0][0], "anx")
        self.assertEqual(cadence[0][1], "--workspace=example")
        self.assertEqual(cadence[0][2:5], ["work", "cadence", "card:x"])
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
        self.assertIsNone(flag(command, "--budget"))

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
                self.assertEqual(command[0], str(missing))
                self.assertEqual(command[1], "--workspace=example")
                self.assertEqual(command[2:5], ["work", "receipt", "card:x"])
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
            # A token of its own named --timeout or --base-url is ANX global config.
            # --summary=--timeout=... must not be parsed that way.
            binary.write_text(textwrap.dedent(f"""\
                #!/usr/bin/env python3
                import json, pathlib, re, sys
                args = sys.argv[1:]
                index = 0
                while index < len(args):
                    token = args[index]
                    name, eq, value = token.partition("=")
                    if name in ("--timeout", "--base-url"):
                        if not eq:
                            if index + 1 >= len(args):
                                sys.stderr.write("missing global value\\n")
                                sys.exit(2)
                            value = args[index + 1]
                            index += 1
                        if name == "--timeout" and not re.fullmatch(r"[1-9][0-9]*[smhd]", value):
                            sys.stderr.write("invalid --timeout\\n")
                            sys.exit(2)
                        if name == "--base-url":
                            sys.stderr.write("unexpected --base-url\\n")
                            sys.exit(2)
                    index += 1
                pathlib.Path({str(log)!r}).open("a").write(json.dumps(sys.argv) + "\\n")
                """))
            binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
            note = "--timeout=not-a-duration"
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
            self.assertNotIn(note, recorded)
            self.assertEqual(flag(recorded, "--summary"), note)
            self.assertFalse((root / "should-not-run").exists())

            manifest = root / "loop.json"
            manifest.write_text(json.dumps({
                "schema_version": 1,
                "stop_rule": "--base-url=http://127.0.0.1:9",
                "progress_budget_seconds": 60,
                "cron": "*/15 * * * *",
            }))
            log.unlink()
            cadence = self.run_cli(
                "manifest", "--card", "card:x", "--manifest", str(manifest),
                "--anx", str(binary), "--apply",
            )
            self.assertEqual(cadence.returncode, 0, cadence.stderr)
            recorded = json.loads(log.read_text().strip())
            self.assertNotIn("--base-url=http://127.0.0.1:9", recorded)
            self.assertEqual(flag(recorded, "--stop-rule"), "--base-url=http://127.0.0.1:9")

            blocked = self.run_cli(
                "receipts", "--card=--timeout=not-a-duration", "--input", str(ledger),
                "--anx", str(binary), "--apply",
            )
            self.assertEqual(blocked.returncode, 2)
            self.assertIn("does not start with '-'", blocked.stderr)
            self.assertEqual(log.read_text().count("\n"), 1)

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
        self.assertIn("avo:improve:2:bbb222:reject", runs)
        self.assertNotIn("avo:improve:1:aaa111:accept", runs)
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
