"""Bounded 3MF mesh geometry import: Core + Production component references.

No slicer configuration is executed. Required unsupported extensions fail closed.
Sources: 3MF Core 1.4 §§2.1, 3.3–3.4, 4.2; Production §§2–3.3.
"""
from __future__ import annotations

import io
from pathlib import PurePosixPath
from urllib.parse import unquote
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import trimesh

CORE="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PROD="http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
RELS="http://schemas.openxmlformats.org/package/2006/relationships"
MODEL_REL="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"
UNITS={"micron":.001,"millimeter":1.,"centimeter":10.,"inch":25.4,"foot":304.8,"meter":1000.}


def affine(value):
    matrix=np.eye(4)
    if value:
        try: values=np.asarray([float(v) for v in value.split()])
        except ValueError as exc: raise ValueError("3MF 배치 행렬을 읽지 못했습니다.") from exc
        if values.shape!=(12,) or not np.isfinite(values).all():
            raise ValueError("3MF 배치에는 유한한 12개 값이 필요합니다.")
        matrix[:3,:]=values.reshape(4,3).T
        determinant=np.linalg.det(matrix[:3,:3])
        if not np.isfinite(determinant) or determinant==0:
            raise ValueError("3MF의 특이 배치 행렬은 지원하지 않습니다.")
    return matrix


def member_path(value, relative_to=""):
    value=unquote(value)
    if "\\" in value or ":" in value or "?" in value or "#" in value:
        raise ValueError("3MF 내부 경로만 읽을 수 있습니다.")
    path=PurePosixPath(value.lstrip("/")) if value.startswith("/") else PurePosixPath(relative_to).parent/value
    if ".." in path.parts:
        raise ValueError("3MF 상위 경로 참조는 지원하지 않습니다.")
    return str(path)


def read_3mf(data, *, max_faces=600_000):
    try: archive=zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc: raise ValueError("유효한 3MF ZIP 패키지가 아닙니다.") from exc
    with archive:
        listing=archive.infolist()
        if len(listing)>10_000 or sum(i.file_size for i in listing)>256*1024*1024:
            raise ValueError("3MF 압축 해제 데이터가 256 MiB/10,000항목 한도를 넘습니다.")
        names=[i.filename for i in listing]
        if len(set(names))!=len(names):
            raise ValueError("3MF 안에 중복 경로가 있습니다.")
        def xml(path):
            try: raw=archive.read(path)
            except (KeyError,RuntimeError,zipfile.BadZipFile) as exc:
                raise ValueError(f"3MF 참조 파일을 읽지 못했습니다: {path}") from exc
            if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
                raise ValueError("3MF DTD/엔터티 선언은 지원하지 않습니다.")
            try:
                namespaces={}
                for event,item in ET.iterparse(io.BytesIO(raw),events=("start-ns","start")):
                    if event=="start":break
                    namespaces[item[0]]=item[1]
                return ET.fromstring(raw),namespaces
            except ET.ParseError as exc: raise ValueError("3MF XML 구문 오류입니다.") from exc
        rels,_=xml("_rels/.rels")
        starts=[r for r in rels if r.get("Type")==MODEL_REL]
        if len(starts)!=1 or starts[0].get("TargetMode", "Internal")!="Internal":
            raise ValueError("3MF의 단일 내부 시작 모델을 확인하지 못했습니다.")
        root_path=member_path(starts[0].get("Target",""))
        root,root_ns=xml(root_path)
        unit=root.get("unit","millimeter")
        if unit not in UNITS:raise ValueError("지원하지 않는 3MF 길이 단위입니다.")
        cache={}
        def model(path):
            if path in cache:return cache[path]
            doc,ns=(root,root_ns) if path==root_path else xml(path)
            if doc.tag!=f"{{{CORE}}}model":raise ValueError("3MF Core 모델이 아닙니다.")
            if doc.get("unit","millimeter")!=unit:
                raise ValueError("서로 다른 단위의 3MF 모델 참조는 지원하지 않습니다.")
            unknown=[p for p in doc.get("requiredextensions","").split() if ns.get(p)!=PROD]
            if unknown:raise ValueError("지원하지 않는 3MF 필수 확장: "+", ".join(unknown))
            objects=doc.findall(f"{{{CORE}}}resources/{{{CORE}}}object")
            ids=[o.get("id") for o in objects]
            if len(objects)>1000 or len(set(ids))!=len(ids) or None in ids:
                raise ValueError("3MF 객체 번호가 중복·누락되었거나 1,000개를 초과했습니다.")
            cache[path]=(doc,dict(zip(ids,objects)))
            return cache[path]
        vertices,faces,instances=[],[],[]
        total_vertices=total_faces=0
        def expand(path,oid,transform,stack):
            nonlocal total_vertices,total_faces
            token=(path,oid)
            if token in stack or len(stack)>32:
                raise ValueError("3MF 컴포넌트가 순환하거나 중첩 한도를 넘습니다.")
            doc,objects=model(path)
            if oid not in objects:raise ValueError(f"3MF 참조 객체가 없습니다: {oid}")
            obj=objects[oid]
            if obj.get("type","model")!="model":
                raise ValueError("3MF의 지원/곡면/기타 객체는 부품 솔리드로 검토하지 않습니다.")
            mesh=obj.find(f"{{{CORE}}}mesh")
            components=obj.find(f"{{{CORE}}}components")
            if (mesh is None)==(components is None):raise ValueError("3MF 객체의 메시/컴포넌트 정의가 모호합니다.")
            if components is not None:
                for c in components:
                    if c.tag!=f"{{{CORE}}}component":raise ValueError("지원하지 않는 3MF 컴포넌트 정의입니다.")
                    cross=c.get(f"{{{PROD}}}path")
                    if cross and path!=root_path:raise ValueError("3MF 하위 파일의 외부 객체 참조는 허용되지 않습니다.")
                    target=member_path(cross) if cross else path
                    expand(target,c.get("objectid"),transform@affine(c.get("transform")),stack+(token,))
                return
            vs=mesh.findall(f"{{{CORE}}}vertices/{{{CORE}}}vertex")
            ts=mesh.findall(f"{{{CORE}}}triangles/{{{CORE}}}triangle")
            if len(vs)<3 or not ts or len(instances)>=100 or total_faces+len(ts)>max_faces:
                raise ValueError("3MF 메시가 비었거나 배치 객체 100개/삼각형 한도를 초과했습니다.")
            try:
                xyz=np.array([[float(v.attrib[k]) for k in "xyz"] for v in vs])
                tri=np.array([[int(t.attrib[k]) for k in ("v1","v2","v3")] for t in ts],dtype=np.int64)
            except (ValueError,KeyError,OverflowError) as exc:raise ValueError("3MF 정점 또는 삼각형 값이 잘못되었습니다.") from exc
            if not np.isfinite(xyz).all() or tri.min()<0 or tri.max()>=len(xyz):
                raise ValueError("3MF 정점 좌표/삼각형 번호가 유효하지 않습니다.")
            xyz=(xyz@transform[:3,:3].T+transform[:3,3])*UNITS[unit]
            if not np.isfinite(xyz).all():raise ValueError("3MF 배치 적용 후 좌표가 유한하지 않습니다.")
            if np.linalg.det(transform[:3,:3])<0:tri=tri[:,[0,2,1]]
            vertices.append(xyz);faces.append(tri+total_vertices)
            instances.append(dict(part=path,object_id=oid,name=obj.get("name",oid),transform=transform.tolist(),
                                  vertex_count=len(vs),triangle_count=len(ts)))
            total_vertices+=len(vs);total_faces+=len(ts)
        model(root_path)
        build=root.find(f"{{{CORE}}}build")
        if build is None:raise ValueError("3MF 빌드 목록이 없습니다.")
        skipped=0
        for item in build:
            if item.tag!=f"{{{CORE}}}item":raise ValueError("지원하지 않는 3MF 빌드 항목입니다.")
            if item.get("printable","1") in ("0","false"):
                skipped+=1;continue
            path=member_path(item.get(f"{{{PROD}}}path")) if item.get(f"{{{PROD}}}path") else root_path
            expand(path,item.get("objectid"),affine(item.get("transform")),())
        if not vertices:raise ValueError("3MF 빌드에 검토 가능한 형상이 없습니다.")
        mesh=trimesh.Trimesh(vertices=np.vstack(vertices),faces=np.vstack(faces),process=False)
        return mesh,dict(declared_3mf_unit=unit,unit_status="declared_in_3mf",dimensions_confirmed=True,
            scale_factor=UNITS[unit],root_model_part=root_path,mesh_instances=instances,
            skipped_nonprintable_items=skipped,source_format="3mf",solid_count=None,
            exact_volume_mm3=None,exact_area_mm2=None,
            unit_note="3MF 단위와 객체 배치를 mm로 해석. 슬라이서 설정·재료·서포트 지령은 적용하지 않음.",
            import_scope="Core triangle meshes and Production paths/transforms; no material/texture/slicer or alternate geometry interpretation")
