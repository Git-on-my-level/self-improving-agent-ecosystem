#!/usr/bin/env python3
"""Validate a graft pack and convert it into an observe->propose candidate.

A graft is external material (practices, runbooks, fixture data) that arrives
as evidence, never as trusted state. This script is the intake gate boundary:

- it validates the pack manifest against schemas/graft.schema.json;
- it rejects anything that is not data (executables, symlinks, path escapes,
  hidden files, unlisted files, oversize artifacts);
- it recomputes per-file sha256 and the canonical pack digest;
- it emits a candidate file and (optionally) one pack_intake_recorded event.

It never scores, ranks, or accepts anything: the importing loop's own
correctness gate and adversarial verifier decide, and rejection is evidence.
This script intentionally contains no aggregation, ranking, or attestation
counting of any kind.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import stat
import sys

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from validate import Findings, validate_schema_instance  # noqa: E402

ALLOWED_EXTENSIONS = {".md", ".json", ".txt"}
MAX_ARTIFACT_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 1024 * 1024
MAX_ARTIFACTS = 64
MAX_TITLE = 120
MAX_DESCRIPTION = 1000
MAX_STATEMENT = 500
CLAIM_KINDS = {
    "regression_test_distinguishes", "metric_delta", "invariant_documentation",
}
CLAIM_KINDS_REQUIRING_FIXTURES = {"regression_test_distinguishes", "metric_delta"}


class IntakeError(Exception):
    """A named rejection reason; intake fails closed on any of these."""


def fail(message: str) -> IntakeError:
    return IntakeError(message)


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pack_digest(pairs: list[list[str]]) -> str:
    """Canonical pack digest: sha256 over sorted (path, file-sha256) pairs."""
    canonical = json.dumps(sorted(pairs), separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def check_relative_path(relative: pathlib.PurePosixPath) -> None:
    parts = relative.parts
    if not parts:
        raise fail("artifact path is empty")
    if relative.is_absolute() or str(relative).startswith("/"):
        raise fail(f"artifact path is absolute: {relative}")
    if ".." in parts or "." in parts:
        raise fail(f"artifact path escapes or tricks its root: {relative}")
    for part in parts:
        if part.startswith("."):
            raise fail(f"artifact path contains hidden component: {relative}")
        if "\\" in part or "\x00" in part:
            raise fail(f"artifact path contains forbidden character: {relative}")
    if relative.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise fail(f"artifact extension is not allowed: {relative}")


def scan_pack_files(pack_dir: pathlib.Path) -> list[pathlib.Path]:
    found: list[pathlib.Path] = []
    for path in sorted(pack_dir.rglob("*")):
        relative = pathlib.PurePosixPath(path.relative_to(pack_dir).as_posix())
        if path.is_file() and relative.as_posix() == "graft.json":
            continue  # the manifest itself is not a pack artifact
        if path.is_symlink():
            raise fail(f"symlink is not allowed: {relative}")
        if path.is_dir():
            if path.name.startswith("."):
                raise fail(f"hidden directory is not allowed: {relative}")
            continue
        if not path.is_file():
            raise fail(f"artifact is not a regular file: {relative}")
        check_relative_path(relative)
        mode = path.stat().st_mode
        if mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
            raise fail(f"executable artifact is not allowed: {relative}")
        size = path.stat().st_size
        if size > MAX_ARTIFACT_BYTES:
            raise fail(f"artifact exceeds {MAX_ARTIFACT_BYTES} bytes: {relative}")
        found.append(path)
        if len(found) > MAX_ARTIFACTS:
            raise fail(f"pack exceeds {MAX_ARTIFACTS} artifacts")
    total = sum(path.stat().st_size for path in found)
    if total > MAX_TOTAL_BYTES:
        raise fail(f"pack exceeds {MAX_TOTAL_BYTES} total bytes")
    return found


def load_manifest(pack_dir: pathlib.Path, findings: Findings) -> dict:
    manifest_path = pack_dir / "graft.json"
    try:
        manifest = json.loads(manifest_path.read_text())
    except FileNotFoundError:
        raise fail("missing graft.json manifest")
    except (OSError, json.JSONDecodeError) as exc:
        raise fail(f"cannot read graft.json: {exc}")
    if not isinstance(manifest, dict):
        raise fail("graft.json must contain one JSON object")
    schema = json.loads((REPO_ROOT / "schemas" / "graft.schema.json").read_text())
    validate_schema_instance(manifest, schema, "graft.json", findings)
    if findings.errors:
        raise fail("manifest failed schema validation: " + findings.errors[0])
    if len(manifest["title"]) > MAX_TITLE:
        raise fail(f"title exceeds {MAX_TITLE} characters")
    if len(manifest["description"]) > MAX_DESCRIPTION:
        raise fail(f"description exceeds {MAX_DESCRIPTION} characters")
    return manifest


def cross_check_artifacts(manifest: dict, pack_dir: pathlib.Path, found: list[pathlib.Path]) -> dict[str, dict]:
    declared = {item["path"]: item for item in manifest["artifacts"]}
    if len(declared) != len(manifest["artifacts"]):
        raise fail("manifest lists duplicate artifact paths")
    actual = {
        path.relative_to(pack_dir).as_posix(): path for path in found
    }
    unlisted = sorted(set(actual) - set(declared))
    if unlisted:
        raise fail(f"pack contains files not listed in the manifest: {unlisted[0]}")
    missing = sorted(set(declared) - set(actual))
    if missing:
        raise fail(f"manifest lists artifacts that are absent: {missing[0]}")
    for relative, item in declared.items():
        path = actual[relative]
        if int(item["bytes"]) != path.stat().st_size:
            raise fail(f"artifact size does not match manifest: {relative}")
    return declared


def verify_fixtures(manifest: dict, pack_dir: pathlib.Path, artifacts: dict[str, dict]) -> list[dict]:
    fixture_paths = {
        item["path"] for item in artifacts.values() if item["kind"] == "fixture-data"
    }
    resolved_claims: list[dict] = []
    for index, claim in enumerate(manifest["claims"]):
        if claim["kind"] not in CLAIM_KINDS:
            raise fail(f"claims[{index}].kind is not a known claim kind")
        if len(claim["statement"]) > MAX_STATEMENT:
            raise fail(f"claims[{index}].statement exceeds {MAX_STATEMENT} characters")
        for fixture in claim["fixtures"]:
            if fixture not in artifacts:
                raise fail(f"claims[{index}] references unknown artifact: {fixture}")
            if fixture not in fixture_paths:
                raise fail(f"claims[{index}] fixture is not fixture-data: {fixture}")
            fixture_path = pack_dir / fixture
            try:
                json.loads(fixture_path.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                raise fail(f"fixture is not valid JSON ({fixture}): {exc}")
        if claim["kind"] in CLAIM_KINDS_REQUIRING_FIXTURES and not claim["fixtures"]:
            raise fail(f"claims[{index}] kind {claim['kind']} requires at least one fixture")
        resolved_claims.append(dict(claim))
    return resolved_claims


def build_candidate(
    manifest: dict,
    pack_dir: pathlib.Path,
    artifacts: dict[str, dict],
    digest: str,
    supported_claims: set[str] | None,
) -> dict:
    claims = []
    for claim in manifest["claims"]:
        untestable = supported_claims is not None and claim["kind"] not in supported_claims
        claims.append({
            "kind": claim["kind"],
            "statement": claim["statement"],
            "fixtures": claim["fixtures"],
            "untestable": untestable,
        })
    return {
        "schema_version": 1,
        "candidate_id": f"graft-{digest[:12]}",
        "source": {
            "kind": "graft",
            "pack": manifest["pack"],
            "pack_digest": digest,
            "source_repo": manifest["source"]["repo"],
            "source_ref": manifest["source"]["ref"],
        },
        "claims": claims,
        "artifacts": [
            {"path": path_rel, "sha256": item["sha256"], "kind": item["kind"]}
            for path_rel, item in sorted(artifacts.items())
        ],
        "reject_by_default": any(claim["untestable"] for claim in claims),
        "note": (
            "External evidence from graft pack. Not trusted state: the importing "
            "loop's own correctness gate and adversarial verifier must judge every "
            "claim. Claims marked untestable must fail closed. Fixture data is "
            "data-only; run your own scorer over it."
        ),
    }


def build_event(
    manifest: dict,
    digest: str,
    candidate: dict,
    ecosystem: str,
    loop: str,
    actor_role: str,
    now: str,
) -> dict:
    return {
        "schema_version": 1,
        "event_id": f"graft-{digest[:16]}",
        "type": "pack_intake_recorded",
        "occurred_at": now,
        "ecosystem": ecosystem,
        "loop": loop,
        "candidate_id": candidate["candidate_id"],
        "idempotency_key": f"graft-intake:{digest}",
        "actor": {"role": actor_role, "implementation": "scripts/graft-intake.py"},
        "lineage": {"artifact_digest": digest},
        "evidence": [
            {"uri": f"pack:{digest}", "digest": digest, "observed_at": now},
            {"uri": manifest["source"]["repo"], "digest": digest, "observed_at": now},
        ],
        "result": {
            "status": "ok",
            "reason": (
                f"graft {manifest['pack']} intake recorded; "
                f"claims awaiting the loop's own gate: "
                f"{', '.join(claim['kind'] for claim in manifest['claims'])}"
            ),
        },
        "authority": {"level": "propose", "decision": "allowed"},
        "extensions": {
            "graft": {
                "pack": manifest["pack"],
                "pack_digest": digest,
                "source_ref": manifest["source"]["ref"],
                "claim_kinds": [claim["kind"] for claim in manifest["claims"]],
                "reject_by_default": candidate["reject_by_default"],
            }
        },
    }


def run_intake(
    pack_dir: pathlib.Path,
    out_path: pathlib.Path,
    event_path: pathlib.Path | None,
    ecosystem: str,
    loop: str,
    actor_role: str,
    supported_claims: set[str] | None,
) -> int:
    findings = Findings()
    try:
        manifest = load_manifest(pack_dir, findings)
        found = scan_pack_files(pack_dir)
        artifacts = cross_check_artifacts(manifest, pack_dir, found)
        actual_pairs = []
        for relative, item in artifacts.items():
            actual = sha256_file(pack_dir / relative)
            if actual != item["sha256"]:
                raise fail(f"artifact sha256 does not match manifest: {relative}")
            actual_pairs.append([relative, actual])
        digest = pack_digest(actual_pairs)
        resolved_claims = verify_fixtures(manifest, pack_dir, artifacts)
        manifest = dict(manifest)
        manifest["claims"] = resolved_claims
        candidate = build_candidate(manifest, pack_dir, artifacts, digest, supported_claims)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(candidate, indent=2) + "\n")
        if event_path is not None:
            now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
            event = build_event(
                manifest, digest, candidate, ecosystem, loop, actor_role, now,
            )
            event_schema = json.loads((REPO_ROOT / "schemas" / "event.schema.json").read_text())
            event_findings = Findings()
            validate_schema_instance(event, event_schema, "event", event_findings)
            if event_findings.errors:
                raise fail("generated event failed schema validation: " + event_findings.errors[0])
            with event_path.open("a") as handle:
                handle.write(json.dumps(event) + "\n")
    except IntakeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"graft intake recorded: {candidate['candidate_id']}")
    print(f"pack: {manifest['pack']} digest: {digest}")
    print(f"candidate: {out_path}")
    if candidate["reject_by_default"]:
        print(
            "warning: candidate contains claim kinds outside --supported-claims; "
            "reject_by_default is set and the gate must fail closed",
            file=sys.stderr,
        )
    if event_path is not None:
        print(f"event appended: {event_path}")
    print("The candidate carries no authority: your gate and verifier decide next.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=pathlib.Path, required=True, help="graft pack directory")
    parser.add_argument("--out", type=pathlib.Path, required=True, help="candidate JSON output path")
    parser.add_argument("--event", type=pathlib.Path, help="events.jsonl to append one pack_intake_recorded event to")
    parser.add_argument("--ecosystem", help="ecosystem name for the event (required with --event)")
    parser.add_argument("--loop", help="loop id for the event (required with --event)")
    parser.add_argument("--actor-role", default="sensor", help="actor role recorded on the event (default: sensor)")
    parser.add_argument(
        "--supported-claims",
        help="comma-separated claim kinds this loop can test; unlisted kinds fail closed",
    )
    args = parser.parse_args()
    if (args.event is not None) and (not args.ecosystem or not args.loop):
        parser.error("--event requires --ecosystem and --loop")
    supported = None
    if args.supported_claims:
        supported = {item.strip() for item in args.supported_claims.split(",") if item.strip()}
    return run_intake(
        pack_dir=args.pack.resolve(),
        out_path=args.out.resolve(),
        event_path=args.event.resolve() if args.event else None,
        ecosystem=args.ecosystem or "",
        loop=args.loop or "",
        actor_role=args.actor_role,
        supported_claims=supported,
    )


if __name__ == "__main__":
    raise SystemExit(main())
