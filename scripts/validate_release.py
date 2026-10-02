"""Record reproducible cases without overwriting any previous run."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from amdfm.analysis import code_digest, review
from amdfm.comparison import compare_designs
from amdfm.detail import attach_detail, run_detail
from amdfm.io import load_model
from amdfm.models import json_bytes
from amdfm.orientation import measure_orientation
from amdfm.presentation import html_report
from amdfm.profiles import Profile


def record(out):
    out.mkdir(parents=True,exist_ok=False)
    summary={"timestamp_utc":datetime.now(timezone.utc).isoformat(),"code_sha256":code_digest(),
        "timing_scope":"One local run; wall clock including worker startup for detail. No general speedup claim.",
        "external":[],"sphere":[],"original_files":[]}
    # Git blob comparison protects the 24 original repository artifacts, including ZIP/PDF/DOCX.
    listing=subprocess.check_output(["git","ls-tree","-r","-z","1706eac"],cwd=ROOT)
    for item in listing.split(b"\0"):
        if not item:continue
        meta,name=item.split(b"\t",1)
        path=ROOT/name.decode("utf-8")
        expected=meta.decode().split()[2]
        current=subprocess.check_output(["git","hash-object","--",str(path)],cwd=ROOT).decode().strip()
        summary["original_files"].append({"path":path.relative_to(ROOT).as_posix(),
            "expected_git_blob":expected,"current_git_blob":current,"unchanged":current==expected,
            "sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
    summary["originals_unchanged"]=all(x["unchanged"] for x in summary["original_files"])
    assert summary["originals_unchanged"]
    (out/"summary.json").write_bytes(json_bytes(summary))
    for path in sorted((ROOT/"examples/external").glob("*.stl")):
        started=time.perf_counter()
        model=load_model(path.read_bytes(),path.name)
        loaded=time.perf_counter()-started
        profile=Profile()
        report=review(model,profile)
        quick_seconds=report["elapsed_seconds"]
        (out/f"{path.stem}_quick.json").write_bytes(json_bytes(report))
        details={}
        for mode,limit in (("wall",60),("layers",90)):
            started=time.perf_counter()
            detail=run_detail(model,profile,mode=mode,timeout_s=limit)
            details[mode]={"status":detail["status"],"seconds":time.perf_counter()-started,
                "reason":detail.get("reason"),"expected_layers":detail.get("expected_layers"),
                "complete_layers":detail.get("complete_layers"),
                "minimum_mm":detail.get("measurements",{}).get("minimum_mm")}
            report=attach_detail(report,detail)
            print(json.dumps({"file":path.name,"detail":mode,**details[mode]},ensure_ascii=False),flush=True)
        (out/f"{path.stem}_full.json").write_bytes(json_bytes(report))
        (out/f"{path.stem}_report.html").write_bytes(html_report(report))
        summary["external"].append({"file":path.name,"source_sha256":model.metadata["source_sha256"],
            "extents_mm_assumed":model.mesh.extents.tolist(),"triangles":len(model.mesh.faces),
            "load_seconds":loaded,"quick_seconds":quick_seconds,
            "surface_components":model.metadata["surface_component_count"],"details":details})
        (out/"summary.json").write_bytes(json_bytes(summary))
    # Independent analytic curved-surface reference; do not assume monotone refinement.
    sphere=ROOT/"examples/cad/12_sphere.step"
    analytic=math.pi*10**2*math.sin(math.radians(45))**2
    for deflection in (.05,.005,.001):
        model=load_model(sphere.read_bytes(),sphere.name,deflection_mm=deflection)
        value=measure_orientation(model.mesh,(0,0,1),Profile())["overhang_projected_area_sum_mm2"]
        summary["sphere"].append({"radius_mm":10,"angle_deg":45,"deflection_mm":deflection,
            "triangles":len(model.mesh.faces),"analytic_projection_mm2":analytic,"mesh_projection_mm2":value,
            "relative_error_percent":100*(value-analytic)/analytic})
    cases={}
    profile=Profile(minimum_wall_mm=1.,threshold_basis="Developer comparison scenario: 1 mm; not a universal process limit")
    for name in ("02_thin_plate","14_thin_plate_improved","04_horizontal_hole","05_sealed_cavity"):
        path=ROOT/"examples/cad"/f"{name}.step"
        model=load_model(path.read_bytes(),path.name)
        report=attach_detail(review(model,profile),run_detail(model,profile))
        cases[name]=report
        (out/f"{name}.json").write_bytes(json_bytes(report))
        (out/f"{name}.html").write_bytes(html_report(report))
    comparison=compare_designs(cases["02_thin_plate"],cases["14_thin_plate_improved"])
    (out/"thin_plate_comparison.json").write_bytes(json_bytes(comparison))
    summary["complete"]=True
    (out/"summary.json").write_bytes(json_bytes(summary))
    return summary


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    record(args.out.resolve())
