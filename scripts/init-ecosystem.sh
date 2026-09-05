#!/bin/sh
set -eu

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  echo "usage: $0 TARGET_DIR ECOSYSTEM_NAME [local|project|live]" >&2
  exit 2
fi

target=$1
name=$2
profile=${3:-project}
case "$profile" in local|project|live) ;; *) echo "profile must be local, project, or live" >&2; exit 2;; esac
printf '%s\n' "$name" | grep -Eq '^[a-z][a-z0-9-]{1,62}$' || {
  echo "ecosystem name must be lowercase kebab-case" >&2
  exit 2
}

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(dirname "$script_dir")

if [ -e "$target" ] && [ "$(find "$target" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l | tr -d ' ')" -ne 0 ]; then
  echo "refusing to write into non-empty target: $target" >&2
  exit 1
fi

mkdir -p "$target" "$target/evaluators" "$target/fixtures" \
  "$target/sensors" "$target/adapters" "$target/promotion" "$target/health"

for file in ecosystem.json policy.json events.jsonl README.md MISSION.md; do
  sed "s/__ECOSYSTEM_NAME__/$name/g" "$repo_root/templates/$file" > "$target/$file"
done
python3 - "$target/ecosystem.json" "$profile" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1]); profile = sys.argv[2]
data = json.loads(path.read_text()); data["profile"] = profile
if profile == "local":
    data["state"].pop("offsite_backup", None)
    data["health"]["deadman"] = "local-process-only"
elif profile == "live":
    # Keep explicit fail-closed placeholders so validation forces operators to replace them.
    data["state"]["offsite_backup"] = "declare-before-unattended-use"
    data["health"]["deadman"] = "declare-external-observer-before-unattended-use"
path.write_text(json.dumps(data, indent=2) + "\n")
PY
cp "$repo_root/examples/controlled-outcome/score.py" "$target/evaluators/score.py"
cp "$repo_root/examples/controlled-outcome/verify.py" "$target/evaluators/verify.py"
cp -R "$repo_root/examples/controlled-outcome/fixtures/." "$target/fixtures/"
cp "$repo_root/templates/stubs/sensors/collect.sh" "$target/sensors/collect.sh"
cp "$repo_root/templates/stubs/adapters/agent.sh" "$target/adapters/agent.sh"
cp "$repo_root/templates/stubs/promotion/reconcile.sh" "$target/promotion/reconcile.sh"
cp "$repo_root/templates/stubs/promotion/rollback.sh" "$target/promotion/rollback.sh"
cp "$repo_root/templates/stubs/health/export.sh" "$target/health/export.sh"
chmod +x "$target"/evaluators/*.py "$target"/sensors/*.sh \
  "$target"/adapters/*.sh "$target"/promotion/*.sh "$target"/health/*.sh

echo "Initialized $name ($profile profile) at $target"
echo "The generated commands fail closed until you replace their stubs."
echo "Run: python3 $repo_root/scripts/validate.py $target"
