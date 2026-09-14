"""OCCT isolation boundary. All transferred STEP solids retain face/body mapping.

Only analytic cylinder dimensions are called analytic measurements. Triangulation
settings are requested tolerances, not certified error bounds.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import sys

import numpy as np

INTEGRATION_RELATIVE_TOLERANCE = 1e-9
MAX_CAD_SOLIDS = 1000


def zero_parameter_area(face):
    """Confirm an exactly collapsed parameter interval and zero B-rep area.

    No tolerance is used to discard a small but real face. Some valid imported
    STEP solids retain a cylinder trimmed to a curve; it has no triangulation
    and can stall adaptive integration despite contributing exactly zero area.
    """
    from OCP.BRepTools import BRepTools
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    if not np.isfinite([u0, u1, v0, v1]).all() or (u0 != u1 and v0 != v1):
        return False
    area = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, area, False, False)
    return area.Mass() == 0.0


def integrated_properties(shape, *, include_volume=True):
    """Integrate analytic surfaces with an explicit numerical stopping rule.

    OCCT's default, non-adaptive overload can differ materially on B-splines.
    Its returned estimates describe quadrature convergence, not source-CAD
    accuracy, a certified global bound, or a manufacturing tolerance.
    """
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopoDS import TopoDS, TopoDS_Compound
    from OCP.BRep import BRep_Builder
    faces = [TopoDS.Face_s(face) for face in items(shape, TopAbs_FACE)]
    nonzero_faces = [face for face in faces if not zero_parameter_area(face)]
    skipped = len(faces) - len(nonzero_faces)
    if skipped:
        # A separate integration compound leaves the imported B-rep unchanged.
        integration_shape, builder = TopoDS_Compound(), BRep_Builder()
        builder.MakeCompound(integration_shape)
        for face in nonzero_faces:
            builder.Add(integration_shape, face)
    else:
        integration_shape = shape
    area = GProp_GProps()
    area_error = BRepGProp.SurfaceProperties_s(integration_shape, area, INTEGRATION_RELATIVE_TOLERANCE, False)
    volume_value = volume_error = None
    if include_volume:
        volume = GProp_GProps()
        volume_error = BRepGProp.VolumeProperties_s(integration_shape, volume, INTEGRATION_RELATIVE_TOLERANCE, False, False)
        volume_value = volume.Mass()
    # A failed/non-finite integration must not be advertised as an exact mass.
    for name, value, error in [("면적", area.Mass(), area_error)] + (
            [("체적", volume_value, volume_error)] if include_volume else []):
        if not np.isfinite(value) or value <= 0 or not np.isfinite(error) or error < 0:
            raise ValueError(f"CAD {name} 적분에서 유효한 양의 값과 수렴 추정치를 확인하지 못했습니다.")
        if error > INTEGRATION_RELATIVE_TOLERANCE * 100:
            raise ValueError(f"CAD {name} 적분의 수렴 추정치가 요청 허용오차를 크게 초과했습니다 ({error:g}).")
    return dict(volume_mm3=volume_value, area_mm2=area.Mass(),
        integration=dict(method="OCCT adaptive 2D Gauss over analytic B-rep surfaces",
            requested_relative_tolerance=INTEGRATION_RELATIVE_TOLERANCE,
            exactly_zero_parameter_area_faces_excluded=skipped,
            volume_relative_error_estimate=volume_error, area_relative_error_estimate=area_error,
            limitation="Numerical quadrature estimates; not certified geometric or manufacturing error bounds."))


def items(shape, kind):
    from OCP.TopExp import TopExp_Explorer
    exp = TopExp_Explorer(shape, kind)
    while exp.More():
        yield exp.Current()
        exp.Next()


def mesh_topology(shape):
    """Check the actual tessellation without modifying or tolerance-welding it."""
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopoDS import TopoDS
    from OCP.TopLoc import TopLoc_Location
    from OCP.BRep import BRep_Tool
    import trimesh
    xyz, cells, offset, missing = [], [], 0, 0
    for raw in items(shape, TopAbs_FACE):
        face, location = TopoDS.Face_s(raw), TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, location)
        if tri is None or not tri.NbTriangles():
            missing += not zero_parameter_area(face)
            continue
        vertices = np.asarray([tri.Node(i).Transformed(location.Transformation()).Coord()
            for i in range(1, tri.NbNodes()+1)])
        faces = np.asarray([tri.Triangle(i).Get() for i in range(1, tri.NbTriangles()+1)], dtype=np.int64)-1
        if face.Orientation() == TopAbs_REVERSED:
            faces = faces[:, [0,2,1]]
        xyz.append(vertices)
        cells.append(faces+offset)
        offset += len(vertices)
    if not xyz:
        return dict(ready=False, triangle_count=0, missing_nonzero_faces=int(missing))
    vertices, inverse = np.unique(np.vstack(xyz), axis=0, return_inverse=True)
    mesh = trimesh.Trimesh(vertices, inverse[np.vstack(cells)], process=False)
    keep = mesh.area_faces > 0
    zero = int((~keep).sum())
    original_count = len(mesh.faces)
    mesh.update_faces(keep)
    edges, counts = np.unique(np.sort(mesh.edges, axis=1), axis=0, return_counts=True)
    duplicates = len(mesh.faces)-len(np.unique(np.sort(mesh.faces, axis=1), axis=0))
    return dict(ready=bool(not missing and mesh.is_watertight and mesh.is_winding_consistent and not duplicates),
        triangle_count=original_count, zero_area_cells=zero, missing_nonzero_faces=int(missing),
        boundary_edges=int((counts==1).sum()), nonmanifold_edges=int((counts>2).sum()),
        duplicate_triangles=int(duplicates), winding_consistent=bool(mesh.is_winding_consistent),
        watertight=bool(mesh.is_watertight))


def prepare_tessellation(shape, deflection, remaining_triangles, *, surface_only=False):
    """Retry failed solid tessellation at finer resolution on a separate copy.

    We adopt a candidate only if closedness, winding and duplicate checks all
    recover. A failed candidate leaves the original triangulation available.
    Neither candidate repairs/sews the source B-rep or tolerance-welds vertices.
    """
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    mesher = BRepMesh_IncrementalMesh(shape, deflection, False, .15, False)
    if not mesher.IsDone():
        raise ValueError("CAD 솔리드/곡면의 메시 변환이 완료되지 않았습니다.")
    original = mesh_topology(shape)
    record = dict(requested_deflection_mm=deflection, effective_deflection_mm=deflection,
        original_topology=original, retry=None, adopted_refinement=False)
    if surface_only or original["ready"] or deflection <= .001:
        return shape, record
    finer = max(.001, deflection/5)
    try:
        # copyGeom=True and copyMesh=False explicitly detach triangulation per
        # the OCCT 7.9 API; copyGeom=False may share cached mesh handles.
        candidate = BRepBuilderAPI_Copy(shape, True, False).Shape()
        retry_mesher = BRepMesh_IncrementalMesh(candidate, finer, False, .15, False)
        diagnosis = mesh_topology(candidate) if retry_mesher.IsDone() else dict(ready=False, error="mesher_not_done")
        record["retry"] = dict(requested_deflection_mm=finer, topology=diagnosis)
        if diagnosis["ready"] and diagnosis["triangle_count"] <= remaining_triangles:
            record.update(effective_deflection_mm=finer, adopted_refinement=True)
            return candidate, record
        record["retry"]["not_adopted_reason"] = ("triangle_budget" if diagnosis.get("triangle_count",0)>remaining_triangles
            else "topology_not_recovered")
    except Exception as exc:
        record["retry"] = dict(requested_deflection_mm=finer, not_adopted_reason="retry_failed", error=str(exc))
    return shape, record


def convert(source, destination, deflection):
    from OCP.STEPControl import STEPControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.TColStd import TColStd_SequenceOfAsciiString
    from OCP.TopAbs import TopAbs_SOLID, TopAbs_FACE, TopAbs_SHELL, TopAbs_REVERSED, TopAbs_IN
    from OCP.TopoDS import TopoDS
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRep import BRep_Tool
    from OCP.TopLoc import TopLoc_Location
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepTools import BRepTools
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.gp import gp_Pnt2d

    reader = STEPControl_Reader()
    if reader.ReadFile(str(source)) != IFSelect_RetDone:
        raise ValueError("OCCT가 STEP 교환 파일을 읽지 못했습니다.")
    lengths, angles, solids_angles = (TColStd_SequenceOfAsciiString() for _ in range(3))
    reader.FileUnits(lengths, angles, solids_angles)
    unit_names = [lengths.Value(i).ToCString() for i in range(1, lengths.Length() + 1)]
    if not unit_names:
        raise ValueError("STEP 길이 단위를 확인하지 못했습니다. 단위가 선언된 STEP으로 다시 내보내세요.")
    reader.SetSystemLengthUnit(1.0)  # OCCT length unit expressed in mm
    roots = reader.NbRootsForTransfer()
    transferred = reader.TransferRoots()
    if roots < 1 or transferred != roots:
        raise ValueError(f"STEP 루트 일부만 변환되었습니다 ({transferred}/{roots}). 부분 형상을 전체로 평가하지 않습니다.")
    shape = reader.OneShape()
    if shape.IsNull():
        raise ValueError("변환된 STEP 형상이 비어 있습니다.")
    solids = [TopoDS.Solid_s(s) for s in items(shape, TopAbs_SOLID)]
    # Reject mixed solid + free-surface imports rather than silently dropping data.
    all_face_count = sum(1 for _ in items(shape, TopAbs_FACE))
    solid_face_count = sum(sum(1 for _ in items(s, TopAbs_FACE)) for s in solids)
    if not all_face_count:
        raise ValueError("STEP에 검토할 면이 없습니다. 선·점만 있는 입력은 지원하지 않습니다.")
    surface_only = not solids
    if solids and all_face_count != solid_face_count:
        raise ValueError("솔리드 외의 독립 곡면이 함께 들어 있습니다. 검토할 솔리드만 내보내세요.")
    if len(solids) > MAX_CAD_SOLIDS or all_face_count > 20_000:
        raise ValueError(f"CAD 솔리드 {MAX_CAD_SOLIDS:,}개 / 면 20,000개 한도를 초과했습니다.")
    if not BRepCheck_Analyzer(shape).IsValid():
        raise ValueError("OCCT B-rep 유효성 검사가 실패했습니다. CAD에서 형상 검사/복구 후 다시 내보내세요.")

    vertices, triangles, face_ids, body_ids, features, bodies = [], [], [], [], [], []
    unmeshed_zero_area_faces = []
    tessellation_attempts = []
    offset = 0
    face_id = 0
    total_triangles = 0
    groups = [(0, shape)] if surface_only else list(enumerate(solids, 1))
    surface_properties = integrated_properties(shape, include_volume=False) if surface_only else None
    for body_id, solid in groups:
        properties = surface_properties if surface_only else integrated_properties(solid)
        box = Bnd_Box()
        BRepBndLib.AddOptimal_s(solid, box, False, False)
        bounds = box.Get()
        if not surface_only:
            cavity_shells = max(0, sum(1 for _ in items(solid, TopAbs_SHELL)) - 1)
            bodies.append(dict(body_id=body_id, valid=True, **properties,
                bounds_mm=[list(bounds[:3]), list(bounds[3:])], cavity_shell_count=cavity_shells))
        solid, attempt = prepare_tessellation(solid, deflection, 600_000-total_triangles, surface_only=surface_only)
        tessellation_attempts.append(dict(body_id=body_id, **attempt))
        for raw_face in items(solid, TopAbs_FACE):
            face_id += 1
            face = TopoDS.Face_s(raw_face)
            loc = TopLoc_Location()
            tri = BRep_Tool.Triangulation_s(face, loc)
            if tri is None or tri.NbTriangles() == 0:
                if zero_parameter_area(face):
                    record = dict(face_id=face_id, body_id=body_id, kind="zero_area_trim",
                        uv_bounds=list(BRepTools.UVBounds_s(face)), area_mm2=0.,
                        scope="Exactly collapsed UV interval and zero analytic-surface integral; no triangle or material area to omit.")
                    unmeshed_zero_area_faces.append(record)
                    features.append(record)
                    continue
                raise ValueError(f"CAD 면 {face_id}의 메시가 없습니다. 누락된 면을 제외하지 않습니다.")
            total_triangles += tri.NbTriangles()
            if total_triangles > 600_000:
                raise ValueError("CAD 메시가 600,000 삼각형 한도를 초과했습니다. 목표 편차를 늘려 다시 시도하세요.")
            transform = loc.Transformation()
            xyz = np.array([tri.Node(i).Transformed(transform).Coord() for i in range(1, tri.NbNodes() + 1)])
            faces = np.array([tri.Triangle(i).Get() for i in range(1, tri.NbTriangles() + 1)], dtype=np.int64) - 1
            if face.Orientation() == TopAbs_REVERSED:
                faces = faces[:, [0, 2, 1]]
            vertices.append(xyz)
            triangles.append(faces + offset)
            offset += len(xyz)
            face_ids.extend([face_id] * len(faces))
            body_ids.extend([body_id] * len(faces))
            surface = BRepAdaptor_Surface(face, True)
            feature = dict(face_id=face_id, body_id=body_id, kind="other", center_mm=xyz.mean(axis=0).tolist())
            if surface.GetType() == GeomAbs_Plane:
                plane = surface.Plane()
                normal = np.array(plane.Axis().Direction().Coord())
                if face.Orientation() == TopAbs_REVERSED:
                    normal *= -1
                feature.update(kind="plane", normal=normal.tolist())
            elif surface.GetType() == GeomAbs_Cylinder:
                cylinder = surface.Cylinder()
                u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
                # A trimmed cylinder may not contain its parameter midpoint.
                # Leave its concavity unknown in that case, rather than inventing a hole.
                state = BRepClass_FaceClassifier(face, gp_Pnt2d((u0 + u1) / 2, (v0 + v1) / 2), 1e-7).State()
                role = "unknown"
                if state == TopAbs_IN and not surface_only:
                    role = "inner" if face.Orientation() == TopAbs_REVERSED else "outer"
                feature.update(kind="cylinder", role=role, diameter_mm=2 * cylinder.Radius(),
                    axis=list(cylinder.Axis().Direction().Coord()),
                    axis_point_mm=list(cylinder.Location().Coord()), axial_extent_mm=float(v1 - v0),
                    full_circumference=bool(abs((u1-u0)-2*math.pi) < 1e-6),
                    recognition_scope="analytic cylindrical face; not hole count or through-hole certification")
            features.append(feature)

    np.savez_compressed(str(destination) + ".npz", vertices=np.vstack(vertices), faces=np.vstack(triangles),
                        face_ids=np.asarray(face_ids), body_ids=np.asarray(body_ids))
    exact_volume = bodies[0]["volume_mm3"] if len(bodies) == 1 else None
    exact_area = surface_properties["area_mm2"] if surface_only else (bodies[0]["area_mm2"] if len(bodies) == 1 else None)
    mesh = __import__("trimesh").Trimesh(vertices=np.vstack(vertices), faces=np.vstack(triangles), process=False)
    meta = dict(cad_kernel="Open CASCADE via cadquery-ocp-novtk 7.9.3.1.1", cad_valid=True,
        declared_step_units=unit_names, transferred_roots=transferred, solid_count=len(solids),
        cad_geometry_kind="surface" if surface_only else "solid",
        cad_face_count=face_id, bodies=bodies, exact_volume_mm3=exact_volume, exact_area_mm2=exact_area,
        constituent_volume_sum_mm3=None if surface_only else sum(b["volume_mm3"] for b in bodies),
        cavity_shell_count=None if surface_only else sum(b["cavity_shell_count"] for b in bodies),
        property_integration=(surface_properties["integration"] if surface_only else
            {"requested_relative_tolerance": INTEGRATION_RELATIVE_TOLERANCE,
             "method": "OCCT adaptive 2D Gauss over analytic B-rep surfaces", "per_body": [b["integration"] for b in bodies]}),
        tessellation=dict(requested_linear_deflection_mm=deflection, requested_angular_deflection_rad=.15,
            relative=False, triangle_count=total_triangles,
            unmeshed_exactly_zero_area_faces=unmeshed_zero_area_faces,
            body_attempts=tessellation_attempts,
            volume_relative_difference=(abs(mesh.volume-exact_volume)/exact_volume if exact_volume else None),
            limitation="Requested deflection is not a certified Hausdorff error bound; volume agreement is not local accuracy."),
        features=features, assembly_overlap="not_checked" if len(bodies)>1 else "not_applicable",
        surface_scope=("All imported faces tessellated; no solid construction or sewing; material side, volume, cavities and wall thickness are unconfirmed." if surface_only else None),
        cad_translation_policy="OCCT default STEP transfer and built-in shape processing; no separate healing requested. Validity is checked after translation.",
        pmi="not_imported", external_references="No external reference resolution; all transfer roots must succeed.")
    Path(str(destination) + ".json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    destination = Path(sys.argv[2])
    try:
        convert(Path(sys.argv[1]), destination, float(sys.argv[3]))
    except Exception as exc:
        destination.with_suffix(".json").write_text(json.dumps({"error": str(exc)}, ensure_ascii=False), encoding="utf-8")
        raise SystemExit(1)
