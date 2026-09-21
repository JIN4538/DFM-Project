"""Geometric machining checks for a specified tool and a fixed approach axis.

Measurements of cylindrical faces are not a certified hole count/depth. Point
visibility is not a swept-volume tool, holder or fixture collision simulation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math

import numpy as np

from amdfm.models import Finding, plain
from amdfm.orientation import unit_direction


SOURCES = {
    "CNC_GEOMETRY": {
        "title": "Protolabs — Design for Machining Toolkit",
        "url": "https://www.protolabs.com/en-gb/resources/design-for-machining-toolkit/",
        "scope": "Internal corners, deep features and access motivate checks. Service-specific limits are not universal limits.",
    },
    "CNC_CORNER": {
        "title": "Protolabs Network — Sharp corners in CNC machining",
        "url": "https://www.hubs.com/knowledge-base/sharp-corners-in-cnc-machining/",
        "scope": "Geometric cutter radius constraint; not a prediction of stability, surface quality or time.",
    },
    "CNC_TOOL_DIMENSIONS": {
        "title": "Harvey Performance — The Anatomy of an End Mill",
        "url": "https://www.harveyperformance.com/in-the-loupe/end-mill-anatomy/",
        "scope": "Cutting length, overall length and length below shank are distinct. The entered tip-to-holder reach is an explicit user condition, not an inferred catalog value.",
    },
    "CNC_FACE_RECOGNITION": {
        "title": "Yeo et al. — Machining feature recognition based on deep neural networks to support tight integration with 3D CAD systems (2021)",
        "url": "https://www.nature.com/articles/s41598-021-01313-3",
        "scope": "원통 특징이 여러 B-rep 면으로 표현될 수 있다는 배경 근거입니다. 현재 코드는 면 구간을 측정하며 이 논문의 DNN·17종 특징 분류기를 구현하지 않습니다. 논문의 인식률은 가공 성공률이 아닙니다.",
        "locator": "제공 PDF 5–9쪽의 면 표현; 13–17쪽의 분류 평가",
        "access": "2026-09-21 제공 전문 20쪽 검토; 핵심 혼동행렬·표 원페이지 대조",
        "local_path": "references/machining/Machining Feature Recognition Based on Deep Neural Networks to Support Tight Integration with 3D CAD Systems.pdf",
    },
    "CNC_ACCESS_SCOPE": {
        "title": "Autodesk Fusion — Shaft and Holder",
        "url": "https://help.autodesk.com/cloudhelp/ENU/Fusion-CAM/files/GUIDD505C759-C325-4C99-BBDD-35FE39B3761F.htm",
        "scope": "Actual shaft/holder collision checks involve toolpath and clearance conditions. This source does not validate the implementation's sampled point-ray algorithm.",
    },
    "CNC_SPATIAL_PLANNING": {
        "title": "Nelaturi et al. (2015) — Automatic Spatial Planning for Machining Operations",
        "url": None,
        "scope": "점의 직선 가시성과 두께가 있는 공구의 접근은 다릅니다. 현재 표본 ray 검사는 초기 차폐 관측이며, 논문의 유한 공구 제거 체적·공정 순서·고정구 계획을 구현하지 않습니다.",
        "locator": "제공 PDF 2–3쪽, Fig. 1–2: 무한히 가는 공구와 유한 공구의 차이",
        "access": "2026-09-21 제공 전문 6쪽 검토·핵심 도해 대조",
        "local_path": "references/machining/Automatic Spatial Planning for Machining Operations.pdf",
    },
    "CNC_MRSEV": {
        "title": "Gupta et al. — Building MRSEV Models for CAM Applications",
        "url": None,
        "scope": "가공 특징은 면 하나와 같지 않으며 소재·제거 체적·접근 체적이 필요합니다. 현재 제한 포켓과 원통면 검출은 이 보고서의 일반 특징 인식·공정 계획 구현이 아닙니다.",
        "locator": "제공 보고서 PDF 11–21쪽; 30–31쪽 구현 한계",
        "access": "2026-09-21 제공 스캔 36쪽 OCR 검토·정의/알고리즘/도해 원페이지 대조",
        "local_path": "references/machining/Building MRSEV Models for CAM Applications.pdf",
    },
    "CNC_CUTTING_PHYSICS": {
        "title": "Budak (2006) — Analytical Models for High Performance Milling. Part I",
        "url": "https://doi.org/10.1016/j.ijmachtools.2005.09.009",
        "scope": "절삭력·변형·공차 예측에는 절삭 계수, 이송·절입, 공구/홀더/공작물 강성이 필요합니다. 현재 치수 비교에는 이 물리 모델이 포함되어 있지 않습니다.",
        "locator": "제공 PDF 2–4쪽 힘·보정, 5–8쪽 강성·변형",
        "access": "2026-09-21 제공 전문 11쪽 검토·수식/단위 대조",
        "local_path": "references/machining/Analytical Models for High Performance Milling. Part I - Cutting Forces, Structural Deformations and Tolerance Integrity.pdf",
    },
    "CNC_GPS_REQUIREMENTS": {
        "title": "KS A ISO 8015:2011 — GPS 기본사항·개념·원칙·규칙",
        "url": None,
        "scope": "도면의 명세와 실제 검증을 구분하는 근거입니다. 공차·PMI·데이텀·실측 없이 CAD 명목 치수로 공차 적합이나 가공 성공률을 계산하지 않습니다. 표준의 100% 가정은 실물 성공률이 아닙니다.",
        "locator": "제공 PDF §4.4, §§5.3, 5.5, 5.10, 5.13; 국내 2023 개정판",
        "access": "2026-09-21 제공 전페이지 캡처 21쪽 검토; 워터마크/OCR 한계 있음",
        "local_path": "references/machining/KS A ISO 8015 전문 캡쳐본.pdf",
    },
}


# Numeric comparison policy only: these bands are neither CAD design tolerance,
# tool runout nor a permitted manufacturing clearance. Preserve boundary cases so
# rounding after STEP transfer/rotation cannot masquerade as a proven conflict.
LENGTH_ABSOLUTE_COMPARISON_MM = 1e-9
COMPARISON_RELATIVE_TOLERANCE = 1e-10
AXIS_SINE_TOLERANCE = 1e-8


def _axis_angle_and_alignment(axis, direction):
    axis = unit_direction(axis)
    sine = float(np.linalg.norm(np.cross(axis, direction)))
    cosine = abs(float(np.dot(axis, direction)))
    # acos(dot) loses resolution close to parallel; 1 - dot <= 1e-8 would
    # silently accept an actual angle of about .0081 degrees.
    return math.degrees(math.atan2(sine, cosine)), sine <= AXIS_SINE_TOLERANCE


def _outward_along(normal, direction):
    normal = np.asarray(normal)
    return (np.dot(normal, direction) > 0
            and np.linalg.norm(np.cross(normal, direction)) <= AXIS_SINE_TOLERANCE)


def _length_comparison(measured, limit):
    if limit is None:
        return None, False
    tolerance = max(LENGTH_ABSOLUTE_COMPARISON_MM,
                    max(abs(measured), abs(limit)) * COMPARISON_RELATIVE_TOLERANCE)
    delta = measured - limit
    return bool(delta > tolerance), bool(abs(delta) <= tolerance)


def _record_comparison(row, key, measured, limit):
    exceeded, boundary = _length_comparison(measured, limit)
    row[key] = exceeded
    if boundary:
        row.setdefault("numerical_boundary_comparisons", []).append(key)


_MECHANISMS = {
    "cnc_input": ("STEP transfer metadata: validity, solid count and availability of B-rep face records", []),
    "cnc_coverage": ("Inventory of unsupported surfaces, unresolved cylinder material sides and incomplete planar boundary extraction", []),
    "cnc_holes": ("Analytic cylindrical face diameter and UV axial bounds; fixed-axis and user tool-condition comparisons", ["CNC_GEOMETRY", "CNC_FACE_RECOGNITION", "CNC_TOOL_DIMENSIONS", "CNC_MRSEV"]),
    "cnc_curved_corners": ("Concave analytic cylindrical face radius versus radius of the user-specified cylindrical end mill", ["CNC_CORNER"]),
    "cnc_rectangular_pockets": ("Restricted B-rep adjacency recognition of four-sided floors; local width and wall-height comparisons", ["CNC_GEOMETRY", "CNC_CORNER", "CNC_TOOL_DIMENSIONS", "CNC_MRSEV"]),
    "cnc_visibility": ("point_visibility; deterministic sampled mesh points and straight rays; finite cutter and holder not modeled", ["CNC_ACCESS_SCOPE", "CNC_SPATIAL_PLANNING"]),
}


@dataclass(frozen=True)
class MachiningProfile:
    machine: str = "미확정"
    material: str = "미확정"
    tool_diameter_mm: float | None = None
    flute_length_mm: float | None = None
    reach_mm: float | None = None
    hole_depth_ratio_limit: float | None = None
    basis: str = "사용자 지정 공구·탐색 조건; 실제 가공 검증 전"

    def validate(self):
        for name in ("tool_diameter_mm", "flute_length_mm", "reach_mm", "hole_depth_ratio_limit"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not math.isfinite(value) or value <= 0):
                raise ValueError("공구 치수와 검토 기준에는 유한한 양수를 입력하세요.")
        if self.flute_length_mm is not None and self.reach_mm is not None and self.flute_length_mm > self.reach_mm:
            raise ValueError("날 길이는 공구 도달 길이보다 클 수 없습니다.")

    def to_dict(self):
        return asdict(self)


def _faces(model, cad_ids):
    if model.face_ids is None:
        return []
    return np.flatnonzero(np.isin(model.face_ids, cad_ids)).tolist()


def _finding(model, key, title, status, reason, action, measurements=None, cad_ids=(), limitations=()):
    method, evidence = _MECHANISMS[key]
    return plain(Finding(key, title, status, reason, action,
        method, evidence,
        measurements=measurements or {}, cad_face_ids=list(cad_ids), face_indices=_faces(model, cad_ids),
        limitations=list(limitations), severity="review" if status == "attention" else "info"))


def rectangular_pocket_floors(features, direction):
    """Recognize only unsplit rectangular floors bounded by four inward walls.

    Interior islands, curved trims and disconnected/split wires are preserved
    as unsupported. No pocket count is inferred from unrelated planar faces.
    """
    direction = unit_direction(direction)
    by_id = {f["face_id"]: f for f in features}
    result = []
    for face in features:
        if face.get("kind") != "plane" or not _outward_along(face.get("normal", [0, 0, 0]), direction):
            continue
        if face.get("boundary_status") != "complete":
            continue
        wires = face.get("boundary_wires", [])
        if len(wires) != 1 or not wires[0].get("outer") or not wires[0].get("closed"):
            continue
        edges = wires[0].get("edges", [])
        if len(edges) != 4 or any(e.get("kind") != "line" for e in edges):
            continue
        starts = np.array([e["start_mm"] for e in edges])
        ends = np.array([e["end_mm"] for e in edges])
        vectors = ends - starts
        lengths = np.linalg.norm(vectors, axis=1)
        if np.any(lengths <= 0):
            continue
        tol = max(1e-7, float(max(lengths)) * 1e-8)
        unit = vectors / lengths[:, None]
        # Order-independent rectangle test: two parallel edge pairs, normal to
        # one another. Source wires supply closure/topology, not mesh bounds.
        dots = np.abs(unit @ unit.T)
        if any(np.sum(dots[i] > 1 - 1e-8) != 2 for i in range(4)):
            continue
        if np.any((dots > 1e-8) & (dots < 1 - 1e-8)):
            continue
        center = (starts.sum(axis=0) + ends.sum(axis=0)) / 8
        walls, depths = [], []
        for edge in edges:
            neighbors = [a for a in edge.get("adjacent_faces", []) if a["face_id"] != face["face_id"]]
            if len(neighbors) != 1:
                break
            wall = neighbors[0]
            normal = np.asarray(wall.get("normal", [0, 0, 0]))
            if wall.get("kind") != "plane" or abs(np.dot(normal, direction)) > 1e-8:
                break
            if np.dot(normal, center - np.asarray(edge["midpoint_mm"])) <= tol:
                break  # Convex boss/exterior wall, not a concave pocket floor.
            whole_wall = by_id.get(wall["face_id"], {})
            if whole_wall.get("boundary_status") != "complete" or len(whole_wall.get("boundary_wires", [])) != 1:
                break
            points = [p for w in whole_wall.get("boundary_wires", []) for e in w.get("edges", [])
                      for p in (e.get("start_mm"), e.get("end_mm")) if p is not None]
            if not points:
                break
            heights = (np.asarray(points) - center) @ direction
            if min(heights) < -tol or max(heights) <= tol:
                break
            depth = float(max(heights))
            top_edges = [e for w in whole_wall["boundary_wires"] for e in w["edges"]
                         if all(abs(np.dot(np.asarray(e[k]) - center, direction) - depth) <= tol
                                for k in ("start_mm", "end_mm"))]
            if not top_edges or any(not any(
                a["face_id"] != wall["face_id"] and a.get("kind") == "plane"
                and _outward_along(a.get("normal", [0, 0, 0]), direction)
                for a in e.get("adjacent_faces", [])) for e in top_edges):
                break  # A sealed cavity/overhung lip has no outward-facing rim.
            depths.append(depth)
            walls.append(wall["face_id"])
        if len(walls) != 4 or max(depths) - min(depths) > tol:
            continue
        result.append(dict(floor_face_id=face["face_id"], wall_face_ids=walls,
            center_mm=center.tolist(), width_mm=float(min(lengths)), length_mm=float(max(lengths)),
            wall_height_mm=float(max(depths)), internal_corner_radius_mm=0.,
            scope="Four straight floor edges, inward walls of equal height and outward planar rim; tool path not certified."))
    return result


def unresolved_inward_floors(features, direction, recognized):
    """Locate possible interior floors excluded by the strict recognizer.

    A face with any inward vertical neighboring wall is only a review location:
    it may be a channel, cavity, island/rounded pocket or a numerically unresolved
    floor. Do not invent dimensions or certify it as an open machining pocket.
    """
    direction = unit_direction(direction)
    recognized_ids = {row["floor_face_id"] for row in recognized}
    by_id = {face["face_id"]: face for face in features}
    candidates = []
    for face in features:
        if face.get("kind") != "plane" or face["face_id"] in recognized_ids:
            continue
        if not _outward_along(face.get("normal", [0, 0, 0]), direction):
            continue
        wires = face.get("boundary_wires") or []
        edges = [edge for wire in wires for edge in wire.get("edges", [])]
        points = [edge["start_mm"] for edge in edges if edge.get("start_mm") is not None]
        if not points:
            continue
        points = np.asarray(points)
        # Reference-point arithmetic avoids summing large translated positions.
        center = points[0] + (points - points[0]).mean(axis=0)
        for edge in edges:
            if edge.get("midpoint_mm") is None:
                continue
            relative = center - np.asarray(edge["midpoint_mm"])
            inward_wall_above = False
            for adjacent in edge.get("adjacent_faces", []):
                wall = by_id.get(adjacent["face_id"], {})
                wall_center = wall.get("centroid_mm") or wall.get("center_mm")
                if (adjacent.get("kind") == "plane" and wall_center is not None
                    and abs(np.dot(adjacent.get("normal", [0, 0, 0]), direction)) <= 1e-8
                    and np.dot(adjacent.get("normal", [0, 0, 0]), relative) > 1e-7
                    and np.dot(np.asarray(wall_center) - center, direction) > 1e-7):
                    inward_wall_above = True
                    break
            if inward_wall_above:
                candidates.append(face["face_id"])
                break
    return candidates


def review_machining(model, profile: MachiningProfile, direction=(0, 0, 1), *, visibility=False):
    profile.validate()
    direction = unit_direction(direction)
    findings = []
    cad_ready = (model.metadata.get("source_format") in ("step", "stp")
                 and model.metadata.get("cad_geometry_kind") == "solid"
                 and model.metadata.get("solid_count") == 1 and model.metadata.get("cad_valid") is True
                 and bool(model.cad_features))
    findings.append(_finding(model, "cnc_input", "절삭 검토 입력", "observed" if cad_ready else "unknown",
        "단일 STEP 솔리드의 해석 곡면을 읽었습니다." if cad_ready else "현재 입력에서는 CAD 특징 치수를 확정하지 않습니다.",
        "공구 조건을 입력하고 위치별 결과를 확인하세요." if cad_ready else "단위가 선언된 단일 솔리드 STEP을 선택하세요.",
        {"cad_feature_dimensions_available": cad_ready}, limitations=["공차·표면 거칠기·PMI·소재·고정 방법은 자동 추출하지 않습니다."]))
    features = model.cad_features if cad_ready else []
    incomplete_boundaries = [f["face_id"] for f in features if f.get("kind") == "plane"
                             and f.get("boundary_status") != "complete"]
    unresolved_cylinders = [f["face_id"] for f in features if f.get("kind") == "cylinder"
                            and f.get("role") not in ("inner", "outer")]
    unsupported_faces = [f["face_id"] for f in features if f.get("kind") not in ("plane", "cylinder", "zero_area_trim")]
    coverage_missing = bool(incomplete_boundaries or unresolved_cylinders or unsupported_faces)
    findings.append(_finding(model, "cnc_coverage", "CAD 면 정보와 특징 인식 범위", "unknown" if not cad_ready or coverage_missing else "observed",
        "CAD 특징 인식에 필요한 입력을 확인할 수 없습니다." if not cad_ready else
        f"경계 미확정 평면 {len(incomplete_boundaries)}개, 내·외부 미확정 원통면 {len(unresolved_cylinders)}개, 미지원 곡면 {len(unsupported_faces)}개입니다.",
        "미확정 면은 CAD/CAM에서 별도로 확인하세요. 검출되지 않은 특징을 없는 것으로 판단하지 않습니다." if coverage_missing or not cad_ready else
        "아래 검토는 명시된 평면·원통면·직사각 바닥 범위입니다. 복잡한 특징은 별도 확인하세요.",
        {"incomplete_boundary_face_ids": incomplete_boundaries, "unresolved_cylinder_face_ids": unresolved_cylinders,
         "unsupported_face_ids": unsupported_faces, "cad_features_available": cad_ready},
        incomplete_boundaries + unresolved_cylinders + unsupported_faces,
        ["경계 추출 완료와 전체 포켓·구멍 인식 완료는 다릅니다. 분할·교차·섬·곡선 경계 특징은 전수 인식하지 않습니다.",
         "4변 외 평면 바닥(예: 챔퍼 때문에 8변이 된 포켓)은 폭·깊이 비교에서 제외됩니다."]))
    holes = [f for f in features if f.get("kind") == "cylinder" and f.get("role") == "inner" and f.get("full_circumference")]
    rows = []
    for feature in holes:
        diameter, extent = float(feature["diameter_mm"]), float(feature["axial_extent_mm"])
        axis_angle, aligned = _axis_angle_and_alignment(feature["axis"], direction)
        row = dict(face_id=feature["face_id"], diameter_mm=diameter, cylindrical_length_mm=extent,
            length_diameter_ratio=extent / diameter, axis_aligned=aligned, axis_angle_deg=axis_angle,
            tool_too_large=None, segment_exceeds_reach=None,
            exceeds_ratio=(extent / diameter > profile.hole_depth_ratio_limit * (1 + COMPARISON_RELATIVE_TOLERANCE)) if profile.hole_depth_ratio_limit else None)
        if aligned:
            if profile.tool_diameter_mm is not None:
                _record_comparison(row, "tool_too_large", profile.tool_diameter_mm, diameter)
            _record_comparison(row, "segment_exceeds_reach", extent, profile.reach_mm)
        if profile.hole_depth_ratio_limit is not None and abs(extent / diameter - profile.hole_depth_ratio_limit) <= profile.hole_depth_ratio_limit * COMPARISON_RELATIVE_TOLERANCE:
            row.setdefault("numerical_boundary_comparisons", []).append("exceeds_ratio")
        rows.append(row)
    offending = [r for r in rows if not r["axis_aligned"] or r["tool_too_large"] or r["segment_exceeds_reach"] or r["exceeds_ratio"]]
    missing = profile.tool_diameter_mm is None or profile.reach_mm is None
    hole_status = "unknown" if not cad_ready else "attention" if offending else "unknown" if unresolved_cylinders or (rows and missing) else "observed" if rows else "not_detected"
    hole_actions = []
    if not cad_ready:
        hole_actions.append("단위가 선언된 단일 솔리드 STEP을 선택하세요.")
    if any(not row["axis_aligned"] for row in rows):
        hole_actions.append("축이 다른 면은 접근 방향이나 재고정 방향을 검토하세요. 해당 면의 공구 치수 비교는 보류했습니다.")
    if any(row["tool_too_large"] for row in rows):
        hole_actions.append("공구 지름보다 작은 내부 원통면에는 더 작은 공구나 형상 변경을 검토하세요.")
    if any(row["segment_exceeds_reach"] for row in rows):
        hole_actions.append("원통 구간보다 짧게 입력된 공구 돌출 길이는 실제 진입 깊이·가공 순서와 함께 확인하세요.")
    if any(row["exceeds_ratio"] for row in rows):
        hole_actions.append("입력한 길이/지름 기준을 넘는 위치는 해당 공구·가공 조건의 근거와 대조하세요.")
    if unresolved_cylinders:
        hole_actions.append("내·외부가 미확정인 원통면은 CAD에서 재확인하세요.")
    if rows and missing:
        hole_actions.append("비교에 필요한 공구 지름·돌출 길이를 입력하세요.")
    if not hole_actions:
        hole_actions.append("현재 측정·입력 범위에서 추가 공구 변경 조건은 관측되지 않았습니다. 홀 입구와 막힘, 드릴 끝 형상, 실제 경로는 별도로 확인하세요." if rows else
                            "원통면이 나뉘거나 교차한 형상은 전체 구멍으로 합치지 않습니다. CAD에서 구멍과 접근 경로를 확인하세요.")
    findings.append(_finding(model, "cnc_holes", "원통형 내부 특징과 공구", hole_status,
        ("단일 STEP 솔리드가 없어 원통형 특징 검토를 보류합니다." if not cad_ready else
         f"내부 원통면 {len(rows)}개 중 {len(offending)}개에 방향·공구 조건 확인이 필요합니다." if offending else
         f"내·외부를 확정하지 못한 원통면 {len(unresolved_cylinders)}개가 있어 내부 특징 검토가 미완료입니다." if unresolved_cylinders else
         f"원주 방향 범위가 360°인 내부 원통면 {len(rows)}개의 지름과 축 구간을 측정했습니다." if rows else "인식 범위에서 원주 방향 범위가 360°인 내부 원통면을 찾지 못했습니다."),
        " ".join(hole_actions),
        {"cylindrical_faces": rows, "face_count": len(rows) if cad_ready else None,
         "unresolved_cylinder_face_ids": unresolved_cylinders}, [r["face_id"] for r in offending],
        ["원통면 구간은 홀 전체 깊이나 홀 개수가 아닙니다. 분할·교차 홀을 병합하지 않습니다.",
         "축 정렬은 양쪽에서의 기하 방향 일치만 뜻합니다. 입구·막힘·홀더 충돌을 확인한 결과가 아닙니다.",
         "선택 축과 평행하지 않은 원통면은 지름·돌출 길이 비교를 보류합니다. 다른 공구·경로까지 가공 불가로 판정한 결과가 아닙니다.",
         "원주 방향 범위 360°는 모든 높이에 원통 벽이 있다는 뜻이 아닙니다. 교차·트림 구간이 포함될 수 있습니다.",
         "수치 경계의 비교는 초과로 확정하지 않습니다. 같은 치수는 실제 가공 여유가 확보되었다는 뜻이 아닙니다."]))
    curved = [f for f in features if f.get("kind") == "cylinder" and f.get("role") == "inner"
              and not f.get("full_circumference") and _axis_angle_and_alignment(f["axis"], direction)[1]]
    corner_rows = []
    for feature in curved:
        row = dict(face_id=feature["face_id"], radius_mm=feature["diameter_mm"] / 2, tool_too_large=None)
        if profile.tool_diameter_mm is not None:
            _record_comparison(row, "tool_too_large", profile.tool_diameter_mm, feature["diameter_mm"])
        corner_rows.append(row)
    corner_bad = [r for r in corner_rows if r["tool_too_large"]]
    corner_boundary = any(row.get("numerical_boundary_comparisons") for row in corner_rows)
    corner_action = (
        "단위가 선언된 단일 솔리드 STEP을 선택하세요." if not cad_ready else
        "공구 반경보다 작은 강조 면은 더 작은 공구 또는 설계 반경 확대를 검토하세요." if corner_bad else
        "내·외부가 미확정인 원통면을 CAD에서 확인한 뒤 반경을 비교하세요." if unresolved_cylinders else
        "선택한 축과 나란한 오목 원통면은 확인되지 않았습니다. 다른 축이나 분할·복잡한 면은 CAD/CAM에서 확인하세요." if not curved else
        "사용할 원통형 엔드밀의 지름을 입력하면 측정 반경과 비교합니다." if profile.tool_diameter_mm is None else
        "공구와 형상 반경이 수치 경계에 있습니다. 실제 가공 여유·공구 물림과 경로를 CAM에서 확인하세요." if corner_boundary else
        "현재 반경 비교에서 공구를 더 줄여야 할 조건은 관측되지 않았습니다. 다음으로 진입 경로·홀더 충돌·가공 여유를 확인하세요.")
    findings.append(_finding(model, "cnc_curved_corners", "공구축과 나란한 오목 원통면", "unknown" if not cad_ready
        else "attention" if corner_bad else "unknown" if unresolved_cylinders or (curved and profile.tool_diameter_mm is None)
        else "observed" if curved else "not_detected",
        "단일 STEP 솔리드가 없어 오목 원통면 반경 검토를 보류합니다." if not cad_ready else
        (f"내·외부가 미확정인 원통면 {len(unresolved_cylinders)}개는 오목면 유무도 판단을 보류합니다. " +
         ("공구 지름이 없어 반경 비교도 보류합니다." if profile.tool_diameter_mm is None else
          f"확정한 오목면 중 공구보다 작은 반경은 {len(corner_bad)}개입니다.")) if unresolved_cylinders else
        f"오목한 부분 원통면 {len(curved)}개의 반경을 확인했습니다. 선택한 공구보다 작은 반경은 {len(corner_bad)}개입니다." if profile.tool_diameter_mm else
        f"오목한 부분 원통면 {len(curved)}개를 찾았습니다. 공구 지름을 입력하면 반경과 비교합니다.",
        corner_action,
        {"cylindrical_faces": corner_rows, "unresolved_cylinder_face_ids": unresolved_cylinders}, [r["face_id"] for r in corner_bad],
        ["부분 원통면을 포켓 코너로 확정하지 않습니다. 선택 축에서 원통형 엔드밀 옆날이 접근하는 조건의 기하 비교입니다.",
         "공구 반경과 형상 반경이 같은 수치 경계는 여유·안정성·표면 품질을 보장하지 않습니다."]))
    pockets = rectangular_pocket_floors(features, direction)
    unresolved_floor_ids = unresolved_inward_floors(features, direction, pockets)
    pocket_rows = []
    for pocket in pockets:
        p = dict(pocket)
        p["width_too_small"] = None
        if profile.tool_diameter_mm is not None:
            _record_comparison(p, "width_too_small", profile.tool_diameter_mm, p["width_mm"])
        _record_comparison(p, "exceeds_flute_length", p["wall_height_mm"], profile.flute_length_mm)
        _record_comparison(p, "exceeds_reach", p["wall_height_mm"], profile.reach_mm)
        pocket_rows.append(p)
    pocket_ids = [p["floor_face_id"] for p in pockets]
    findings.append(_finding(model, "cnc_rectangular_pockets", "직사각 포켓 바닥과 내부 직각", "unknown" if not cad_ready else "attention" if pockets else "unknown" if incomplete_boundaries or unresolved_floor_ids else "not_detected",
        "단일 STEP 솔리드가 없어 포켓 검토를 보류합니다." if not cad_ready else
        (f"같은 높이의 네 수직 벽으로 둘러싸인 직사각 바닥 {len(pockets)}개를 찾았습니다. 내부 직각은 유한 반경의 원통형 엔드밀로 그대로 만들 수 없습니다."
         + (f" 별도로 내부 바닥 후보 {len(unresolved_floor_ids)}개는 치수 인식을 보류했습니다." if unresolved_floor_ids else "")) if pockets else
        "일부 평면 경계가 미확정이므로 직사각 포켓 검토를 완료하지 못했습니다." if incomplete_boundaries else
        f"내부 바닥 후보 {len(unresolved_floor_ids)}개가 있지만 직사각 포켓 조건을 확정하지 못했습니다. 이 위치의 폭·벽 높이는 미측정입니다." if unresolved_floor_ids else
        "현재 인식 범위의 직사각 포켓 바닥을 찾지 못했습니다.",
        "모서리에 반경이나 코너 여유를 추가하고 폭·날 길이·도달 길이를 함께 확인하세요." if pockets else
        "곡선·분할 면·섬이 있는 포켓은 별도 CAD/CAM 검토가 필요합니다.",
        {"pockets": pocket_rows, "count": len(pockets) if cad_ready else None,
         "incomplete_boundary_face_ids": incomplete_boundaries,
         "unresolved_floor_face_ids": unresolved_floor_ids}, pocket_ids + unresolved_floor_ids,
        ["직선 4변 바닥·평면 수직벽·동일 벽높이만 인식합니다. 전체 포켓 목록이 아닙니다.",
         "벽 높이는 공구 경로 길이 또는 전체 진입 깊이를 보장하지 않습니다. 홀더·고정구·소재 제거 순서는 미검토입니다.",
         "내부 바닥 후보는 채널·밀폐 공동·섬·곡선 경계나 수치 불일치일 수도 있습니다. 열린 포켓으로 확정한 수가 아닙니다.",
         "벽 높이가 날 길이보다 커도 여러 깊이의 절입이나 목부 공구를 사용할 수 있으므로 그 자체를 가공 불가로 판정하지 않습니다.",
         "수치 경계의 비교는 초과로 확정하지 않습니다. 같은 치수는 실제 가공 여유가 확보되었다는 뜻이 아닙니다."]))
    access = None
    if visibility:
        from .accessibility import run_point_visibility
        access = run_point_visibility(model.mesh, direction)
        blocked = access.get("occluded_face_indices", [])
        counts = access.get("measurements", {}).get("sample_state_counts", {})
        calculated = access.get("measurements", {}).get("evaluated_samples", 0)
        selected = access.get("measurements", {}).get("selected_samples", 0)
        observation = (f"표본 {selected}개 중 {calculated}개의 상태를 계산했습니다. "
            f"가려짐 {counts.get('occluded', 0)}개, 반대쪽을 향함 {counts.get('back_facing', 0)}개, "
            f"축과 평행한 면 {counts.get('tangent', 0)}개입니다. " if calculated else
            "표본의 가림 여부를 확정하지 못했습니다. ")
        finding = _finding(model, "cnc_visibility", "선택 방향의 표면 가림", "attention" if blocked else "observed" if access["status"] == "complete" else "unknown",
            observation + access["reason"],
            "가려진 위치와 반대쪽 표면에 다른 접근 방향이 필요한지 확인하세요. 실제 공구·홀더 충돌은 CAM에서 확인하세요.",
            access.get("measurements", {}), limitations=access.get("limitations", []))
        finding["face_indices"] = blocked
        findings.append(finding)
    else:
        findings.append(_finding(model, "cnc_visibility", "선택 방향의 표면 가림", "unknown",
            "표면 표본의 직선 접근 검사를 아직 실행하지 않았습니다.", "표면 가림 검사를 실행해 선택 방향에서 가려진 위치를 확인하세요."))
    return dict(schema_version="dfm-review-1", process_family="machining", process="MILLING_3AXIS",
        created_utc=datetime.now(timezone.utc).isoformat(), model_fingerprint=model.fingerprint,
        input=model.metadata, profile=profile.to_dict(), direction=direction.tolist(),
        current_orientation={"transform": np.eye(4).tolist()}, findings=findings, visibility=access,
        sources=[dict(id=key, **value) for key, value in SOURCES.items()],
        numerical_policy={"length_absolute_comparison_mm": LENGTH_ABSOLUTE_COMPARISON_MM,
            "comparison_relative_tolerance": COMPARISON_RELATIVE_TOLERANCE,
            "axis_sine_tolerance": AXIS_SINE_TOLERANCE,
            "axis_angle_tolerance_deg": math.degrees(math.asin(AXIS_SINE_TOLERANCE)),
            "boundary_scope": "Floating-point comparison policy only; boundary cases do not establish design tolerance, machining clearance or feasibility."},
        scope="Fixed-axis geometric review; not machining certification or success probability.",
        unassessed=["공구·홀더·고정구의 실제 경로 충돌", "소재와 고정·가공 순서", "절삭력·처짐·진동·표면 품질",
                    "공차와 PMI", "분할·자유곡면 포켓 및 교차 홀", "가공 시간·비용·성공 확률"])
