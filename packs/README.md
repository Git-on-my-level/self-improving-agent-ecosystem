# Known graft packs

**Listing is directory assistance, not validation.** An entry here means a
human looked at the pack and recorded what they saw. It does not mean the pack
works, and it never means it is approved. Every importing loop still runs its
own correctness gate and adversarial verifier; see
[docs/grafts.md](../docs/grafts.md).

Entries are contributor-asserted via PR. Each entry pins the source repo, the
commit the digest was computed at, and the canonical pack digest from
`scripts/graft-intake.py` (sha256 over the sorted per-file `(path, sha256)`
list). After the pack changes upstream, its digest changes; update the row or
the row simply stops matching what you fetch. Old digests are never revoked;
they are just content that is no longer referenced.

| Pack | Source | Commit | Digest (first 16) | Claim kinds | Last verified | Notes |
| ---- | ------ | ------ | ----------------- | ----------- | ------------- | ----- |
| _(none indexed yet — add yours via PR)_ | | | | | | |

To add an entry:

1. Install and intake the pack yourself:
   `./scripts/install-graft.sh --repo URL --ref COMMIT --prefix .grafts/<pack>`
   then `python3 scripts/graft-intake.py --pack .grafts/<pack> --out /tmp/candidate.json`.
2. Record the full digest it prints, truncated to 16 hex characters in the
   table, plus the claim kinds and the date you ran intake.
3. Say in the PR description what the pack claims and what you verified locally.
   PR review covers provenance and safety (data-only, no authority fields); it
   is not a validation of the claims.
