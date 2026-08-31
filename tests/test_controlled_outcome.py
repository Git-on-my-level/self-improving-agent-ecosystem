from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "controlled-outcome"


class ControlledOutcomeTests(unittest.TestCase):
    def score(self, fixture: str) -> dict[str, object]:
        output = subprocess.check_output(
            [sys.executable, str(EXAMPLE / "score.py"), str(EXAMPLE / "fixtures" / fixture)],
            text=True,
        )
        return json.loads(output)

    def test_valid_controlled_improvement_passes(self) -> None:
        result = self.score("valid")
        self.assertTrue(result["correct"])
        self.assertAlmostEqual(result["objective"], 0.175)

    def test_reward_hack_fails_closed(self) -> None:
        result = self.score("reward-hack")
        self.assertFalse(result["correct"])
        self.assertIsNone(result["objective"])
        self.assertIn("attribution", result["note"])

    def test_insufficient_sample_fails_closed(self) -> None:
        result = self.score("insufficient-sample")
        self.assertFalse(result["correct"])
        self.assertIsNone(result["objective"])

    def test_unsigned_identity_fails_closed(self) -> None:
        result = self.score("unsigned-identity")
        self.assertFalse(result["correct"])
        self.assertIsNone(result["objective"])
        self.assertIn("identity", result["note"])

    def test_verifier_recomputes_valid_objective(self) -> None:
        score = self.score("valid")
        with tempfile.TemporaryDirectory() as tmp:
            score_path = pathlib.Path(tmp) / "score.json"
            score_path.write_text(json.dumps(score))
            output = subprocess.check_output(
                [
                    sys.executable,
                    str(EXAMPLE / "verify.py"),
                    str(EXAMPLE / "fixtures" / "valid"),
                    str(score_path),
                ],
                text=True,
            )
        self.assertTrue(json.loads(output)["pass"])


if __name__ == "__main__":
    unittest.main()
