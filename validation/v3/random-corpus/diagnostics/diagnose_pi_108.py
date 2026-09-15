from pathlib import Path
import hashlib
import json
import sys

import numpy as np
import shapely as sh
import trimesh

ROOT = Path(__file__).parent
AUDIT = ROOT / "final-01"
REPO = ROOT.parents[1] / "DFM-Project"
sys.path.insert(0, str(AUDIT / "engine-source"))
sys.path.insert(0, str(REPO))
from amdfm.models import Model, json_bytes
from scripts.inspect_section_events import independent_section

folder = AUDIT / "file_026"
info = json.loads((folder / "model.json").read_text(encoding="utf-8"))
with np.load(folder / "model.npz", allow_pickle=False) as data:
    model = Model(trimesh.Trimesh(vertices=data["vertices"], faces=data["faces"], process=False),
        info["metadata"], info["cad_features"], data["face_ids"].copy(), data["body_ids"].copy()).select_body(108)
report = json.loads((folder / "body_108_MEX.json").read_text(encoding="utf-8"))
matrix = np.asarray(report["current_orientation"]["transform"])
mesh = trimesh.Trimesh(vertices=model.mesh.vertices@matrix[:3,:3].T+matrix[:3,3], faces=model.mesh.faces, process=False)
rows = []
center = 2.3906250000000004
for z in (center-1e-4, center-1e-6, center, center+1e-6, center+1e-4):
    row = {"z_mm": z}
    try:
        row["independent_polygon"] = independent_section(mesh, z)
    except Exception as exc:
        row["independent_error"] = f"{type(exc).__name__}: {exc}"
    segments, face_indices = trimesh.intersections.mesh_plane(mesh, plane_normal=[0,0,1], plane_origin=[0,0,z], return_faces=True)
    lines = sh.linestrings(segments[:,:,:2])
    intersections = sh.STRtree(lines).query(lines, predicate="intersects")
    unusual = []
    for i, j in intersections.T:
        if i >= j:
            continue
        cross = lines[i].intersection(lines[j])
        if cross.geom_type == "Point":
            xy = np.asarray(cross.coords)[0]
            end_i = min(np.linalg.norm(segments[i,:,:2]-xy, axis=1))
            end_j = min(np.linalg.norm(segments[j,:,:2]-xy, axis=1))
            if end_i <= 1e-10 and end_j <= 1e-10:
                continue
            unusual.append(dict(kind="intersection_inside_segment", xy_mm=xy.tolist(),
                distance_to_endpoints_mm=[float(end_i),float(end_j)],
                mesh_faces=[int(face_indices[i]),int(face_indices[j])],
                cad_faces=[int(model.face_ids[face_indices[i]]),int(model.face_ids[face_indices[j]])]))
        elif cross.length > 1e-10:
            unusual.append(dict(kind="overlap", length_mm=float(cross.length),
                mesh_faces=[int(face_indices[i]),int(face_indices[j])],
                cad_faces=[int(model.face_ids[face_indices[i]]),int(model.face_ids[face_indices[j]])]))
    row["unusual_segment_intersections"] = unusual
    row["segment_count"] = len(segments)
    rows.append(row)
record = dict(source_sha256=model.metadata["source_sha256"], model_fingerprint=model.fingerprint,
    body=108, source_code_sha256=report["provenance"]["code_sha256"],
    script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    coordinate_frame="build_mm", endpoint_intersection_tolerance_mm=1e-10,
    mesh_watertight=mesh.is_watertight, mesh_winding_consistent=mesh.is_winding_consistent,
    findings=rows, scope="Independent local intersections on frozen tessellation, not a diagnosis of raw CAD topology or a physical print defect.")
destination = ROOT / "pi-body-108-crossing-diagnosis-01.json"
assert not destination.exists()
destination.write_bytes(json_bytes(record))
print(json.dumps(rows, ensure_ascii=True, indent=2))
