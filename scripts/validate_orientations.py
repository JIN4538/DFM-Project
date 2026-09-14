"""Write a fresh analytic audit and optional external-mesh timing record."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

import numpy as np
import trimesh

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from amdfm.analysis import code_digest, review
from amdfm.io import load_model
from amdfm.orientation import measure_orientation
from amdfm.profiles import Profile


def validate(out):
    out.mkdir(parents=True,exist_ok=False)
    lengths=np.array([7.,13.,29.])
    areas=np.array([13*29,7*29,7*13])
    mesh=trimesh.creation.box(extents=lengths)
    vectors=np.random.default_rng(824).normal(size=(1000,3))
    vectors/=np.linalg.norm(vectors,axis=1)[:,None]
    audit=[]
    for angle in (45.,63.):
        errors=np.zeros(4)
        for d in vectors:
            r=measure_orientation(mesh,d,Profile(overhang_angle_deg=angle))
            mask=np.abs(d)>np.cos(np.deg2rad(angle))
            expected_area=float(np.dot(areas[mask],np.abs(d[mask])))
            rotation=np.array(r["transform"])[:3,:3]
            errors=np.maximum(errors,[abs(r["height_mm"]-np.dot(lengths,np.abs(d))),
                abs(r["overhang_projected_area_sum_mm2"]-expected_area),
                np.max(np.abs(rotation@d-[0,0,1])),abs(np.linalg.det(rotation)-1)])
            assert r["contact_triangle_area_mm2"]==0
        assert np.all(errors<[1e-10,1e-9,2e-13,2e-13])
        audit.append(dict(angle_deg=angle,direction_count=len(vectors),
            max_height_error_mm=errors[0],max_projected_sum_error_mm2=errors[1],
            max_alignment_error=errors[2],max_determinant_error=errors[3]))
    benchmarks=[]
    for path in sorted((ROOT/"examples/external").glob("*.stl")):
        data=path.read_bytes()
        model=load_model(data,path.name)
        row=dict(file=path.name,sha256=hashlib.sha256(data).hexdigest(),
            unit_status=model.metadata["unit_status"],extents_mm=model.mesh.extents.tolist(),
            face_count=len(model.mesh.faces),runs=[])
        for dense in (False,True):
            start=time.perf_counter()
            report=review(model,Profile(),dense=dense)
            row["runs"].append(dict(candidate_count=len(report["orientations"]),
                seconds=time.perf_counter()-start,profile=report["profile"]))
        benchmarks.append(row)
    originals=[]
    for raw in subprocess.check_output(["git","ls-tree","-r","--name-only","-z","1706eac"],cwd=ROOT).split(b"\0"):
        if not raw:continue
        name=raw.decode("utf-8")
        before=subprocess.check_output(["git","show",f"1706eac:{name}"],cwd=ROOT)
        expected=subprocess.check_output(["git","rev-parse",f"1706eac:{name}"],cwd=ROOT).decode().strip()
        current=subprocess.check_output(["git","hash-object","--",str(ROOT/name)],cwd=ROOT).decode().strip()
        unchanged=expected==current
        assert unchanged,name
        originals.append(dict(path=name,unchanged=unchanged,git_blob=current,
            git_blob_sha256=hashlib.sha256(before).hexdigest(),
            checkout_sha256=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()))
    result=dict(created_utc=datetime.now(timezone.utc).isoformat(),python=platform.python_version(),
        platform=platform.platform(),analysis_code_sha256=code_digest(),seed=824,
        box_extents_mm=lengths.tolist(),analytic=audit,external_benchmarks=benchmarks,originals=originals,
        scope="Independent polyhedral geometry checks; curved tessellation, layer sampling and process physics are separate limitations.")
    (out/"summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(dict(out=str(out),analytic=audit,benchmarks=[dict(file=b["file"],runs=[(r["candidate_count"],r["seconds"]) for r in b["runs"]]) for b in benchmarks]),ensure_ascii=False))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,required=True)
    validate(parser.parse_args().out.resolve())
