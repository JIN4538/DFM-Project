"""Audit checked RL arbitration on untouched generated scenarios and STEP files."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    from amdfm.io import load_model
    from dfm.machining import MachiningProfile, review_machining
    from dfm import plan_learning as prior
    from dfm.enhanced_planning import recommend_plan
    from dfm.rl_planner import evaluate_changes
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--scenarios",type=Path,required=True)
    parser.add_argument("--skip-cad",action="store_true")
    args=parser.parse_args()
    if args.output.exists():raise ValueError("출력은 새 파일 경로여야 합니다")
    args.output.parent.mkdir(parents=True,exist_ok=True)
    scenarios=json.load(gzip.open(args.scenarios,"rt",encoding="utf-8"))["test"]
    records=[]
    with tempfile.TemporaryDirectory() as directory:
        feedback=Path(directory)/"empty-preferences.json"
        def inspect(report,prefs,identity):
            start=time.perf_counter()
            before=prior.recommend_plan(report,preferences=prefs,feedback_path=feedback)
            after=recommend_plan(report,preferences=prefs,feedback_path=feedback)
            reinforcement=after.get("reinforcement_planning",{})
            item=dict(identity=identity,preferences=prefs,status=after["status"],adopted=reinforcement.get("adopted",False),
                      proposal_status=reinforcement.get("status"),reason=reinforcement.get("reason"),elapsed_seconds=time.perf_counter()-start,
                      source=after.get("selection_source"))
            if before.get("selected") and after.get("selected"):
                first=evaluate_changes(report,before["selected"]["changes"],preferences=prefs)
                last=evaluate_changes(report,after["selected"]["changes"],preferences=prefs)
                item.update(before=[first["conflicts"],first["cost"]],after=[last["conflicts"],last["cost"]],
                            changes=after["selected"]["changes"],remaining=after["selected"]["remaining"],
                            worse=last["conflicts"]>first["conflicts"] or last["conflicts"]==first["conflicts"] and last["cost"]>first["cost"]+1e-9)
            records.append(item)
        for item in scenarios:
            inspect(item["report"],item["preferences"],dict(kind="procedural_test",id=item["id"],family=item["family"]))
        for path in ([] if args.skip_cad else sorted((ROOT/"examples/machining").glob("*.step"))):
            raw=path.read_bytes()
            model=load_model(raw,path.name)
            for d,f,r in ((12.,4.,6.),(3.,15.,20.)):
                report=review_machining(model,MachiningProfile(tool_diameter_mm=d,flute_length_mm=f,reach_mm=r,hole_depth_ratio_limit=4.))
                for prefs in ({},{"preserve_geometry":True},{"allow_tool_change":False}):
                    inspect(report,prefs,dict(kind="existing_STEP",path=path.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(raw).hexdigest(),tool=[d,f,r]))
    summary={}
    for kind in ("procedural_test","existing_STEP"):
        rows=[r for r in records if r["identity"]["kind"]==kind]
        summary[kind]=dict(count=len(rows),adopted=sum(r["adopted"] for r in rows),worse=sum(r.get("worse",False) for r in rows),
                           unavailable=sum(r["proposal_status"]=="unavailable" for r in rows),
                           mean_seconds=sum(r["elapsed_seconds"] for r in rows)/max(1,len(rows)))
    result=dict(created_utc=datetime.now(timezone.utc).isoformat(),summary=summary,records=records,
                runtime_sha256=hashlib.sha256((ROOT/"dfm/rl_planner.py").read_bytes()).hexdigest(),
                arbitration_sha256=hashlib.sha256((ROOT/"dfm/enhanced_planning.py").read_bytes()).hexdigest())
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    print(json.dumps(summary))
    if any(r.get("worse",False) for r in records):raise SystemExit("검증된 기존안보다 나쁜 추천이 있습니다")


if __name__=="__main__":main()
