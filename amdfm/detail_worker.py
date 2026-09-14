"""Memory-sensitive geometry queries run outside the Streamlit process."""
from pathlib import Path
import json
import sys
import time

import numpy as np
import trimesh

from .models import json_bytes
from src.core.mesh_diagnostics import inspect_mesh


def normal_chords(mesh, limit=None, n=800):
    areas = mesh.area_faces
    nf = len(areas)
    if nf <= n:
        indices = np.arange(nf)
        mass = areas.copy()
    else:
        n_area = n//2
        indices_area = np.searchsorted(np.cumsum(areas), (np.arange(n_area)+.5)*areas.sum()/n_area)
        detection = np.linspace(0,nf-1,n//4,dtype=int)
        small = np.argsort(areas)[:n//4]
        indices = np.unique(np.r_[indices_area, detection, small])
        mass = np.bincount(indices_area,minlength=nf)[indices]*areas.sum()/n_area
    centers = mesh.triangles_center[indices]
    normals = mesh.face_normals[indices]
    eps = max(1e-9, float(min(mesh.extents))*1e-6)
    distance, source_faces, target_faces, weights, points = [], [], [], [], []
    near = 0
    for start in range(0,len(indices),32):
        sl = slice(start,start+32)
        xyz, rays, target = mesh.ray.intersects_location(centers[sl]-normals[sl]*eps,
            -normals[sl], multiple_hits=False)
        dist = np.linalg.norm(xyz-centers[start+rays],axis=1)
        keep = np.isfinite(dist) & (dist > eps*1.01) & (target != indices[start+rays])
        near += int((~keep).sum())
        distance.extend(dist[keep].tolist())
        source_faces.extend(indices[start+rays[keep]].tolist())
        target_faces.extend(target[keep].tolist())
        weights.extend(mass[start+rays[keep]].tolist())
        points.extend(centers[start+rays[keep]].tolist())
    if not distance or sum(weights) <= 0:
        return {"status":"unknown", "reason":"유효한 법선 관통거리 표본이 없습니다."}
    distances = np.array(distance)
    order = np.argsort(distances)
    cumulative = np.cumsum(np.array(weights)[order])
    p05 = float(distances[order[min(np.searchsorted(cumulative,cumulative[-1]*.05),len(order)-1)]])
    below = np.flatnonzero(distances < limit) if limit else np.array([],dtype=int)
    return {"status":"measured" if len(distance)==len(indices) else "partial", "measurements":{
        "minimum_mm":float(min(distance)), "area_weighted_p05_mm":p05,
        "requested_samples":len(indices), "valid_samples":len(distance),
        "missing_samples":len(indices)-len(distance), "discarded_near_hits":near,
        "sampled_face_area_fraction":float(areas[np.unique(source_faces)].sum()/areas.sum()),
        "minimum_resolvable_distance_mm":eps*1.01, "minimum_wall_mm":limit,
        "below_limit_face_indices":[source_faces[i] for i in below],
        "thinnest_face_indices":[source_faces[i] for i in order[:50]],
        "samples":[{"point_mm":p,"normal_chord_mm":t,"source_face":s,"target_face":target}
                   for p,t,s,target in zip(points,distance,source_faces,target_faces)]}}


def run(base):
    started=time.perf_counter()
    request=json.loads((base/"request.json").read_text(encoding="utf-8"))
    with np.load(base/"mesh.npz",allow_pickle=False) as arrays:
        mesh=trimesh.Trimesh(vertices=arrays["vertices"],faces=arrays["faces"],process=False)
    profile=request["profile"]
    if request["mode"]=="wall":
        if request["assembly"]:
            result={"status":"unknown","reason":"두께는 단일 CAD 솔리드를 선택한 뒤 계산하세요. 겹치는 조립체를 재료 체적으로 가정하지 않습니다."}
        elif request.get("ambiguous_stl_shells"):
            result={"status":"unknown","reason":"여러 STL 표면의 교차·공동 포함 관계가 미확정입니다. 단일 CAD 솔리드 STEP 또는 확인된 단일 성분을 사용하세요."}
        elif not inspect_mesh(mesh)["topology_ready"]:
            result={"status":"unknown","reason":"입력 위상·면 방향 결함 때문에 안쪽 관통거리 측정을 보류했습니다."}
        else:
            result=normal_chords(mesh,profile["minimum_wall_mm"])
    else:
        from src.core.layer_review import inspect_layers
        if request["assembly"]:
            result={"status":"unknown","reason":"층간 검토는 단일 CAD 솔리드를 선택한 뒤 실행하세요."}
        elif request.get("ambiguous_stl_shells"):
            result={"status":"unknown","reason":"여러 STL 표면의 교차·공동 포함 관계가 미확정입니다. 단일 CAD 솔리드 또는 확인된 단일 성분으로 층간 검토를 실행하세요."}
        else:
            result=inspect_layers(mesh,request["direction"],profile["layer_height_mm"],
                profile["line_width_mm"],profile["overhang_angle_deg"],max_layers=1500,max_total_segments=1_500_000)
    result.update(mode=request["mode"],fingerprint=request["fingerprint"],profile=profile,
                  direction=request["direction"],elapsed_seconds=time.perf_counter()-started)
    return result


if __name__=="__main__":
    base=Path(sys.argv[1])
    try:
        result=run(base)
    except Exception as exc:
        request=json.loads((base/"request.json").read_text(encoding="utf-8"))
        result={"status":"unknown","reason":str(exc),"mode":request["mode"],"fingerprint":request["fingerprint"]}
    (base/"result.json").write_bytes(json_bytes(result))
