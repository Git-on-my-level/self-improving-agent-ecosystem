from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
VALIDATOR = ROOT / "scripts" / "validate.py"
INITIALIZER = ROOT / "scripts" / "init-ecosystem.sh"
BRIDGE = ROOT / "scripts" / "avo-to-event.py"


class ValidateTests(unittest.TestCase):
    def initialized(self, root: pathlib.Path) -> pathlib.Path:
        target = root / "example-system"
        subprocess.check_call([str(INITIALIZER), str(target), "example-system"])
        ecosystem_path = target / "ecosystem.json"
        ecosystem = json.loads(ecosystem_path.read_text())
        ecosystem["owner"] = "test-owner"
        ecosystem["state"]["offsite_backup"] = "test-backup"
        ecosystem["health"]["deadman"] = "test-external-deadman"
        ecosystem_path.write_text(json.dumps(ecosystem, indent=2) + "\n")
        return target

    def test_initialized_scaffold_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.initialized(pathlib.Path(tmp))
            result = subprocess.run([sys.executable, str(VALIDATOR), str(target)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_duplicate_role_state_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.initialized(pathlib.Path(tmp))
            path = target / "ecosystem.json"
            data = json.loads(path.read_text())
            data["roles"]["builder"]["state_root"] = data["roles"]["observer"]["state_root"]
            path.write_text(json.dumps(data))
            result = subprocess.run([sys.executable, str(VALIDATOR), str(target)], text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("share state_root", result.stderr)

    def test_accepted_event_without_correctness_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.initialized(pathlib.Path(tmp))
            event_path = target / "events.jsonl"
            event = json.loads(event_path.read_text())
            event.update({"event_id": "accepted-0001", "type": "candidate_accepted", "candidate_id": "candidate-1"})
            event["result"].update({"correct": False, "objective": 10})
            event_path.write_text(json.dumps(event) + "\n")
            result = subprocess.run([sys.executable, str(VALIDATOR), str(target)], text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("accepted candidate must be correct", result.stderr)

    def test_schema_required_fields_and_enums_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.initialized(pathlib.Path(tmp))
            path = target / "ecosystem.json"
            data = json.loads(path.read_text())
            del data["owner"]
            data["loops"][0]["mode"] = "anything-goes"
            data["loops"][0]["budgets"]["max_cost_per_day"] = -1
            path.write_text(json.dumps(data))
            result = subprocess.run([sys.executable, str(VALIDATOR), str(target)], text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing required field owner", result.stderr)
            self.assertIn("invalid value 'anything-goes'", result.stderr)
            self.assertIn("must be >= 0", result.stderr)

    def test_event_schema_required_fields_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.initialized(pathlib.Path(tmp))
            event_path = target / "events.jsonl"
            event = json.loads(event_path.read_text())
            del event["actor"]
            del event["authority"]
            event_path.write_text(json.dumps(event) + "\n")
            result = subprocess.run([sys.executable, str(VALIDATOR), str(target)], text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing required field actor", result.stderr)
            self.assertIn("missing required field authority", result.stderr)

    def test_discover_accept_may_have_null_objective(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.initialized(pathlib.Path(tmp))
            manifest_path = target / "ecosystem.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["loops"][0]["mode"] = "discover"
            manifest_path.write_text(json.dumps(manifest))
            event_path = target / "events.jsonl"
            event = json.loads(event_path.read_text())
            event.update({"event_id": "accepted-0002", "type": "candidate_accepted", "candidate_id": "candidate-1"})
            event["result"].update({"correct": True, "objective": None})
            event_path.write_text(json.dumps(event) + "\n")
            result = subprocess.run([sys.executable, str(VALIDATOR), str(target)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_local_profile_does_not_require_offsite_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = pathlib.Path(tmp) / "local-system"
            subprocess.check_call([str(INITIALIZER), str(target), "local-system", "local"])
            ecosystem_path = target / "ecosystem.json"
            ecosystem = json.loads(ecosystem_path.read_text())
            ecosystem["owner"] = "test-owner"
            ecosystem_path.write_text(json.dumps(ecosystem, indent=2) + "\n")
            result = subprocess.run([sys.executable, str(VALIDATOR), str(target), "--allow-placeholders"], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue((target / "MISSION.md").exists())

    def test_avo_bridge_emits_valid_idempotent_accept_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            target = self.initialized(base)
            avo = base / "avo"
            run = avo / "runs" / "000001"
            run.mkdir(parents=True)
            (run / "score.json").write_text(json.dumps({"correct": True, "objective": 1, "metrics": {}}))
            (run / "diff.patch").write_text("patch")
            ledger = avo / "ledger.jsonl"
            ledger.write_text(json.dumps({
                "tick": 1, "action": "accept", "correct": True, "objective": 1,
                "note": "improved", "parent": "base123", "commit": "commit456",
                "diff_hash": "abc123", "metrics": {}, "run_dir": "runs/000001"
            }) + "\n")
            output = target / "events.jsonl"
            subprocess.check_call([
                sys.executable, str(BRIDGE), "--ledger", str(ledger),
                "--ecosystem", str(target / "ecosystem.json"), "--loop", "improve",
                "--evaluator-revision", "eval-v1", "--output", str(output),
            ])
            event = json.loads(output.read_text())
            self.assertEqual(event["type"], "candidate_accepted")
            self.assertEqual(event["lineage"]["accepted_revision"], "commit456")
            self.assertEqual(event["lineage"]["evaluator_revision"], "eval-v1")
            result = subprocess.run([sys.executable, str(VALIDATOR), str(target)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_templates_validate_with_allow_placeholders(self) -> None:
        templates = ROOT / "templates"
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), str(templates), "--allow-placeholders"],
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_avo_bridge_maps_error_to_candidate_failed_and_keeps_ledger_ts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            target = self.initialized(base)
            avo = base / "avo"
            run = avo / "runs" / "000002"
            run.mkdir(parents=True)
            (run / "score.json").write_text("{}")
            ledger = avo / "ledger.jsonl"
            ledger.write_text(json.dumps({
                "tick": 2, "action": "error", "ts": "2026-02-03T04:05:06Z",
                "note": "scorer timeout", "parent": "base123",
                "diff_hash": "def456", "metrics": {}, "run_dir": "runs/000002",
            }) + "\n")
            output = target / "bridged.jsonl"
            subprocess.check_call([
                sys.executable, str(BRIDGE), "--ledger", str(ledger),
                "--ecosystem", str(target / "ecosystem.json"), "--loop", "improve",
                "--evaluator-revision", "eval-v1", "--output", str(output),
            ])
            event = json.loads(output.read_text())
            self.assertEqual(event["type"], "candidate_failed")
            self.assertEqual(event["result"]["status"], "failed")
            self.assertEqual(event["occurred_at"], "2026-02-03T04:05:06Z")


if __name__ == "__main__":
    unittest.main()
