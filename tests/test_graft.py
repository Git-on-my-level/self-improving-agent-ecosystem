from __future__ import annotations

import hashlib
import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
INTAKE = ROOT / "scripts" / "graft-intake.py"
EVENT_SCHEMA = json.loads((ROOT / "schemas" / "event.schema.json").read_text())
sys.path.insert(0, str(ROOT / "scripts"))

from validate import Findings, validate_schema_instance  # noqa: E402

FIXTURE = {"observation": "baseline is slower", "value": 3}


def write_pack(
    root: pathlib.Path,
    *,
    artifacts: dict[str, bytes] | None = None,
    claims: list[dict] | None = None,
    **overrides: object,
) -> pathlib.Path:
    pack = root / "pack"
    (pack / "fixtures").mkdir(parents=True)
    if artifacts is None:
        artifacts = {
            "SKILL.md": b"# Practice\n\nDo the thing incrementally.\n",
            "fixtures/baseline.json": json.dumps(FIXTURE).encode(),
        }
    artifacts = dict(artifacts)
    for relative, content in artifacts.items():
        path = pack / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    entries = []
    for relative in sorted(artifacts):
        content = artifacts[relative]
        kind = "fixture-data" if relative.endswith(".json") else "skill-doc"
        entries.append({
            "path": relative,
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
            "kind": kind,
        })
    manifest = {
        "schema_version": 1,
        "pack": "example-pack",
        "title": "Example pack",
        "description": "Argues that incremental practice beats rewrites.",
        "license": "MIT",
        "authors": ["Someone"],
        "source": {"repo": "https://example.com/packs/example-pack", "ref": "main"},
        "artifacts": entries,
        "claims": claims if claims is not None else [{
            "kind": "regression_test_distinguishes",
            "statement": "The fixture data distinguishes incremental from rewrite behavior.",
            "fixtures": ["fixtures/baseline.json"],
        }],
    }
    manifest.update(overrides)
    (pack / "graft.json").write_text(json.dumps(manifest, indent=2))
    return pack


def run_intake(pack: pathlib.Path, out: pathlib.Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(INTAKE), "--pack", str(pack), "--out", str(out), *extra],
        capture_output=True, text=True,
    )


class GraftIntakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def digest_of(self, pack: pathlib.Path) -> str:
        pairs = []
        for path in sorted(p for p in pack.rglob("*") if p.is_file() and p.name != "graft.json"):
            pairs.append([path.relative_to(pack).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()])
        canonical = json.dumps(sorted(pairs), separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def valid_pack(self) -> pathlib.Path:
        return write_pack(self.root)

    def test_valid_pack_produces_candidate_and_event(self) -> None:
        pack = self.valid_pack()
        out = self.root / "candidate.json"
        events = self.root / "events.jsonl"
        result = run_intake(pack, out, "--event", str(events), "--ecosystem", "demo", "--loop", "main-loop")
        self.assertEqual(result.returncode, 0, result.stderr)
        candidate = json.loads(out.read_text())
        self.assertEqual(candidate["candidate_id"], f"graft-{self.digest_of(pack)[:12]}")
        self.assertEqual(candidate["source"]["pack_digest"], self.digest_of(pack))
        self.assertFalse(candidate["reject_by_default"])
        event = json.loads(events.read_text().splitlines()[-1])
        self.assertEqual(event["type"], "pack_intake_recorded")
        self.assertEqual(event["candidate_id"], candidate["candidate_id"])
        self.assertEqual(event["evidence"][0]["uri"], f"pack:{self.digest_of(pack)}")
        self.assertEqual(event["idempotency_key"], f"graft-intake:{self.digest_of(pack)}")
        findings = Findings()
        validate_schema_instance(event, EVENT_SCHEMA, "event", findings)
        self.assertEqual(findings.errors, [])

    def test_event_type_is_registered_in_validator(self) -> None:
        import validate
        self.assertIn("pack_intake_recorded", validate.EVENT_TYPES)
        self.assertIn("pack_intake_recorded", validate.CANDIDATE_EVENTS)

    def test_digest_is_deterministic_and_tamper_sensitive(self) -> None:
        pack = self.valid_pack()
        out = self.root / "candidate.json"
        first = run_intake(pack, out)
        self.assertEqual(first.returncode, 0, first.stderr)
        digest_before = json.loads(out.read_text())["source"]["pack_digest"]
        self.assertEqual(digest_before, self.digest_of(pack))
        manifest = json.loads((pack / "graft.json").read_text())
        manifest["description"] = "Changed description changes the manifest but not artifacts."
        (pack / "graft.json").write_text(json.dumps(manifest))
        second = run_intake(pack, self.root / "candidate2.json")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(
            json.loads((self.root / "candidate2.json").read_text())["source"]["pack_digest"],
            digest_before,
        )
        # A changed artifact byte must change the digest and break the manifest hash.
        (pack / "SKILL.md").write_bytes(b"# Practice\n\nDo the thing differently.\n")
        tampered = run_intake(pack, self.root / "candidate3.json")
        self.assertEqual(tampered.returncode, 1)
        self.assertIn("does not match manifest", tampered.stderr)

    def test_executable_artifact_is_rejected(self) -> None:
        pack = self.valid_pack()
        (pack / "SKILL.md").chmod(0o755)
        result = run_intake(pack, self.root / "candidate.json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("executable artifact", result.stderr)

    def test_disallowed_extension_is_rejected(self) -> None:
        pack = write_pack(self.root, artifacts={
            "SKILL.md": b"# Practice\n",
            "fixtures/run.sh": b"#!/bin/sh\nrm -rf /\n",
        })
        result = run_intake(pack, self.root / "candidate.json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("extension is not allowed", result.stderr)

    def test_symlink_is_rejected(self) -> None:
        pack = self.valid_pack()
        target = self.root / "outside.txt"
        target.write_text("secret")
        (pack / "fixtures" / "leak.json").symlink_to(target)
        result = run_intake(pack, self.root / "candidate.json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("symlink", result.stderr)

    def test_path_escape_is_rejected(self) -> None:
        pack = self.valid_pack()
        manifest = json.loads((pack / "graft.json").read_text())
        manifest["artifacts"].append({
            "path": "../escape.json", "sha256": "0" * 64, "bytes": 2, "kind": "fixture-data",
        })
        (pack / "graft.json").write_text(json.dumps(manifest))
        result = run_intake(pack, self.root / "candidate.json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("schema validation", result.stderr)

    def test_hidden_file_is_rejected(self) -> None:
        pack = self.valid_pack()
        (pack / ".hidden.md").write_text("invisible instructions")
        result = run_intake(pack, self.root / "candidate.json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("hidden", result.stderr)

    def test_unlisted_file_is_rejected(self) -> None:
        pack = self.valid_pack()
        (pack / "extra.md").write_text("smuggled content")
        result = run_intake(pack, self.root / "candidate.json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not listed in the manifest", result.stderr)

    def test_oversize_artifact_is_rejected(self) -> None:
        pack = self.valid_pack()
        (pack / "big.md").write_bytes(b"x" * (256 * 1024 + 1))
        result = run_intake(pack, self.root / "candidate.json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("exceeds", result.stderr)

    def test_authority_field_on_manifest_is_rejected(self) -> None:
        pack = write_pack(self.root, authority={"level": "promote"})
        result = run_intake(pack, self.root / "candidate.json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("unknown field", result.stderr)

    def test_capability_field_on_claim_is_rejected(self) -> None:
        pack = write_pack(self.root, claims=[{
            "kind": "metric_delta",
            "statement": "Improves throughput by 20 percent.",
            "fixtures": ["fixtures/baseline.json"],
            "capability": "deploy",
        }])
        result = run_intake(pack, self.root / "candidate.json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("unknown field", result.stderr)

    def test_unknown_claim_kind_is_rejected(self) -> None:
        pack = write_pack(self.root, claims=[{
            "kind": "makes_agents_smarter", "statement": "Trust me.", "fixtures": [],
        }])
        result = run_intake(pack, self.root / "candidate.json")
        self.assertEqual(result.returncode, 1)

    def test_claim_requiring_fixture_without_fixture_is_rejected(self) -> None:
        pack = write_pack(self.root, claims=[{
            "kind": "regression_test_distinguishes",
            "statement": "Distinguishes the behavior.",
            "fixtures": [],
        }])
        result = run_intake(pack, self.root / "candidate.json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("requires at least one fixture", result.stderr)

    def test_invalid_fixture_json_is_rejected(self) -> None:
        pack = write_pack(self.root, artifacts={
            "SKILL.md": b"# Practice\n",
            "fixtures/broken.json": b"{not json",
        }, claims=[{
            "kind": "metric_delta",
            "statement": "Improves the measurement.",
            "fixtures": ["fixtures/broken.json"],
        }])
        result = run_intake(pack, self.root / "candidate.json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not valid JSON", result.stderr)

    def test_bad_license_is_rejected(self) -> None:
        pack = write_pack(self.root, license="Proprietary-EULA")
        result = run_intake(pack, self.root / "candidate.json")
        self.assertEqual(result.returncode, 1)

    def test_unsupported_claim_kind_fails_closed(self) -> None:
        pack = write_pack(self.root, claims=[
            {"kind": "regression_test_distinguishes", "statement": "Testable.",
             "fixtures": ["fixtures/baseline.json"]},
            {"kind": "metric_delta", "statement": "Not testable here.",
             "fixtures": ["fixtures/baseline.json"]},
        ])
        out = self.root / "candidate.json"
        result = run_intake(pack, out, "--supported-claims", "regression_test_distinguishes")
        self.assertEqual(result.returncode, 0, result.stderr)
        candidate = json.loads(out.read_text())
        self.assertTrue(candidate["reject_by_default"])
        by_kind = {claim["kind"]: claim for claim in candidate["claims"]}
        self.assertFalse(by_kind["regression_test_distinguishes"]["untestable"])
        self.assertTrue(by_kind["metric_delta"]["untestable"])

    def test_no_aggregation_or_ranking_code_exists(self) -> None:
        source = INTAKE.read_text()
        for forbidden in (
            "attestation_count", "leaderboard", "rank(", "score(",
            "accept_count", "compute_objective",
        ):
            self.assertNotIn(forbidden, source)

    def test_intake_requires_event_scope_with_event(self) -> None:
        pack = self.valid_pack()
        result = run_intake(pack, self.root / "candidate.json", "--event", "events.jsonl")
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
