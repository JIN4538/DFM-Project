"""Real before/after B-rep pairs for independently verified pocket corner edits.

The original STEP is never modified. A proposed fillet is retained only when
OCCT produces a valid single solid, preserves its AABB and adds material at
the concave corners. This is geometric edit supervision, not expert preference.
"""
import hashlib
import math
from pathlib import Path
import numpy as np


def unique(parent, kind):
    from OCP.TopExp import TopExp_Explorer
    ex = TopExp_Explorer(parent, kind)
    output = []
    while ex.More():
        item = ex.Current()
        if not any(item.IsSame(old) for old in output):
            output.append(item)
        ex.Next()
    return output


def read_shape(path):
    from OCP.STEPControl import STEPControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopAbs import TopAbs_SOLID
    reader = STEPControl_Reader()
    if reader.ReadFile(str(path)) != IFSelect_RetDone:
        raise ValueError('STEP read failed')
    reader.SetSystemLengthUnit(1.)
    reader.TransferRoots()
    shape = reader.OneShape()
    if not BRepCheck_Analyzer(shape).IsValid() or len(unique(shape, TopAbs_SOLID)) != 1:
        raise ValueError('A valid single solid is required')
    return unique(shape, TopAbs_SOLID)[0]


def bounds(shape):
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    b = Bnd_Box()
    b.SetGap(0.)
    BRepBndLib.AddOptimal_s(shape, b, False, False)
    return np.array(b.Get())


def round_corners(shape, pocket, radius):
    from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX, TopAbs_SOLID
    from OCP.TopoDS import TopoDS
    from OCP.BRep import BRep_Tool
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
    from OCP.BRepCheck import BRepCheck_Analyzer
    from amdfm.cad_worker import integrated_properties
    from dfm.cad_graph import extract_graph
    from dfm.external_features_review import pocket_dimensions
    if not isinstance(radius, (int, float)) or isinstance(radius, bool) or not math.isfinite(radius) or radius <= 0:
        raise ValueError('Radius must be finite and positive')
    faces = [TopoDS.Face_s(f) for f in unique(shape, TopAbs_FACE)]
    indices = pocket['face_ids']
    if any(not isinstance(i, int) or i < 1 or i > len(faces) for i in indices):
        raise ValueError('Source face IDs are invalid')
    graph = extract_graph(shape, faces)
    candidate = dict(feature=pocket['feature'], face_ids=indices, measured_faces=[graph['measurements'][i-1] for i in indices])
    measured = pocket_dimensions(candidate, pocket['direction'])
    if measured is None or measured['floor_face_id'] != pocket['floor_face_id']:
        raise ValueError('Source pocket no longer matches the verified prism')
    for name in ('width_mm', 'wall_height_mm', 'entry_circle_diameter_mm'):
        if not math.isclose(measured[name], pocket[name], rel_tol=1e-7, abs_tol=1e-7):
            raise ValueError('Source pocket dimension mismatch')
    if radius > measured['entry_circle_diameter_mm']/2:
        raise ValueError('Radius exceeds local entry disk bound')
    axis = np.asarray(pocket['direction'], dtype=float)
    axis /= np.linalg.norm(axis)
    walls = [faces[i-1] for i in indices if i != measured['floor_face_id']]
    edges, owners = [], []
    for wall in walls:
        for edge in unique(wall, TopAbs_EDGE):
            k = next((j for j, old in enumerate(edges) if edge.IsSame(old)), None)
            if k is None:
                edges.append(edge); owners.append(1)
            else:
                owners[k] += 1
    selected = []
    for edge, count in zip(edges, owners):
        if count != 2:
            continue
        vertices = unique(edge, TopAbs_VERTEX)
        if len(vertices) != 2:
            continue
        a, b = [np.array(BRep_Tool.Pnt_s(TopoDS.Vertex_s(v)).Coord()) for v in vertices]
        length = np.linalg.norm(b-a)
        if length > 0 and abs((b-a)@axis)/length > 1-1e-7:
            selected.append(TopoDS.Edge_s(edge))
    expected = {'triangular_pocket': 3, 'rectangular_pocket': 4, '6sides_pocket': 6}[pocket['feature']]
    if len(selected) != expected:
        raise ValueError('Complete vertical corner edge set not identified')
    operation = BRepFilletAPI_MakeFillet(shape)
    for edge in selected:
        operation.Add(float(radius), edge)
    operation.Build()
    if not operation.IsDone():
        raise ValueError('OCCT fillet construction failed')
    after = operation.Shape()
    if not BRepCheck_Analyzer(after).IsValid() or len(unique(after, TopAbs_SOLID)) != 1:
        raise ValueError('Fillet result is not a valid single solid')
    before_props = integrated_properties(shape)
    after_props = integrated_properties(after)
    if not np.allclose(bounds(shape), bounds(after), rtol=0, atol=max(1e-7, measured['width_mm']*1e-7)):
        raise ValueError('Fillet changed outer bounding box')
    # Internal rounding adds material to the sharp recess corners. An outer
    # edge selected accidentally would remove it and is therefore rejected.
    before_volume = before_props['volume_mm3']
    after_volume = after_props['volume_mm3']
    if after_volume <= before_volume or after_volume >= before_volume*1.5:
        raise ValueError('Unexpected material change in internal corner edit')
    # Independent analytic prism check: each convex floor corner replaces
    # its sharp wedge by a tangent arc. This detects incomplete rounding and
    # interference with another feature even when the result is valid CAD.
    floor = next(m for m in candidate['measured_faces'] if m['face_id'] == measured['floor_face_id'])
    points = np.asarray(floor['vertex_points_mm'])
    center = points.mean(0)
    u = points[0]-center; u /= np.linalg.norm(u)
    v = np.cross(axis, u)
    order = np.argsort(np.arctan2((points-center)@v, (points-center)@u))
    points = points[order]
    extra_area = 0.
    for i, point in enumerate(points):
        a = points[i-1]-point
        b = points[(i+1) % len(points)]-point
        alpha = math.acos(float(np.clip(a@b/(np.linalg.norm(a)*np.linalg.norm(b)), -1, 1)))
        extra_area += radius**2*(1/math.tan(alpha/2)-(math.pi-alpha)/2)
    expected_delta = extra_area*measured['wall_height_mm']
    actual_delta = after_volume-before_volume
    if not math.isclose(actual_delta, expected_delta, rel_tol=1e-6, abs_tol=max(1e-7, before_volume*1e-8)):
        raise ValueError('Modified material differs from independent rounded-prism formula')
    return after, dict(before_corner_radius_mm=0., after_corner_radius_mm=float(radius), modified_corner_edges=len(selected),
        before_volume_mm3=before_volume, after_volume_mm3=after_volume,
        measured_material_addition_mm3=actual_delta, analytic_material_addition_mm3=expected_delta,
        source_floor_face_id=measured['floor_face_id'], unchanged_outer_bounds=True,
        corner_axes_mm=[[p.tolist(), (p+axis*measured['wall_height_mm']).tolist()] for p in points],
        edit_bounds_mm=[np.minimum(points.min(0), (points+axis*measured['wall_height_mm']).min(0)).tolist(),
            np.maximum(points.max(0), (points+axis*measured['wall_height_mm']).max(0)).tolist()],
        verification='Valid single B-rep solid; exact pocket remeasurement; unchanged outer AABB; positive internal material addition')


def write_step(shape, path):
    from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
    from OCP.IFSelect import IFSelect_RetDone
    writer = STEPControl_Writer()
    if writer.Transfer(shape, STEPControl_AsIs) != IFSelect_RetDone or writer.Write(str(path)) != IFSelect_RetDone:
        raise ValueError('STEP export failed')
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
