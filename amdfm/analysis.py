from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib.metadata
from pathlib import Path
import platform
import time

import numpy as np

from src.core.mesh_diagnostics import inspect_mesh
from . import __version__
from .evidence import used_sources
from .models import Finding, Model, plain
from .orientation import compare_orientations, measure_orientation
from .profiles import Profile, PROCESS_LABELS, UNASSESSED


def code_digest():
    digest = hashlib.sha256()
    root = Path(__file__).resolve().parents[1]
    files = sorted((root/"amdfm").glob("*.py")) + sorted((root/"src/core").glob("*.py"))
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode())
        with path.open("rb") as f:
            while block := f.read(65536):
                digest.update(block)
    return digest.hexdigest()


def review(model: Model, profile: Profile, direction=(0,0,1), *, compare=True, extended=False):
    started = time.perf_counter()
    profile.validate()
    mesh = model.mesh
    diag = inspect_mesh(mesh)
    if not diag["geometry_available"]:
        raise ValueError("; ".join(diag["issues"]))
    reliable = diag["topology_ready"]
    assembly = (model.metadata.get("solid_count") or 1) > 1
    ambiguous_shells = model.metadata.get("source_format")=="stl" and model.metadata.get("surface_component_count",1)>1
    measured = measure_orientation(mesh, direction, profile, reliable_normals=reliable)
    findings = []
    findings.append(Finding("input", "입력 형상", "observed" if reliable else "attention",
        "폐곡면·방향·중복면 조건을 확인했습니다." if reliable else "입력 결함은 내부/외부 구분과 두께·지지 측정을 바꿀 수 있습니다.",
        "문제가 표시된 면을 CAD 또는 메시 편집기에서 확인하세요." if not reliable else "다음 설계 검토 항목을 확인하세요.",
        "edge incidence, winding, duplicate/degenerate facets", ["ISO52910", "OCCT"],
        measurements=diag, face_indices=diag["problem_face_indices"], severity="input" if not reliable else "info",
        limitations=["STL 단일 껍질의 모든 자기교차를 검사하지 않습니다."] if model.metadata["source_format"]=="stl" else []))
    if model.metadata.get("unit_status") == "assumed":
        findings.append(Finding("scale", "실제 크기 확인", "attention",
            "이 STL에는 단위·실제 치수가 없습니다. 현재 수치는 선택한 배율의 설계 시나리오입니다.",
            "부품의 알려진 길이를 입력하거나 CAD/판매자 치수와 대조하세요. 현재 크기로 사용할 경우 이를 기록하세요.",
            "explicit STL scale assumption", ["ISO52910"],
            measurements={"extents_mm":mesh.extents.tolist(), "scale_factor":model.metadata["scale_factor"]}, severity="input"))
    if assembly:
        findings.append(Finding("assembly", "여러 CAD 솔리드", "attention",
            "여러 솔리드의 체적 합은 겹침을 제거한 조립체 체적이 아닙니다.",
            "입력에서 검토할 솔리드를 선택하세요. 접촉·교차·조립 공차는 별도로 확인하세요.",
            "STEP solid enumeration", ["ISO52910", "OCCT"],
            measurements={"solid_count":model.metadata["solid_count"]}, severity="input"))
    if ambiguous_shells:
        findings.append(Finding("shells", "여러 STL 표면 성분", "attention",
            "분리된 표면이 여러 개입니다. 독립 부품·내부 공동·서로 겹치는 재료인지 빠른 검사만으로 구분하지 않습니다.",
            "단일 CAD 솔리드 STEP을 사용하거나 메시 편집기에서 성분의 교차·공동 방향을 확인하세요. 표면 방향 검토는 계속 제공합니다.",
            "connected mesh vertex components; union/intersection not evaluated", ["ISO52910"],
            measurements={"surface_component_count":model.metadata["surface_component_count"]},severity="input"))
    fit = measured["build_fit"]
    findings.append(Finding("build", "빌드 공간과 배치", "unknown" if fit is None else ("observed" if fit else "attention"),
        "장비가 미확정이므로 필요한 공간을 먼저 제시합니다." if fit is None else ("지정 공간에 형상 외곽이 들어갑니다." if fit else "현재 방향의 형상 외곽이 지정 공간을 초과합니다."),
        "장비 공간을 입력하거나 방향 비교에서 수용 가능한 배치를 선택하세요.",
        "build-frame AABB; additional XY yaw 0/90 degrees", ["ISO52910"],
        measurements={k:measured[k] for k in ("placed_extents_mm", "build_fit", "xy_yaw_deg", "max_axis_utilization")},
        limitations=["연속 회전 최적화·서포트·래프트·장비 금지 영역은 포함하지 않습니다."], severity="constraint" if fit is False else "info"))
    area = measured["overhang_projected_area_sum_mm2"]
    if profile.process == "PBF_POLYMER":
        status, reason, action = "not_applicable", "고분자 PBF의 분말 지지에 MEX의 오버행 판정은 적용하지 않습니다.", "열수축·뒤틀림·분말 제거 경로를 공정 담당자와 검토하세요."
    elif not reliable:
        status, reason, action = "unknown", "면 방향 또는 위상 결함 때문에 하향면의 의미가 불확실합니다.", "입력 형상을 수정한 뒤 다시 검토하세요."
    else:
        status = "attention" if area > 1e-8 else "not_detected"
        reason = f"수평면 기준 {profile.overhang_angle_deg:g}° 미만 하향면을 찾았습니다." if area > 1e-8 else "설정 각도 미만의 하향면 후보가 검출되지 않았습니다."
        action = "방향 변경을 비교하고, 표시된 수평 천장을 경사·아치·물방울 단면으로 바꾸거나 제거 가능한 지지를 설계하세요."
        if profile.process == "PBF_METAL":
            action = "방향과 경사면을 비교한 뒤 열전달·고정용 서포트와 제거·후가공 접근성을 검토하세요."
        elif profile.process == "VPP":
            action = "기울기·서포트 접점·박리 방향을 비교하고 내부 세척·배출구를 확보하세요."
    faces = measured["overhang_face_indices"]
    cad_ids = sorted(set(model.face_ids[faces].tolist())) if faces and model.face_ids is not None else []
    findings.append(Finding("overhang", "하향면과 지지 검토", status, reason, action,
        measured["overhang_scope"], ["ISO52910", "JIANG2018", "ISO52911P", "ISO52911M", "KIM2019"],
        measurements={"projected_area_sum_mm2":area, "surface_area_mm2":measured["overhang_surface_area_mm2"],
                      "angle_from_horizontal_deg":profile.overhang_angle_deg, "threshold_basis":profile.threshold_basis},
        face_indices=faces, cad_face_ids=cad_ids,
        limitations=["면 투영 합은 겹친 투영의 합집합 또는 실제 서포트량이 아닙니다.", "각도만으로 브리지 성공·열변형·서포트 제거성을 결정하지 않습니다."]))
    contact = measured["contact_triangle_area_mm2"]
    if profile.process == "MEX":
        findings.append(Finding("contact", "바닥 접촉", "unknown" if contact is None else ("attention" if contact <= 1e-8 else "observed"),
            "바닥의 평평한 하향 삼각형 면적을 측정했습니다. 점·선 접촉은 접착 면적으로 세지 않습니다.",
            "접촉이 작거나 없으면 평면을 아래로 놓고, 브림·접착 설정과 무게중심을 확인하세요.",
            "coplanar bottom triangle area sum", ["ISO52910"], measurements={"area_mm2":contact},
            limitations=["첫 압출 경로의 면적·실제 접착력·전도 안정성 계산은 아닙니다."]))
    cylinders = [f for f in model.cad_features if f["kind"]=="cylinder"]
    holes = [f for f in cylinders if f["role"]=="inner"]
    d = np.asarray(measured["direction"])
    transverse = [f for f in holes if abs(np.dot(f["axis"], d)) < .70710678]
    small = [f for f in holes if profile.minimum_hole_mm and f["diameter_mm"] < profile.minimum_hole_mm]
    support_holes = transverse if profile.process!="PBF_POLYMER" else []
    problem_ids = [f["face_id"] for f in support_holes + small]
    hole_action="수평 구멍 후보는 축을 적층 방향으로 돌리거나 천장 단면을 변경하세요. 끼워맞춤 홀은 후가공 여유·핀 게이지 검사를 계획하세요."
    if profile.process=="PBF_POLYMER":
        hole_action="홀의 분말 배출·청소 접근성과 수축·후가공 공차를 검토하세요. 축이 기울었다는 이유만으로 MEX의 지지 규칙을 적용하지 않습니다."
    elif profile.process=="VPP":
        hole_action="홀의 형상과 방향을 세척·수지 배출·서포트 접점 및 후경화 공차와 함께 검토하세요."
    hole_status = "unknown" if model.face_ids is None else ("attention" if problem_ids else "observed")
    findings.append(Finding("cad_holes", "CAD 원통면·구멍 후보", hole_status,
        "CAD 원통의 지름과 축을 읽어 작은 내측 원통면과 적층축에서 기울어진 구멍 후보를 표시합니다." if model.face_ids is not None else "STL만으로 설계된 구멍 지름·축을 확정하지 않습니다. STEP에서 원통면을 인식할 수 있습니다.",
        hole_action,
        "OCCT analytic cylinders; reversed cylindrical face; axis inclination >45 degrees is a review grouping", ["STAV2022", "ISO52910", "KIM2019"],
        measurements={"cylindrical_faces":cylinders, "inner_face_count":len(holes) if model.face_ids is not None else None,
            "transverse_inner_face_count":len(transverse) if model.face_ids is not None else None,
            "minimum_hole_mm":profile.minimum_hole_mm, "threshold_basis":profile.threshold_basis},
        cad_face_ids=sorted(set(problem_ids)),
        face_indices=np.flatnonzero(np.isin(model.face_ids, problem_ids)).tolist() if model.face_ids is not None else [],
        limitations=["원통면 수는 구멍 개수와 다릅니다. 부분 원통·필렛·블라인드/관통·배출 통로는 구분하지 않습니다.", "축 기울기 45° 분류는 표시 정책이며 공정 합격 기준이 아닙니다."]))
    cavities = model.metadata.get("cavity_shell_count")
    cavity_action="공동이 있으면 공정에 맞게 배출구·청소 접근 경로를 설계하고 내부 서포트의 제거 가능성을 확인하세요."
    if profile.process=="MEX":
        cavity_action="밀폐 기능을 보존하면서 내부 천장의 브리징·자립 형상·분할 제작을 비교하세요. 내부 서포트가 필요하다면 제거 경로도 설계하세요."
    findings.append(Finding("cavities", "밀폐 공동·재료 제거", "unknown" if cavities is None else ("attention" if cavities else "not_detected"),
        "CAD 솔리드의 외곽 외 추가 껍질은 내부 밀폐 경계를 나타냅니다." if cavities is not None else "STL 내부 공동과 배출 연결성은 빠른 검토에서 확정하지 않았습니다.",
        cavity_action,
        "valid CAD solid shell count minus one; no flow/connectivity simulation", ["ISO52910", "FORM4", "ASTMF3530"],
        measurements={"internal_shell_count":cavities},
        limitations=["열린 채널의 좁은 목·막힌 분말·수지 흡착 컵은 이 검사로 배제하지 못합니다."]))
    findings.append(Finding("wall", "얇은 벽·세부 특징", "unknown",
        "두께와 미세 특징은 면 각도만으로 판단할 수 없습니다. 정밀 검토에서 법선 방향 거리 표본을 계산합니다.",
        "벽 검토를 실행하고 실제 장비의 허용 두께를 입력하세요. MEX는 슬라이서의 가변 선폭 경로도 대조하세요.",
        "not run in quick review", ["ISO52910", "KUIPERS2020", "PRUSA_ARACHNE"],
        measurements={"minimum_wall_mm":profile.minimum_wall_mm, "nominal_line_width_mm":profile.line_width_mm}))
    orientations = compare_orientations(mesh, profile, reliable_normals=reliable, extended=extended) if compare else []
    attention = sum(f.status == "attention" for f in findings)
    return plain(dict(schema="amdfm-review/3.0", app_version=__version__,
        timestamp_utc=datetime.now(timezone.utc).isoformat(), model=model.metadata,
        model_fingerprint=model.fingerprint, profile=profile.to_dict(), process_label=PROCESS_LABELS[profile.process],
        summary={"review_status":"geometry_review" if reliable else "partial_geometry",
                 "attention_items":attention, "decision":"설계 검토 결과; 출력 성공·강도·표준 적합 판정 아님"},
        geometry={"extents_mm":mesh.extents.tolist(), "mesh_triangle_area_mm2":float(mesh.area),
            "mesh_signed_volume_mm3":float(mesh.volume) if reliable and not assembly and not ambiguous_shells else None,
            "exact_cad_volume_mm3":model.metadata.get("exact_volume_mm3"), "face_count":len(mesh.faces)},
        current_orientation=measured, orientations=orientations, findings=[asdict(f) for f in findings],
        unassessed=UNASSESSED[profile.process], sources=used_sources(findings),
        provenance={"code_sha256":code_digest(), "python":platform.python_version(), "platform":platform.platform(),
            "dependencies":{n:importlib.metadata.version(n) for n in ("numpy","trimesh","shapely","streamlit","cadquery-ocp-novtk")}},
        elapsed_seconds=time.perf_counter()-started))
