"""Independent catalog/cross-section check. Never alters original STEP."""
from pathlib import Path
import hashlib
import json
import numpy as np
import trimesh
from shapely.geometry import Polygon

root = Path(__file__).parent
baseline = root / "baseline-01"
manifest = json.loads((baseline / "manifest.json").read_text(encoding="utf-8"))
entry = next(x for x in manifest["inventory"] if x["relative_path"].endswith("/900-602.stp"))
arrays = np.load(baseline / entry["id"] / "model.npz")
mesh = trimesh.Trimesh(vertices=arrays["vertices"], faces=arrays["faces"], process=False)
lines = trimesh.intersections.mesh_plane(mesh, plane_normal=[0, 0, 1], plane_origin=mesh.centroid)
points, inverse = np.unique(np.round(lines[:, :, :2].reshape(-1, 2), 7), axis=0, return_inverse=True)
edges = inverse.reshape(-1, 2)
neighbors = {}
for a, b in edges:
    neighbors.setdefault(a, set()).add(b)
    neighbors.setdefault(b, set()).add(a)
assert all(len(v) == 2 for v in neighbors.values()), "Section graph is not closed degree two"
unvisited, rings = set(neighbors), []
while unvisited:
    start = next(iter(unvisited))
    current, previous, ring = start, None, []
    while True:
        ring.append(current)
        unvisited.discard(current)
        nxt = next(x for x in neighbors[current] if x != previous)
        previous, current = current, nxt
        if current == start:
            break
    rings.append(points[ring])
polygons = [Polygon(r) for r in rings]
area = mx = my = ix_origin = iy_origin = 0.
for ring, polygon in zip(rings, polygons):
    sign = -1 if sum(other.contains(polygon) for other in polygons if other is not polygon) % 2 else 1
    x, y = ring.T
    xx, yy = np.roll(x, -1), np.roll(y, -1)
    cross = x * yy - xx * y
    orientation = 1 if cross.sum() > 0 else -1
    cross *= sign * orientation
    area += cross.sum() / 2
    mx += ((x + xx) * cross).sum() / 6
    my += ((y + yy) * cross).sum() / 6
    ix_origin += ((y*y + y*yy + yy*yy) * cross).sum() / 12
    iy_origin += ((x*x + x*xx + xx*xx) * cross).sum() / 12
centroid = np.array([mx, my]) / area
ix_section = ix_origin - area * centroid[1]**2
iy_section = iy_origin - area * centroid[0]**2
length = float(mesh.extents[2])
mesh_area = float(mesh.volume / length)
inertia = mesh.mass_properties.inertia
record = dict(source_sha256=entry["sha256"], baseline_code_sha256=manifest["code_sha256"],
    independent_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    method="Midheight triangle-plane intersections; degree-two endpoint cycles; polygon containment parity; signed shoelace area/second moments.",
    endpoint_rounding_mm=1e-7, ring_count=len(rings), section_area_mm2=area,
    section_Ix_mm4=ix_section, section_Iy_mm4=iy_section,
    mesh_volume_over_length_mm2=mesh_area,
    mesh_Ix_mm4=float(inertia[0, 0]/length - mesh_area*length**2/12),
    mesh_Iy_mm4=float(inertia[1, 1]/length - mesh_area*length**2/12),
    catalog_Ix_Iy_mm4=28500,
    catalog_scope="Supplied TXT:2.85cm4 each. Rounded nominal vendor values may differ from supplied CAD. No modification or calibration of original geometry.",
    failed_previous_attempt="trimesh.Path2D.polygons_full unavailable because optional networkx is absent; custom closed-cycle tracing used instead.")
dest = root / "supplier-900-602-check-02.json"
assert not dest.exists()
dest.write_text(json.dumps(record, indent=2), encoding="utf-8")
print(json.dumps(record, indent=2))
