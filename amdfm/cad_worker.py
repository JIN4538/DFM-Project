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


def items(shape, kind):
    from OCP.TopExp import TopExp_Explorer
    exp = TopExp_Explorer(shape, kind)
    while exp.More():
        yield exp.Current()
        exp.Next()


def convert(source, destination, deflection):
    from OCP.STEPControl import STEPControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.TColStd import TColStd_SequenceOfAsciiString
    from OCP.TopAbs import TopAbs_SOLID, TopAbs_FACE, TopAbs_SHELL, TopAbs_REVERSED, TopAbs_IN
    from OCP.TopoDS import TopoDS
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
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
    if not solids:
        raise ValueError("닫힌 솔리드가 없는 STEP입니다. 곡면/선만 있는 파일은 지원하지 않습니다.")
    # Reject mixed solid + free-surface imports rather than silently dropping data.
    all_face_count = sum(1 for _ in items(shape, TopAbs_FACE))
    solid_face_count = sum(sum(1 for _ in items(s, TopAbs_FACE)) for s in solids)
    if all_face_count != solid_face_count:
        raise ValueError("솔리드 외의 독립 곡면이 함께 들어 있습니다. 검토할 솔리드만 내보내세요.")
    if len(solids) > 100 or all_face_count > 20_000:
        raise ValueError("CAD 솔리드 100개 / 면 20,000개 한도를 초과했습니다.")
    if not BRepCheck_Analyzer(shape).IsValid():
        raise ValueError("OCCT B-rep 유효성 검사가 실패했습니다. CAD에서 형상 검사/복구 후 다시 내보내세요.")

    vertices, triangles, face_ids, body_ids, features, bodies = [], [], [], [], [], []
    offset = 0
    face_id = 0
    total_triangles = 0
    for body_id, solid in enumerate(solids, 1):
        vprop, aprop = GProp_GProps(), GProp_GProps()
        BRepGProp.VolumeProperties_s(solid, vprop)
        BRepGProp.SurfaceProperties_s(solid, aprop)
        if vprop.Mass() <= 0:
            raise ValueError(f"솔리드 {body_id}의 양의 재료 체적을 확인할 수 없습니다.")
        box = Bnd_Box()
        BRepBndLib.AddOptimal_s(solid, box, False, False)
        bounds = box.Get()
        cavity_shells = max(0, sum(1 for _ in items(solid, TopAbs_SHELL)) - 1)
        bodies.append(dict(body_id=body_id, valid=True, volume_mm3=vprop.Mass(),
            area_mm2=aprop.Mass(), bounds_mm=[list(bounds[:3]), list(bounds[3:])],
            cavity_shell_count=cavity_shells))
        mesher = BRepMesh_IncrementalMesh(solid, deflection, False, 0.15, False)
        if not mesher.IsDone():
            raise ValueError(f"솔리드 {body_id}의 메시 변환이 완료되지 않았습니다.")
        for raw_face in items(solid, TopAbs_FACE):
            face_id += 1
            face = TopoDS.Face_s(raw_face)
            loc = TopLoc_Location()
            tri = BRep_Tool.Triangulation_s(face, loc)
            if tri is None or tri.NbTriangles() == 0:
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
                if state == TopAbs_IN:
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
    exact_area = bodies[0]["area_mm2"] if len(bodies) == 1 else None
    mesh = __import__("trimesh").Trimesh(vertices=np.vstack(vertices), faces=np.vstack(triangles), process=False)
    meta = dict(cad_kernel="Open CASCADE via cadquery-ocp-novtk 7.9.3.1.1", cad_valid=True,
        declared_step_units=unit_names, transferred_roots=transferred, solid_count=len(solids),
        cad_face_count=face_id, bodies=bodies, exact_volume_mm3=exact_volume, exact_area_mm2=exact_area,
        constituent_volume_sum_mm3=sum(b["volume_mm3"] for b in bodies),
        cavity_shell_count=sum(b["cavity_shell_count"] for b in bodies),
        tessellation=dict(requested_linear_deflection_mm=deflection, requested_angular_deflection_rad=.15,
            relative=False, triangle_count=total_triangles,
            volume_relative_difference=(abs(mesh.volume-exact_volume)/exact_volume if exact_volume else None),
            limitation="Requested deflection is not a certified Hausdorff error bound; volume agreement is not local accuracy."),
        features=features, assembly_overlap="not_checked" if len(bodies)>1 else "not_applicable",
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
