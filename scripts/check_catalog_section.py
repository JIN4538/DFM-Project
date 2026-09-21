"""Compare an audited extrusion's geometric section with a supplied catalog value.

This independent polygon arithmetic is a validation aid, not a printability rule.
The volume/length comparison assumes a constant extrusion; the section calculation
itself measures one midpoint plane. Original CAD and mesh inputs are read-only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from shapely.geometry import Polygon
import trimesh


def measure(audit_root, relative_file, *, axis=2, endpoint_decimals=7):
    manifest = json.loads((audit_root / "manifest.json").read_text(encoding="utf-8"))
    matches = [x for x in manifest["inventory"] if x["relative_path"].endswith(relative_file)]
    if len(matches) != 1:
        raise ValueError("Specify one unambiguous input path from the audit manifest.")
    entry = matches[0]
    with np.load(audit_root / entry["id"] / "model.npz") as arrays:
        mesh = trimesh.Trimesh(vertices=arrays["vertices"], faces=arrays["faces"], process=False)
    center = mesh.bounds.mean(axis=0)
    normal = np.eye(3)[axis]
    transverse_axes = [i for i in range(3) if i != axis]
    lines = trimesh.intersections.mesh_plane(mesh, plane_normal=normal, plane_origin=center)
    endpoints = lines[:, :, transverse_axes].reshape(-1, 2) - center[transverse_axes]
    points, inverse = np.unique(np.round(endpoints, endpoint_decimals), axis=0, return_inverse=True)
    edges = inverse.reshape(-1, 2)
    neighbors = {}
    for a, b in edges:
        neighbors.setdefault(a, set()).add(b)
        neighbors.setdefault(b, set()).add(a)
    if not neighbors or not all(len(v) == 2 for v in neighbors.values()):
        raise ValueError("Midpoint section is not a closed degree-two graph at the reported joining precision.")
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
    if not all(p.is_valid and p.area > 0 for p in polygons):
        raise ValueError("A section ring is invalid or has no area.")
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
    if area <= 0:
        raise ValueError("No positive material section area.")
    centroid = np.array([mx, my]) / area
    section_inertia = [ix_origin - area * centroid[1]**2, iy_origin - area * centroid[0]**2]
    length = float(mesh.extents[axis])
    mesh_area = float(mesh.volume / length)
    inertia = mesh.mass_properties.inertia
    return dict(source_relative_path=entry["relative_path"], source_sha256=entry["sha256"],
        baseline_code_sha256=manifest["code_sha256"],
        independent_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        method="Midpoint triangle-plane intersections; degree-two endpoint cycles; polygon containment parity; signed shoelace area/second moments.",
        plane_axis=axis, plane_coordinate_mm=float(center[axis]), section_axes=transverse_axes,
        endpoint_rounding_mm=10.**(-endpoint_decimals), ring_count=len(rings), section_area_mm2=float(area),
        section_centroid_mm=(centroid+center[transverse_axes]).tolist(),
        section_centroidal_inertia_mm4=[float(v) for v in section_inertia],
        extrusion_length_mm=length, mesh_volume_over_length_mm2=mesh_area,
        mesh_extrusion_centroidal_inertia_mm4=[float(inertia[i, i]/length - mesh_area*length**2/12) for i in transverse_axes],
        scope="One midpoint section; extrusion volume/inertia conversion assumes a constant section. Catalog values and geometry are compared without changing or calibrating the input. No material density or printing outcome is inferred.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--source", required=True, help="Full relative path or unique suffix in audit manifest")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--axis", type=int, choices=(0, 1, 2), default=2)
    parser.add_argument("--catalog-inertia-mm4", type=float)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Output already exists; preserve the previous result and select a fresh path.")
    result = measure(args.audit, args.source, axis=args.axis)
    if args.catalog_inertia_mm4 is not None:
        if not np.isfinite(args.catalog_inertia_mm4) or args.catalog_inertia_mm4 <= 0:
            parser.error("Catalog inertia must be finite and positive.")
        result["catalog_inertia_mm4"] = args.catalog_inertia_mm4
        result["relative_difference_from_catalog"] = [abs(v-args.catalog_inertia_mm4)/args.catalog_inertia_mm4
            for v in result["section_centroidal_inertia_mm4"]]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, indent=2))
