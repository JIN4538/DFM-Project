"""Simultaneous, independently checked corner edits in separate CAD pockets.

Each source pocket is remeasured and checked individually before one OCCT
operation edits the original shape. A second volume check rejects interference
between edits. No original file is changed and no partial result is exported.
"""
from __future__ import annotations

import math
import numpy as np
from .cad_edit_pairs import unique, round_corners, bounds

MAX_POCKETS = 8


def _corner_edges(faces, pocket):
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_VERTEX
    from OCP.TopoDS import TopoDS
    from OCP.BRep import BRep_Tool
    axis = np.asarray(pocket['direction'], dtype=float)
    axis /= np.linalg.norm(axis)
    edges, owners = [], []
    for identifier in pocket['face_ids']:
        if identifier == pocket['floor_face_id']:
            continue
        for edge in unique(faces[identifier-1], TopAbs_EDGE):
            index = next((i for i, old in enumerate(edges) if old.IsSame(edge)), None)
            if index is None:
                edges.append(edge)
                owners.append(1)
            else:
                owners[index] += 1
    selected = []
    for edge, count in zip(edges, owners):
        vertices = unique(edge, TopAbs_VERTEX)
        if count != 2 or len(vertices) != 2:
            continue
        a, b = [np.asarray(BRep_Tool.Pnt_s(TopoDS.Vertex_s(v)).Coord()) for v in vertices]
        length = np.linalg.norm(b-a)
        if length > 0 and abs(float((b-a)@axis))/length > 1-1e-7:
            selected.append(TopoDS.Edge_s(edge))
    return selected


def round_multiple_corners(shape, requests):
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
    from OCP.TopoDS import TopoDS
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
    from OCP.BRepCheck import BRepCheck_Analyzer
    from amdfm.cad_worker import integrated_properties
    if not isinstance(requests, list) or not 1 <= len(requests) <= MAX_POCKETS:
        raise ValueError('Between one and eight verified pocket edits are required')
    faces = [TopoDS.Face_s(f) for f in unique(shape, TopAbs_FACE)]
    all_edges, audits, source_faces = [], [], set()
    operation = BRepFilletAPI_MakeFillet(shape)
    for request in requests:
        pocket, radius = request['pocket'], request['radius']
        ids = set(pocket['face_ids'])
        if source_faces & ids:
            raise ValueError('Pocket edits share source faces')
        source_faces.update(ids)
        # This existing check includes analytic rounded-prism volume, the
        # original face dimensions, radius bounds and a valid single solid.
        _, audit = round_corners(shape, pocket, radius)
        edges = _corner_edges(faces, pocket)
        if len(edges) != audit['modified_corner_edges']:
            raise ValueError('Corner edge selection differs from independent check')
        for edge in edges:
            if any(edge.IsSame(old) for old in all_edges):
                raise ValueError('Pocket edits share a corner edge')
            all_edges.append(edge)
            operation.Add(float(radius), edge)
        audit['direction'] = list(pocket['direction'])
        audits.append(audit)
    operation.Build()
    if not operation.IsDone():
        raise ValueError('Combined OCCT fillet construction failed')
    after = operation.Shape()
    if not BRepCheck_Analyzer(after).IsValid() or len(unique(after, TopAbs_SOLID)) != 1:
        raise ValueError('Combined edit is not a valid single solid')
    before_volume = integrated_properties(shape)['volume_mm3']
    after_volume = integrated_properties(after)['volume_mm3']
    expected_delta = sum(a['analytic_material_addition_mm3'] for a in audits)
    actual_delta = after_volume-before_volume
    tolerance = max(1e-7, before_volume*1e-8)
    if not math.isclose(actual_delta, expected_delta, rel_tol=1e-6, abs_tol=tolerance):
        raise ValueError('Pocket edits interfere: material differs from summed analytic prisms')
    all_bounds = np.asarray([a['edit_bounds_mm'] for a in audits])
    low, high = all_bounds[:, 0].min(0), all_bounds[:, 1].max(0)
    if not np.allclose(bounds(shape), bounds(after), rtol=0, atol=max(1e-7, float((high-low).max())*1e-7)):
        raise ValueError('Combined edit changed outer bounding box')
    return after, dict(edits=audits, edited_pocket_count=len(audits), modified_corner_edges=len(all_edges),
        before_corner_radius_mm=0., after_corner_radius_mm=max(a['after_corner_radius_mm'] for a in audits),
        before_volume_mm3=before_volume, after_volume_mm3=after_volume,
        measured_material_addition_mm3=actual_delta, analytic_material_addition_mm3=expected_delta,
        unchanged_outer_bounds=True, corner_axes_mm=[x for a in audits for x in a['corner_axes_mm']],
        edit_bounds_mm=[low.tolist(), high.tolist()],
        verification='Valid single B-rep; each source pocket independently remeasured; unchanged outer AABB; summed analytic material check')
