#!/bin/sh
set -eu

# Fetch a graft pack without executing any of it. Unlike install-avo-lite.sh,
# --ref is required: imports must be reproducible, so a pack is always pinned.

repo=""
ref=""
prefix=""
subdir="."

usage() {
  echo "usage: $0 --repo URL --ref COMMIT_OR_TAG --prefix DIR [--subdir PATH]" >&2
  echo "Fetches the pack source at a pinned ref into DIR. Never executes pack content." >&2
  echo "After fetching, run scripts/graft-intake.py to validate and digest the pack." >&2
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo) [ "$#" -ge 2 ] || { usage; exit 2; }; repo=$2; shift 2 ;;
    --ref) [ "$#" -ge 2 ] || { usage; exit 2; }; ref=$2; shift 2 ;;
    --prefix) [ "$#" -ge 2 ] || { usage; exit 2; }; prefix=$2; shift 2 ;;
    --subdir) [ "$#" -ge 2 ] || { usage; exit 2; }; subdir=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
done

[ -n "$repo" ] || { usage; exit 2; }
[ -n "$ref" ] || { echo "refusing to install without --ref: pack imports must be pinned" >&2; exit 2; }
[ -n "$prefix" ] || { usage; exit 2; }

command -v git >/dev/null 2>&1 || { echo "git is required" >&2; exit 2; }
[ ! -e "$prefix" ] || { echo "refusing to overwrite existing path: $prefix" >&2; exit 1; }

parent=$(dirname "$prefix")
mkdir -p "$parent"
tmp=$(mktemp -d "$parent/.graft-install.XXXXXX")
cleanup() {
  [ ! -d "$tmp" ] || rm -rf "$tmp"
}
trap cleanup 0 HUP INT TERM

git clone --filter=blob:none --no-checkout "$repo" "$tmp/repo"
if ! git -C "$tmp/repo" fetch --depth 1 origin "$ref"; then
  echo "unable to fetch requested graft ref: $ref" >&2
  exit 1
fi
git -C "$tmp/repo" checkout --detach FETCH_HEAD
actual=$(git -C "$tmp/repo" rev-parse HEAD)

case "$ref" in
  [0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]*)
    case "$actual" in
      "$ref"*) ;;
      *) echo "fetched commit $actual does not match requested $ref" >&2; exit 1 ;;
    esac
    ;;
esac

if [ ! -f "$tmp/repo/$subdir/graft.json" ]; then
  echo "no graft.json found under $subdir at revision $actual" >&2
  exit 1
fi

mkdir "$prefix"
# Copy declared pack content only: data files, never permissions, never hooks.
cp -R "$tmp/repo/$subdir/." "$prefix/"
find "$prefix" -type f -exec chmod 644 {} +
find "$prefix" -type d -exec chmod 755 {} +

rmdir "$tmp" 2>/dev/null || true
rm -rf "$tmp/repo"
trap - 0 HUP INT TERM

echo "Fetched graft pack source at $prefix"
echo "Source: $repo"
echo "Revision: $actual"
echo "Record this commit and the pack digest printed by scripts/graft-intake.py:"
echo "  python3 scripts/graft-intake.py --pack $prefix --out candidate.json"
echo "Inspect the artifacts before intake; nothing here has been executed."
