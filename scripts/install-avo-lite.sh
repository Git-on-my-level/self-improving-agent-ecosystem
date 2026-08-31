#!/bin/sh
set -eu

repo="https://github.com/Git-on-my-level/avo-lite.git"
ref="9df79c9ba33954a8e076f95b0af3028ad4666e38"
prefix=".tools/avo-lite"

usage() {
  echo "usage: $0 [--prefix DIR] [--ref COMMIT_OR_TAG] [--repo URL]" >&2
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --prefix) [ "$#" -ge 2 ] || { usage; exit 2; }; prefix=$2; shift 2 ;;
    --ref) [ "$#" -ge 2 ] || { usage; exit 2; }; ref=$2; shift 2 ;;
    --repo) [ "$#" -ge 2 ] || { usage; exit 2; }; repo=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
done

command -v git >/dev/null 2>&1 || { echo "git is required" >&2; exit 2; }
[ ! -e "$prefix" ] || { echo "refusing to overwrite existing path: $prefix" >&2; exit 1; }

parent=$(dirname "$prefix")
mkdir -p "$parent"
tmp=$(mktemp -d "$parent/.avo-lite-install.XXXXXX")
cleanup() {
  [ ! -d "$tmp" ] || rm -rf "$tmp"
}
trap cleanup 0 HUP INT TERM

git clone --filter=blob:none --no-checkout "$repo" "$tmp/repo"
if ! git -C "$tmp/repo" fetch --depth 1 origin "$ref"; then
  echo "unable to fetch requested AVO-lite ref: $ref" >&2
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

mv "$tmp/repo" "$prefix"
rmdir "$tmp"
trap - 0 HUP INT TERM

echo "Installed AVO-lite source at $prefix"
echo "Revision: $actual"
echo "Inspect $prefix/README.md and $prefix/SKILL.md before execution."
echo "Then add $prefix/scripts to PATH explicitly."
