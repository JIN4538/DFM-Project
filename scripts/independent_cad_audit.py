"""Read-only, independent geometric audit of local exchange files.

This script deliberately imports no application module. B-rep mass integration
and explicit triangle divergence integration are different numerical paths, but
both STEP paths still depend on OCCT translation; agreement is not certification.
No imported geometry is changed or uploaded. Every run requires a new output dir.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

import numpy as np


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def occurrences(shape, kind):
    from OCP.TopExp import TopExp_Explorer
    it = TopExp_Explorer(shape, kind)
    while it.More():
        yield it.Current()
        it.Next()


def quadrature_shape(solid):
    """Remove only exactly zero parameter-area faces from a separate integrand.

    The source TopoDS shape remains intact. An exactly collapsed cylinder trim
    was observed in Valve face 124; adaptive OCCT integration otherwise stalls.
    """
    from OCP.BRep import BRep_Builder
    from OCP.BRepTools import BRepTools
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopoDS import TopoDS, TopoDS_Compound
    faces, omitted = [], []
    for i, raw in enumerate(occurrences(solid, TopAbs_FACE), 1):
        face = TopoDS.Face_s(raw)
        uv = BRepTools.UVBounds_s(face)
        if uv[0] == uv[1] or uv[2] == uv[3]:
            area = GProp_GProps()
            BRepGProp.SurfaceProperties_s(face, area)
            if area.Mass() == 0:
                omitted.append(dict(face_id_in_body=i, uv=uv, area_mm2=0))
                continue
        faces.append(face)
    if not omitted:
        return solid, omitted
    compound, builder = TopoDS_Compound(), BRep_Builder()
    builder.MakeCompound(compound)
    for face in faces:
        builder.Add(compound, face)
    return compound, omitted


def mesh_statistics(vertices, faces):
    """Explicit, translated-to-origin divergence sum (no trimesh mass call)."""
    import trimesh
    vertices = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int64)
    center = (vertices.min(0) + vertices.max(0)) / 2
    p = vertices[faces] - center
    cross = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    areas = np.linalg.norm(cross, axis=1) / 2
    volume = math.fsum((np.einsum("ij,ij->i", p[:, 0], np.cross(p[:, 1], p[:, 2])) / 6).tolist())
    unique, inv = np.unique(vertices, axis=0, return_inverse=True)
    mesh = trimesh.Trimesh(unique, inv[faces], process=False)
    edges = np.sort(mesh.edges, axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return dict(triangles=len(faces), vertices=len(vertices), exact_coordinate_vertices=len(unique),
        bounds_mm=[vertices.min(0).tolist(), vertices.max(0).tolist()], extents_mm=np.ptp(vertices, axis=0).tolist(),
        signed_volume_divergence_mm3=volume, area_triangle_sum_mm2=math.fsum(areas.tolist()),
        exact_weld_watertight=bool(mesh.is_watertight), winding_consistent=bool(mesh.is_winding_consistent),
        boundary_edges=int((counts == 1).sum()), nonmanifold_edges=int((counts > 2).sum()),
        zero_area_triangles=int((areas == 0).sum()), vertex_component_count=int(mesh.body_count),
        geometry_note="STL units are an mm scenario; no self-intersection certificate; sums of shells are not Boolean unions")


def tessellate(solid, linear):
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRepTools import BRepTools
    from OCP.BRep import BRep_Tool
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS
    BRepTools.Clean_s(solid)
    mesher = BRepMesh_IncrementalMesh(solid, linear, False, .15, False)
    if not mesher.IsDone():
        raise RuntimeError("independent OCCT tessellation did not complete")
    vertices, faces, offset, missing = [], [], 0, []
    for index, item in enumerate(occurrences(solid, TopAbs_FACE), 1):
        face, location = TopoDS.Face_s(item), TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, location)
        if tri is None or not tri.NbTriangles():
            missing.append(index)
            continue
        xyz = np.array([tri.Node(i).Transformed(location.Transformation()).Coord() for i in range(1, tri.NbNodes()+1)])
        cells = np.array([tri.Triangle(i).Get() for i in range(1, tri.NbTriangles()+1)]) - 1
        if face.Orientation() == TopAbs_REVERSED:
            cells = cells[:, [0, 2, 1]]
        vertices.append(xyz)
        faces.append(cells + offset)
        offset += len(xyz)
    if not vertices:
        return None, None, {"error": "no triangulated faces", "missing_faces": missing}
    vertices, faces = np.vstack(vertices), np.vstack(faces)
    stats = mesh_statistics(vertices, faces)
    stats.update(requested_deflection_mm=linear, requested_angle_rad=.15, missing_faces=missing)
    return vertices, faces, stats


def step_audit(path, out, refine, skip_gk=False):
    from OCP.STEPControl import STEPControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.TColStd import TColStd_SequenceOfAsciiString
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.BRepBndLib import BRepBndLib
    from OCP.Bnd import Bnd_Box
    from OCP.TopAbs import TopAbs_SOLID, TopAbs_FACE, TopAbs_SHELL, TopAbs_REVERSED, TopAbs_IN, TopAbs_OUT
    from OCP.TopoDS import TopoDS
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepTools import BRepTools
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.gp import gp_Pnt, gp_Pnt2d
    from OCP.GeomAbs import GeomAbs_Cylinder
    reader = STEPControl_Reader()
    if reader.ReadFile(str(path)) != IFSelect_RetDone:
        raise ValueError("OCCT read failure")
    units, a, b = [TColStd_SequenceOfAsciiString() for _ in range(3)]
    reader.FileUnits(units, a, b)
    reader.SetSystemLengthUnit(1.)
    roots = reader.NbRootsForTransfer()
    transferred = reader.TransferRoots()
    shape = reader.OneShape()
    solids = [TopoDS.Solid_s(x) for x in occurrences(shape, TopAbs_SOLID)]
    result = dict(units=[units.Value(i).ToCString() for i in range(1, units.Length()+1)], roots=roots,
        transferred_roots=transferred, brep_valid=bool(BRepCheck_Analyzer(shape).IsValid()), solid_count=len(solids),
        all_face_occurrences=sum(1 for _ in occurrences(shape, TopAbs_FACE)), bodies=[])
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, box, False, False)
    bound = box.Get()
    result.update(bounds_mm=[list(bound[:3]), list(bound[3:])], extents_mm=(np.array(bound[3:])-bound[:3]).tolist())
    all_xyz, all_cells, mesh_offset = [], [], 0
    for index, solid in enumerate(solids, 1):
        integrand, zero_faces = quadrature_shape(solid)
        basic, adaptive, kronrod, area, tight_area = [GProp_GProps() for _ in range(5)]
        BRepGProp.VolumeProperties_s(solid, basic, False, False, False)
        adaptive_error = BRepGProp.VolumeProperties_s(integrand, adaptive, 1e-9, False, False)
        kronrod_error = (None if skip_gk else
            BRepGProp.VolumePropertiesGK_s(integrand, kronrod, 1e-9, False, True, False, False, False))
        BRepGProp.SurfaceProperties_s(solid, area, False, False)
        area_error = BRepGProp.SurfaceProperties_s(integrand, tight_area, 1e-9, False)
        box = Bnd_Box()
        BRepBndLib.AddOptimal_s(solid, box, False, False)
        bb = box.Get()
        body = dict(body_id=index, valid=bool(BRepCheck_Analyzer(solid).IsValid()),
            orientation=str(solid.Orientation()), shell_count=sum(1 for _ in occurrences(solid, TopAbs_SHELL)),
            face_count=sum(1 for _ in occurrences(solid, TopAbs_FACE)), bounds_mm=[list(bb[:3]), list(bb[3:])],
            volume_default_mm3=basic.Mass(), volume_adaptive_gauss_mm3=adaptive.Mass(),
            volume_gauss_kronrod_mm3=None if skip_gk else kronrod.Mass(), adaptive_error_estimate=adaptive_error,
            gauss_kronrod_error_estimate=kronrod_error, area_default_mm2=area.Mass(),
            area_adaptive_mm2=tight_area.Mass(), area_error_estimate=area_error,
            exact_zero_parameter_area_faces=zero_faces,
            cylinder_roles=[], surface_types=dict(Counter(str(BRepAdaptor_Surface(TopoDS.Face_s(f)).GetType())
                for f in occurrences(solid, TopAbs_FACE))), mesh_refinements=[])
        for face_id, item in enumerate(occurrences(solid, TopAbs_FACE), 1):
            face = TopoDS.Face_s(item)
            surface = BRepAdaptor_Surface(face, True)
            if surface.GetType() != GeomAbs_Cylinder:
                continue
            cyl = surface.Cylinder()
            u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
            u, v = (u0+u1)/2, (v0+v1)/2
            state = BRepClass_FaceClassifier(face, gp_Pnt2d(u, v), 1e-7).State()
            policy_role = ("inner" if face.Orientation() == TopAbs_REVERSED else "outer") if state == TopAbs_IN else "unknown"
            probe_role, probe = "unknown", None
            # Find an interior UV point independent of the midpoint-only policy.
            for fu, fv in [(x, y) for x in (.5, .25, .75, .125, .875) for y in (.5, .25, .75)]:
                u, v = u0+(u1-u0)*fu, v0+(v1-v0)*fv
                if BRepClass_FaceClassifier(face, gp_Pnt2d(u, v), 1e-8).State() != TopAbs_IN:
                    continue
                point = np.array(surface.Value(u, v).Coord())
                axis = np.array(cyl.Axis().Direction().Coord())
                radial = point-np.array(cyl.Location().Coord())
                radial -= axis*np.dot(radial, axis)
                radial /= np.linalg.norm(radial)
                epsilon = min(1e-3, max(1e-5, cyl.Radius()*1e-4))
                plus = BRepClass3d_SolidClassifier(solid, gp_Pnt(*(point+epsilon*radial)), epsilon*.01).State()
                minus = BRepClass3d_SolidClassifier(solid, gp_Pnt(*(point-epsilon*radial)), epsilon*.01).State()
                if plus == TopAbs_IN and minus == TopAbs_OUT:
                    probe_role = "inner"
                elif plus == TopAbs_OUT and minus == TopAbs_IN:
                    probe_role = "outer"
                probe = dict(point_mm=point.tolist(), radial_epsilon_mm=epsilon, plus=str(plus), minus=str(minus))
                if probe_role != "unknown":
                    break
            body["cylinder_roles"].append(dict(face_id_in_body=face_id, diameter_mm=2*cyl.Radius(),
                midpoint_orientation_role=policy_role, radial_solid_probe_role=probe_role, probe=probe))
        for deflection in ([.1, .05, .01] if refine else [.05]):
            xyz, cells, stats = tessellate(solid, deflection)
            if xyz is not None:
                stats["volume_relative_difference_from_adaptive"] = ((stats["signed_volume_divergence_mm3"]-adaptive.Mass())/adaptive.Mass() if adaptive.Mass() else None)
                stats["area_relative_difference_from_adaptive"] = ((stats["area_triangle_sum_mm2"]-tight_area.Mass())/tight_area.Mass() if tight_area.Mass() else None)
                if deflection == .05:
                    all_xyz.append(xyz)
                    all_cells.append(cells+mesh_offset)
                    mesh_offset += len(xyz)
            body["mesh_refinements"].append(stats)
        result["bodies"].append(body)
        out.with_suffix(".partial.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if all_xyz:
        np.savez_compressed(out.with_suffix(".mesh.npz"), vertices=np.vstack(all_xyz), faces=np.vstack(all_cells))
    result["constituent_volume_sum_adaptive_mm3"] = math.fsum(b["volume_adaptive_gauss_mm3"] for b in result["bodies"])
    result["constituent_area_sum_adaptive_mm2"] = math.fsum(b["area_adaptive_mm2"] for b in result["bodies"])
    result["union_volume_mm3"] = result["constituent_volume_sum_adaptive_mm3"] if len(solids)==1 else None
    result["scope"] = "OCCT STEP transfer, separate default/adaptive Gauss/Gauss-Kronrod B-rep integration, independently summed triangle volume; constituent mass is not union mass"
    return result


def stl_audit(path, out):
    import trimesh
    mesh = trimesh.load(path, file_type="stl", process=False)
    result = mesh_statistics(mesh.vertices, mesh.faces)
    np.savez_compressed(out.with_suffix(".mesh.npz"), vertices=mesh.vertices, faces=mesh.faces)
    return result


def threemf_audit(path):
    result = dict(models=[])
    with zipfile.ZipFile(path) as z:
        result["members"] = [dict(name=i.filename, compressed_bytes=i.compress_size, uncompressed_bytes=i.file_size) for i in z.infolist()]
        for item in z.infolist():
            if not item.filename.lower().endswith(".model"):
                continue
            root = ET.fromstring(z.read(item))
            model = dict(member=item.filename, attributes=root.attrib, objects=[], build=[])
            for node in root.iter():
                tag = node.tag.rsplit("}",1)[-1]
                if tag == "object":
                    vertices = [x for x in node.iter() if x.tag.rsplit("}",1)[-1] == "vertex"]
                    triangles = [x for x in node.iter() if x.tag.rsplit("}",1)[-1] == "triangle"]
                    obj = dict(attributes=node.attrib, vertices=len(vertices), triangles=len(triangles),
                        components=[x.attrib for x in node.iter() if x.tag.rsplit("}",1)[-1] == "component"])
                    if vertices:
                        xyz = np.array([[float(x.attrib[k]) for k in ("x","y","z")] for x in vertices])
                        obj["untransformed_bounds"] = [xyz.min(0).tolist(),xyz.max(0).tolist()]
                        obj["untransformed_extents"] = np.ptp(xyz,axis=0).tolist()
                    model["objects"].append(obj)
                elif tag == "item":
                    model["build"].append(node.attrib)
            result["models"].append(model)
    return result


def paired_surface_checks(directory, source):
    """Compare surfaces rather than treating matching basenames as proof."""
    import trimesh
    def read_mesh(stem):
        with np.load(directory/(stem+".mesh.npz")) as values:
            return trimesh.Trimesh(values["vertices"],values["faces"],process=False)
    def distances(query, target):
        # Finite deterministic samples: not a continuous Hausdorff bound.
        vertices = np.unique(query.vertices,axis=0)
        points = np.vstack([vertices[np.linspace(0,len(vertices)-1,min(2000,len(vertices)),dtype=int)],
            query.triangles_center[np.linspace(0,len(query.faces)-1,min(2000,len(query.faces)),dtype=int)]])
        d = np.concatenate([trimesh.proximity.closest_point(target, p)[1] for p in np.array_split(points,16)])
        return dict(samples=len(points), maximum_mm=float(d.max()), p95_mm=float(np.quantile(d,.95)),
            mean_mm=float(d.mean()), rms_mm=float(np.sqrt(np.mean(d*d))))
    rows = []
    pairs = [("Arduino-UNO", "18_Arduino-UNO", "19_Arduino-UNO"),
             ("Raspberry Pi 4 Model B", "22_Raspberry Pi 4 Model B", "21_Raspberry Pi 4 Model B"),
             ("SG90-Servo", "23_SG90-Servo", "24_SG90-Servo")]
    for name, stl_name, step_name in pairs:
        stl, cad = read_mesh(stl_name), read_mesh(step_name)
        a = json.loads((directory/(stl_name+".json")).read_text(encoding="utf-8"))
        b = json.loads((directory/(step_name+".json")).read_text(encoding="utf-8"))
        rows.append(dict(name=name, formats=["STL", "STEP tessellation .05mm"],
            registration="None; source coordinates used without fitting or scaling",
            source_sha256=[a["source_sha256"],b["source_sha256"]],
            extents_difference_stl_minus_brep_mm=(np.array(a["extents_mm"])-b["extents_mm"]).tolist(),
            stl_to_cad_mesh=distances(stl,cad), cad_mesh_to_stl=distances(cad,stl),
            stl_signed_shell_volume_mm3=a["signed_volume_divergence_mm3"],
            cad_constituent_volume_mm3=b["constituent_volume_sum_adaptive_mm3"],
            stl_components=a["vertex_component_count"], cad_solids=b["solid_count"],
            material_region_note="Multiple body/shell integrals are not Boolean union volume; physical material assignments not established"))
    path = source/"the-over-engineered-backpack-wall-mount-v2.3mf"
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("3D/Objects/object_1.model"))
    v = np.asarray([[float(n.attrib[k]) for k in ("x","y","z")] for n in root.iter() if n.tag.endswith("}vertex")])
    f = np.asarray([[int(n.attrib[k]) for k in ("v1","v2","v3")] for n in root.iter() if n.tag.endswith("}triangle")])
    threemf = trimesh.Trimesh(v,f,process=False)
    stl = read_mesh("26_the-over-engineered-backpack-wall-mount-v2")
    translation = stl.bounds.mean(0)-threemf.bounds.mean(0)
    original_stats = mesh_statistics(v,f)
    threemf.apply_translation(translation)
    rows.append(dict(name="the-over-engineered-backpack-wall-mount-v2",formats=["STL","3MF resource mesh"],
        registration="3MF resource mesh translated to STL bounding-box center; no scaling/rotation or surface fitting",
        resource_to_stl_translation_mm=translation.tolist(),source_sha256=[sha(source/(path.stem+".stl")),sha(path)],
        stl_to_3mf=distances(stl,threemf),threemf_to_stl=distances(threemf,stl),
        threemf_raw_geometry=original_stats,
        build_transform_note="Separate .3mf build rotates +90deg about X and translates (128,128,21.0350876); raw resource coordinates compared here"))
    result = dict(pairs=rows, scope="Geometric consistency evidence from finite samples and volume; not identity proof or a certified Hausdorff tolerance")
    (directory/"paired-surface-comparisons.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--refine", action="store_true")
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument("--pairs", action="store_true")
    parser.add_argument("--skip-gk", action="store_true")
    args = parser.parse_args()
    if args.pairs:
        if (args.out/"paired-surface-comparisons.json").exists():
            raise ValueError("paired comparison output already exists")
        paired_surface_checks(args.out,args.source)
        return
    if args.worker:
        before, start = sha(args.source), time.perf_counter()
        try:
            suffix = args.source.suffix.lower()
            if suffix in (".step", ".stp"):
                result = step_audit(args.source, args.out, args.refine, args.skip_gk)
            elif suffix == ".stl":
                result = stl_audit(args.source, args.out)
            else:
                result = threemf_audit(args.source)
            result["status"] = "audited"
        except Exception as exc:
            import traceback
            result = {"status": "error", "error": str(exc), "traceback": traceback.format_exc()}
        result.update(source=str(args.source.resolve()), source_sha256=before,
            source_preserved=sha(args.source)==before, elapsed_seconds=time.perf_counter()-start,
            python=platform.python_version(), independent_audit_script_sha256=sha(Path(__file__)))
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        return
    args.out.mkdir(parents=True, exist_ok=False)
    paths = sorted(p for p in args.source.rglob("*") if p.suffix.lower() in (".stp", ".step", ".stl", ".3mf"))
    manifest = {"files": [], "source_directory": str(args.source), "script_sha256": sha(Path(__file__))}
    for index, path in enumerate(paths, 1):
        dest = args.out/f"{index:02d}_{path.stem}.json"
        command = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--worker", "--source", str(path), "--out", str(dest)]
        if args.refine:
            command.append("--refine")
        if args.skip_gk:
            command.append("--skip-gk")
        try:
            run = subprocess.run(command, capture_output=True, timeout=args.timeout)
            dest.with_suffix(".log").write_bytes(run.stdout+run.stderr)
            info = json.loads(dest.read_text(encoding="utf-8")) if dest.exists() else {"status":"worker_no_result"}
        except subprocess.TimeoutExpired as exc:
            dest.with_suffix(".log").write_bytes((exc.stdout or b"")+(exc.stderr or b""))
            info = dict(status="timeout", timeout_seconds=args.timeout)
        manifest["files"].append(dict(relative_source=path.relative_to(args.source).as_posix(), sha256=sha(path),
            result=dest.name, status=info["status"], elapsed_seconds=info.get("elapsed_seconds"),
            solid_count=info.get("solid_count"), error=info.get("error")))
        (args.out/"manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(index, len(paths), path.name, info["status"], info.get("solid_count"), info.get("error", ""), flush=True)


if __name__ == "__main__":
    main()
