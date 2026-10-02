"""Independent mesh-section arithmetic around vertex/CAD-plane height events.

Within an interval containing no mesh vertex height, oriented polygon boundary
vertices move linearly with z and shoelace area is quadratic. Two-point Gauss
quadrature integrates this polynomial exactly apart from floating-point/endpoint
joining error. This is a mesh validation method, not a CAD surface-error bound.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from scipy.spatial import cKDTree
from shapely.geometry import Polygon
from shapely.validation import explain_validity
import trimesh


def independent_section(mesh, z, decimals=8):
    lines = trimesh.intersections.mesh_plane(mesh, plane_normal=[0, 0, 1], plane_origin=[0, 0, z])
    if len(lines) == 0:
        return dict(area_mm2=0., perimeter_mm=0., rings=0)
    center = mesh.bounds.mean(axis=0)[:2]
    endpoints = lines[:, :, :2].reshape(-1, 2) - center
    # A decimal rounding cell boundary can split two endpoints differing only
    # by floating-point evaluation order. Join by a scale-aware numerical
    # distance and report the actual adjustment; never edit the source mesh.
    tolerance = max(1e-12, float(max(mesh.extents))*np.finfo(float).eps*256)
    parent = np.arange(len(endpoints))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for a, b in cKDTree(endpoints).query_pairs(tolerance):
        a, b = find(a), find(b)
        if a != b:
            parent[b] = a
    roots, inverse = np.unique([find(i) for i in range(len(endpoints))], return_inverse=True)
    points = np.array([endpoints[inverse == i].mean(axis=0) for i in range(len(roots))])
    adjustment = float(np.linalg.norm(points[inverse]-endpoints, axis=1).max())
    edges = inverse.reshape(-1, 2)
    if len(np.unique(np.sort(edges, axis=1), axis=0)) != len(edges):
        raise ValueError(f"Duplicate section edges at z={z}; no implicit repair")
    neighbors = {}
    for a, b in edges:
        neighbors.setdefault(a, set()).add(b)
        neighbors.setdefault(b, set()).add(a)
    if not all(len(v) == 2 for v in neighbors.values()):
        raise ValueError(f"Section is not closed degree-two loops at z={z}")
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
    polygons = [Polygon(ring) for ring in rings]
    if not all(p.is_valid and p.area > 0 for p in polygons):
        reasons = [explain_validity(p) if not p.is_valid else "zero area" for p in polygons if not p.is_valid or p.area <= 0]
        raise ValueError(f"Invalid section ring at z={z}: {reasons}")
    area = perimeter = 0.
    for ring, polygon in zip(rings, polygons):
        parity = -1 if sum(other.contains(polygon) for other in polygons if other is not polygon) % 2 else 1
        following = np.roll(ring, -1, axis=0)
        area += parity * abs(np.sum(ring[:, 0]*following[:, 1] - following[:, 0]*ring[:, 1])) / 2
        perimeter += float(np.linalg.norm(following-ring, axis=1).sum())
    return dict(area_mm2=float(area), perimeter_mm=perimeter, rings=len(rings),
        endpoint_join_tolerance_mm=tolerance, endpoint_join_max_adjustment_mm=adjustment)


def run(args):
    from amdfm.models import Model, json_bytes
    folder = args.audit / args.file_id
    info = json.loads((folder / "model.json").read_text(encoding="utf-8"))
    with np.load(folder / "model.npz", allow_pickle=False) as arrays:
        model = Model(trimesh.Trimesh(vertices=arrays["vertices"], faces=arrays["faces"], process=False),
            info["metadata"], info["cad_features"], arrays["face_ids"].copy() if "face_ids" in arrays else None,
            arrays["body_ids"].copy() if "body_ids" in arrays else None).select_body(args.body)
    name = "whole" if args.body is None else f"body_{args.body:03d}"
    report = json.loads((folder / f"{name}_MEX.json").read_text(encoding="utf-8"))
    if model.fingerprint != report["model_fingerprint"]:
        raise ValueError("Audit/model fingerprints differ")
    matrix = np.asarray(report["current_orientation"]["transform"])
    mesh = trimesh.Trimesh(vertices=model.mesh.vertices@matrix[:3, :3].T+matrix[:3, 3], faces=model.mesh.faces, process=False)
    if not mesh.is_watertight or not mesh.is_winding_consistent or mesh.volume <= 0:
        raise ValueError("This independent event integration requires one oriented closed material mesh.")
    knots = np.unique(np.round(mesh.vertices[:, 2], args.decimals))
    if len(knots)-1 > args.max_intervals:
        raise ValueError("Too many event intervals for the explicit independent-check budget")
    intervals = []
    for index, (low, high) in enumerate(zip(knots[:-1], knots[1:])):
        midpoint = (low+high)/2
        offset = (high-low)/(2*np.sqrt(3))
        samples = [dict(z_mm=float(z), **independent_section(mesh, z, args.decimals))
            for z in (midpoint-offset, midpoint, midpoint+offset)]
        area_values = [x["area_mm2"] for x in samples]
        intervals.append(dict(index=index, low_z_mm=float(low), high_z_mm=float(high),
            thickness_mm=float(high-low), independent_samples=samples,
            constant_sampled_area=np.allclose(area_values, area_values[0], rtol=1e-9, atol=1e-6),
            gauss_volume_mm3=float((samples[0]["area_mm2"]+samples[2]["area_mm2"])*(high-low)/2)))
    planes = []
    for feature in model.cad_features:
        if feature["kind"] != "plane":
            continue
        normal = np.asarray(feature["normal"])@matrix[:3, :3].T
        if abs(normal[2]) < 1-1e-9:
            continue
        selected = np.flatnonzero(model.face_ids == feature["face_id"])
        vertices = mesh.vertices[mesh.faces[selected]].reshape(-1, 3)
        planes.append(dict(cad_face_id=feature["face_id"], normal_build_z=float(normal[2]),
            low_z_mm=float(vertices[:, 2].min()), high_z_mm=float(vertices[:, 2].max()),
            tessellated_plane_area_mm2=float(mesh.area_faces[selected].sum())))
    detail_paths = [folder / f"{name}_MEX_sections.json", *args.section_json]
    checks = []
    for path in detail_paths:
        detail = json.loads(path.read_text(encoding="utf-8"))
        if detail["fingerprint"] != model.fingerprint:
            raise ValueError(f"Section/model fingerprints differ: {path}")
        errors, grid_errors, max_area, max_perimeter, max_join = [], [], 0., 0., 0.
        max_area_fraction_of_grid_bound = 0.
        counts = np.zeros(len(intervals), dtype=int)
        for row in detail.get("rows", []):
            if not row["complete"]:
                continue
            independent = independent_section(mesh, row["z_mm"], args.decimals)
            max_join = max(max_join, independent.get("endpoint_join_max_adjustment_mm", 0.))
            area_error = abs(independent["area_mm2"]-row["area_mm2"])
            perimeter_error = abs(independent["perimeter_mm"]-row["perimeter_mm"])
            max_area, max_perimeter = max(max_area, area_error), max(max_perimeter, perimeter_error)
            if area_error > max(1e-6, independent["area_mm2"]*1e-9) or perimeter_error > max(1e-6, independent["perimeter_mm"]*1e-9):
                errors.append(dict(index=row["index"], z_mm=row["z_mm"], area_error_mm2=area_error, perimeter_error_mm=perimeter_error))
            grid = row["diagnostics"]["grid_mm"]
            segments = row["diagnostics"]["segment_count"]
            movement = grid/np.sqrt(2) + independent.get("endpoint_join_tolerance_mm", 0.)
            # For corresponding polygon vertices moved by at most d:
            # |delta A| <= perimeter*d + N*d^2/2. Account separately for
            # the production simplifier's measured area change.
            area_bound = (independent["perimeter_mm"]*movement + segments*movement**2/2
                + abs(row["diagnostics"].get("contour_area_change_mm2", 0.)) + 1e-8)
            perimeter_bound = 2*segments*(movement + row["diagnostics"].get("contour_simplification_tolerance_mm", 0.)) + 1e-8
            max_area_fraction_of_grid_bound = max(max_area_fraction_of_grid_bound, area_error/area_bound)
            if area_error > area_bound or perimeter_error > perimeter_bound:
                grid_errors.append(dict(index=row["index"], z_mm=row["z_mm"],
                    area_error_mm2=area_error, area_grid_bound_mm2=area_bound,
                    perimeter_error_mm=perimeter_error, perimeter_grid_bound_mm=perimeter_bound))
            interval = np.searchsorted(knots, row["z_mm"], side="right")-1
            if 0 <= interval < len(intervals):
                counts[interval] += 1
        spacing = detail.get("sample_spacing_mm")
        checks.append(dict(source_json=str(path), source_json_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            requested_samples=detail.get("requested_samples"), complete_samples=detail.get("complete_samples"),
            strict_relative_threshold_exceedances=errors,
            declared_grid_precision_exceedances=grid_errors,
            grid_bound_scope="Corresponding closed polygon vertices: |delta A| <= perimeter*d+N*d^2/2, d=grid/sqrt(2)+independent join tolerance; plus reported simplifier area change and1e-8 roundoff allowance. Not a general topological/CAD error certificate.",
            max_area_error_fraction_of_declared_grid_bound=max_area_fraction_of_grid_bound,
            max_area_absolute_difference_mm2=max_area, max_perimeter_absolute_difference_mm=max_perimeter,
            max_endpoint_join_adjustment_mm=max_join,
            interval_sampling=[dict(interval_index=i, samples=int(count),
                represented_thickness_mm=float(count*spacing) if spacing else None,
                actual_interval_thickness_mm=intervals[i]["thickness_mm"]) for i, count in enumerate(counts)],
            unsampled_intervals=np.flatnonzero(counts == 0).tolist(),
            volume_midpoint_estimate_mm3=detail.get("volume_midpoint_estimate_mm3")))
    tetra_tri = mesh.triangles - mesh.vertices.mean(axis=0)
    tetra = float(np.sum(np.einsum("ij,ij->i", tetra_tri[:, 0], np.cross(tetra_tri[:, 1], tetra_tri[:, 2])))/6)
    gauss = sum(x["gauss_volume_mm3"] for x in intervals)
    result = dict(source_sha256=model.metadata["source_sha256"], body=args.body,
        model_fingerprint=model.fingerprint, source_code_sha256=report["provenance"]["code_sha256"],
        independent_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        method="Independent trimesh plane intersections, degree-two loops, shoelace area and segment perimeter; event-interval two-point Gauss volume integration.",
        height_event_rounding_mm=10.**(-args.decimals),
        endpoint_join_policy="Within max(1e-12mm, max_extent*machine_epsilon*256); observed adjustment reported. Source mesh unmodified.",
        coordinate_frame="build_mm", knot_heights_mm=knots,
        intervals=intervals, horizontal_cad_planes=planes, production_section_checks=checks,
        independent_tetra_volume_mm3=tetra, piecewise_gauss_volume_mm3=gauss,
        gauss_vs_tetra_relative_difference=abs(gauss-tetra)/tetra,
        scope="Event knots and polygon areas belong to the stored tessellated closed mesh. No CAD Hausdorff bound, printing force, process success or guaranteed uniform-sample extrema are inferred.")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(json_bytes(result))
    print(json.dumps(dict(intervals=len(intervals), gauss_volume_mm3=gauss, tetra_volume_mm3=tetra,
        relative_difference=result["gauss_vs_tetra_relative_difference"],
        strict_threshold_exceedances=[len(x["strict_relative_threshold_exceedances"]) for x in checks],
        declared_grid_precision_exceedances=[len(x["declared_grid_precision_exceedances"]) for x in checks]), ensure_ascii=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--file-id", required=True)
    parser.add_argument("--body", type=int)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--section-json", type=Path, nargs="*", default=[])
    parser.add_argument("--decimals", type=int, default=8)
    parser.add_argument("--max-intervals", type=int, default=1000)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Output already exists; choose a fresh result path.")
    if not 4 <= args.decimals <= 12 or args.max_intervals < 1:
        parser.error("Endpoint decimals4..12 and a positive interval budget are required.")
    manifest = json.loads((args.audit / "manifest.json").read_text(encoding="utf-8"))
    sys.path.insert(0, manifest["engine_root"])
    run(args)
