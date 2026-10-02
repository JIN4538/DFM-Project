"""Read-only B-rep measurements for downstream process-specific feature checks.

These are trimmed faces and boundary edges, not a machining-feature recognizer.
All positions are in the imported model's millimetre coordinate system. Face IDs
are supplied by the worker so adjacency and the displayed mesh refer to the same
faces. Limits and extraction failures remain explicit rather than empty results.
"""
from __future__ import annotations

import math

import numpy as np

MAX_FACE_BOUNDARY_EDGES = 512
MAX_MODEL_BOUNDARY_EDGES = 50_000
AREA_RELATIVE_TOLERANCE = 1e-9


def _items(shape, kind):
    from OCP.TopExp import TopExp_Explorer
    explorer = TopExp_Explorer(shape, kind)
    while explorer.More():
        yield explorer.Current()
        explorer.Next()


def _surface_descriptor(face, face_id):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder
    from OCP.TopAbs import TopAbs_REVERSED
    surface = BRepAdaptor_Surface(face, True)
    result = dict(face_id=face_id, kind="other")
    if surface.GetType() == GeomAbs_Plane:
        plane = surface.Plane()
        normal = np.asarray(plane.Axis().Direction().Coord())
        if face.Orientation() == TopAbs_REVERSED:
            normal = -normal
        result.update(kind="plane", normal=normal.tolist())
    elif surface.GetType() == GeomAbs_Cylinder:
        cylinder = surface.Cylinder()
        result.update(kind="cylinder", axis=list(cylinder.Axis().Direction().Coord()),
                      radius_mm=cylinder.Radius())
    return result


class BoundaryContext:
    """Per-body topology maps; neither geometry nor source tolerances are changed."""

    def __init__(self, shape, face_id_offset, *, surface_only=False,
                 remaining_edges=MAX_MODEL_BOUNDARY_EDGES):
        from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE
        from OCP.TopExp import TopExp
        from OCP.TopTools import TopTools_IndexedMapOfShape, TopTools_IndexedDataMapOfShapeListOfShape
        from OCP.TopoDS import TopoDS
        self.face_map = TopTools_IndexedMapOfShape()
        self.descriptors = {}
        for index, raw in enumerate(_items(shape, TopAbs_FACE), 1):
            face = TopoDS.Face_s(raw)
            key = self.face_map.Add(face)
            self.descriptors[key] = _surface_descriptor(face, face_id_offset + index)
        self.edge_faces = TopTools_IndexedDataMapOfShapeListOfShape()
        TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, self.edge_faces)
        self.remaining_edges = remaining_edges
        self.surface_only = surface_only

    def _edge(self, edge, current_face):
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.BRep import BRep_Tool
        from OCP.BRepGProp import BRepGProp
        from OCP.GProp import GProp_GProps
        from OCP.GeomAbs import GeomAbs_Line, GeomAbs_Circle
        from OCP.TopAbs import TopAbs_REVERSED
        edge_id = self.edge_faces.FindIndex(edge)
        result = dict(edge_id=edge_id, kind="other", concavity="not_evaluated",
                      degenerate=bool(BRep_Tool.Degenerated_s(edge)), adjacent_faces=[])
        if edge_id:
            seen = set()
            for adjacent in self.edge_faces.FindFromIndex(edge_id):
                index = self.face_map.FindIndex(adjacent)
                if index and index not in seen and not adjacent.IsSame(current_face):
                    result["adjacent_faces"].append(dict(self.descriptors[index]))
                    seen.add(index)
        if result["degenerate"]:
            result["geometry_status"] = "degenerate"
            return result
        curve = BRepAdaptor_Curve(edge)
        first, last = curve.FirstParameter(), curve.LastParameter()
        if not np.isfinite([first, last]).all():
            raise ValueError("Non-finite boundary curve parameter interval.")
        start, end = curve.Value(first), curve.Value(last)
        if edge.Orientation() == TopAbs_REVERSED:
            start, end = end, start
        length = GProp_GProps()
        BRepGProp.LinearProperties_s(edge, length)
        if not math.isfinite(length.Mass()) or length.Mass() < 0:
            raise ValueError("Invalid boundary length integral.")
        result.update(start_mm=list(start.Coord()), end_mm=list(end.Coord()),
                      midpoint_mm=list(curve.Value((first + last) / 2).Coord()),
                      length_mm=length.Mass(), geometry_status="complete")
        if curve.GetType() == GeomAbs_Line:
            result["kind"] = "line"
        elif curve.GetType() == GeomAbs_Circle:
            circle = curve.Circle()
            result.update(kind="circle", radius_mm=circle.Radius(),
                          center_mm=list(circle.Location().Coord()),
                          axis=list(circle.Axis().Direction().Coord()),
                          sweep_rad=abs(last - first))
        return result

    def planar_wires(self, face):
        from OCP.BRep import BRep_Tool
        from OCP.BRepTools import BRepTools, BRepTools_WireExplorer
        from OCP.TopAbs import TopAbs_WIRE, TopAbs_EDGE
        from OCP.TopoDS import TopoDS
        outer = BRepTools.OuterWire_s(face)
        wires = [TopoDS.Wire_s(wire) for wire in _items(face, TopAbs_WIRE)]
        counts = [sum(1 for _ in _items(wire, TopAbs_EDGE)) for wire in wires]
        total = sum(counts)
        result = dict(boundary_status="complete", boundary_total_edge_count=total,
                      boundary_wires=[], material_normal_confirmed=not self.surface_only,
                      boundary_geometry_scope="Trimmed planar face loops, not pocket count, tool accessibility or machining feasibility.")
        allowance = min(MAX_FACE_BOUNDARY_EDGES, self.remaining_edges)
        for wire, expected in zip(wires, counts):
            row = dict(outer=not outer.IsNull() and wire.IsSame(outer),
                       closed=bool(BRep_Tool.IsClosed_s(wire)), edges=[],
                       total_edge_count=expected, ordered=True)
            result["boundary_wires"].append(row)
            explorer = BRepTools_WireExplorer(wire, face)
            while explorer.More() and allowance > 0:
                try:
                    row["edges"].append(self._edge(explorer.Current(), face))
                except Exception as exc:
                    row["edges"].append(dict(kind="unknown", geometry_status="error", error=str(exc)))
                    result["boundary_status"] = "partial"
                allowance -= 1
                self.remaining_edges -= 1
                explorer.Next()
            if explorer.More() or len(row["edges"]) != expected:
                result["boundary_status"] = "partial"
                row["ordered"] = False
                row["unresolved_edge_count"] = max(0, expected - len(row["edges"]))
        if not wires:
            result["boundary_status"] = "partial"
        if result["boundary_status"] != "complete":
            result["boundary_limit_or_error"] = "Boundary extraction incomplete; never interpret omitted edges as absent."
        return result


def trimmed_analytic_face(face, context):
    """Additional plane/cylinder information; failures never erase AM features."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepTools import BRepTools
    from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder
    from OCP.GProp import GProp_GProps
    surface = BRepAdaptor_Surface(face, True)
    if surface.GetType() not in (GeomAbs_Plane, GeomAbs_Cylinder):
        return {}
    result = dict(analytic_geometry_version=1)
    try:
        properties = GProp_GProps()
        error = BRepGProp.SurfaceProperties_s(face, properties, AREA_RELATIVE_TOLERANCE, False)
        if not np.isfinite([properties.Mass(), error]).all() or properties.Mass() <= 0 or error < 0 or error > 100 * AREA_RELATIVE_TOLERANCE:
            raise ValueError("Trimmed face area integration did not meet the numerical convergence policy.")
        result.update(area_mm2=properties.Mass(), centroid_mm=list(properties.CentreOfMass().Coord()),
                      area_integration_relative_error_estimate=error)
    except Exception as exc:
        result.update(area_mm2=None, centroid_mm=None, area_measurement_error=str(exc))
    if surface.GetType() == GeomAbs_Plane:
        plane = surface.Plane()
        result.update(plane_origin_mm=list(plane.Location().Coord()),
                      x_direction=list(plane.XAxis().Direction().Coord()),
                      y_direction=list(plane.YAxis().Direction().Coord()))
        try:
            result.update(context.planar_wires(face))
        except Exception as exc:
            result.update(boundary_status="error", boundary_wires=None, boundary_error=str(exc))
    else:
        cylinder = surface.Cylinder()
        u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
        origin = np.asarray(cylinder.Location().Coord())
        axis = np.asarray(cylinder.Axis().Direction().Coord())
        result.update(u_span_rad=float(u1 - u0), axial_parameter_range_mm=[float(v0), float(v1)],
                      axis_endpoints_mm=[(origin + axis * v0).tolist(), (origin + axis * v1).tolist()],
                      axial_extent_scope="UV-bound axial span of this trimmed cylindrical face; not drill depth or hole connectivity.")
    return result
