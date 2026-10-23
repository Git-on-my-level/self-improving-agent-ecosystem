# Grafts

A graft is a portable pack of practices and data-only evidence contributed from
outside a loop. The name is the trust model: a graft carries no authority of its
own and only takes if the host's own tissue accepts it. Installing a graft
creates a proposal in your loop, never state. This is the kit's answer to
"can self-improving agents learn from others?": yes for practices and data,
deliberately no for another loop's accepted state.

## What a pack is

A pack is a directory of data-only artifacts plus one `graft.json` manifest:

- `skill-doc` and `runbook-doc` artifacts are prose;
- `fixture-data` artifacts are JSON documents;
- `claims` are falsifiable statements with a `kind` from a closed enum owned by
  [schemas/graft.schema.json](../schemas/graft.schema.json):
  - `regression_test_distinguishes` — the fixture data distinguishes the
    claimed behavior on the parent revision;
  - `metric_delta` — the practice improved a measurement; reproduce the delta
    with your own scorer against a contemporaneous baseline;
  - `invariant_documentation` — the pack documents an invariant your gate
    should encode and test.

Packs never ship executable content or scoring code, and the manifest is
structurally closed: authority, capability, threshold, and score fields cannot
be declared at all. Claim kinds a pack may declare are fixed by schema revision
only.

## Intake

```bash
# Fetch pinned, never executed (a ref is required; imports must be reproducible).
./scripts/install-graft.sh --repo URL --ref COMMIT --prefix .grafts/example-pack

# Validate, digest, and convert to an observe->propose candidate.
python3 scripts/graft-intake.py --pack .grafts/example-pack --out candidates/graft-example.json

# Optionally record the intake in your ledger.
python3 scripts/graft-intake.py --pack .grafts/example-pack --out candidates/graft-example.json \
  --event events.jsonl --ecosystem my-ecosystem --loop my-loop
```

Intake fails closed on anything that is not plain data: symlinks, absolute or
escaping paths, executable bits, disallowed extensions, hidden files, files not
listed in the manifest, hash mismatches, and oversize packs. It computes a
canonical pack digest (sha256 over the sorted per-file `(path, sha256)` list),
so the pack is pinned by content, not by a mutable ref. Re-running intake on an
unchanged pack is deterministic; any changed byte changes the digest.

From there the imported practice is an ordinary candidate. Your own hard gate
and adversarial verifier judge every claim — including the
[evaluator-contract](evaluator-contract.md) rule that a
`regression_test_distinguishes` claim must be confirmed to fail on the parent
revision, using your scorer over the pack's data fixtures. Pass
`--supported-claims` with the claim kinds your loop can actually test; any
other kind is marked untestable and the candidate is emitted with
`reject_by_default: true`. Untestable claims fail closed; they are never
skipped silently. Rejection is evidence: it writes `candidate_rejected` and
stays in your ledger.

## Attestations are receipts, not a leaderboard

No new ledger exists. An attestation is your loop's own receipt, made
shareable by two existing mechanisms:

1. `pack_intake_recorded` binds the candidate to `pack:<digest>`, the source,
   and the claim kinds.
2. The subsequent `candidate_accepted` or `candidate_rejected` receipt already
   carries your loop id, your evaluator revision, and evidence refs.

The effective shared record is therefore boolean — accepted or not, under your
evaluator revision, with a link to your receipt. It deliberately carries no
score or delta: scores are not comparable across evaluator revisions, and a
cross-loop magnitude would be a leaderboard, which is a Goodhart surface. Three
rules hold by construction and must keep holding:

- Attestations are pull-only signal. A loop must not weigh attestation counts
  in any gate or objective.
- This kit ships no aggregation, ranking, or attestation-counting code, and
  must never.
- Identity on an attestation is self-asserted, which is harmless because
  attestations confer zero authority: every consumer re-verifies through its
  own gate, so a Sybil farm of fake acceptances buys nothing.

## Known-packs index

[packs/README.md](../packs/README.md) is a curated pointer table updated by
PRs. Listing is directory assistance, not validation: an indexed pack has been
looked at, not green-lit. Entries are contributor-asserted with a resolved
commit and a last-verified digest and date; the digest lets you check that what
you fetch is what was indexed.

## Non-goals

- Centralized green-lighting, quality scoring, or approval of packs.
- A central A/B farm or shared eval environment.
- Cross-loop dedup, aggregation, or ranking of packs or practices.
- Pack-supplied code, scoring logic, thresholds, or authority.
- Attestation aggregation of any kind.
