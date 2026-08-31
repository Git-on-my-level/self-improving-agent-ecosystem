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


if __name__ == "__main__":
    unittest.main()
