#!/usr/bin/env python3
"""Convert terminal AVO ledger entries into idempotent ecosystem events."""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, pathlib, sys
from typing import Any

def digest(path: pathlib.Path) -> str | None:
    if not path.is_file(): return None
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--ledger", type=pathlib.Path, required=True)
    ap.add_argument("--ecosystem", type=pathlib.Path, required=True, help="ecosystem.json")
    ap.add_argument("--loop", required=True)
    ap.add_argument("--evaluator-revision", required=True)
    ap.add_argument("--output", type=pathlib.Path)
    a=ap.parse_args()
    manifest=json.loads(a.ecosystem.read_text())
    loop={x["id"]:x for x in manifest.get("loops",[])}.get(a.loop)
    if not loop:
        print(f"unknown loop: {a.loop}", file=sys.stderr); return 2
    run_root=a.ledger.parent
    events=[]
    mapping={"accept":"candidate_accepted","reject":"candidate_rejected","error":"candidate_rejected"}
    for raw in a.ledger.read_text().splitlines():
        if not raw.strip(): continue
        item=json.loads(raw); action=item.get("action")
        if action not in mapping or int(item.get("tick",0)) <= 0: continue
        tick=int(item["tick"]); diff=str(item.get("diff_hash") or "none")
        candidate=f"avo:{a.loop}:{tick}:{diff}"
        run_dir=run_root / str(item.get("run_dir") or "")
        evidence=[]
        for rel in ("score.json","verify.json","diff.patch"):
            d=digest(run_dir/rel)
            if d: evidence.append({"uri":str((run_dir/rel).relative_to(run_root)),"digest":d,"observed_at":None})
        accepted=item.get("commit") if action=="accept" else None
        status="ok" if action=="accept" else ("failed" if action=="error" else "rejected")
        event={
          "schema_version":1,
          "event_id":f"avo-{a.loop}-{tick}-{diff}",
          "type":mapping[action], "occurred_at":now(), "ecosystem":manifest["name"], "loop":a.loop,
          "candidate_id":candidate, "idempotency_key":f"avo:{a.loop}:{tick}:{diff}:{action}",
          "actor":{"role":loop["driver"]["role"],"implementation":"avo-lite","model":item.get("agent_model") or None,"provider":None},
          "lineage":{"base_revision":item.get("parent"),"candidate_revision":candidate,"accepted_revision":accepted,
                     "promoted_revision":None,"deployed_revision":None,"evaluator_revision":a.evaluator_revision,"artifact_digest":None},
          "evidence":evidence,
          "result":{"status":status,"reason":str(item.get("note") or action),"correct":item.get("correct"),
                    "objective":item.get("objective"),"metrics":item.get("metrics") or {}},
          "authority":{"level":loop.get("authority","propose"),"decision":"allowed","approver":None},
          "extensions":{"avo":{"tick":tick,"action":action,"diff_hash":diff,"verify":item.get("verify")}},
        }
        events.append(event)
    text="".join(json.dumps(e,sort_keys=True,separators=(",",":"))+"\n" for e in events)
    if a.output:
        a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(text)
    else: sys.stdout.write(text)
    return 0
if __name__ == "__main__": raise SystemExit(main())
