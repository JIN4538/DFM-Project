"""Propose missing end-mill dimensions from measured, fixed-axis features.

This module does not infer a catalogue product or fit a learned model. The
diameter fraction and axial allowance are disclosed application assumptions.
Original user dimensions, sharp corners and missing geometry stay visible.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import fields
import math

import numpy as np

from .machining import MachiningProfile, _axis_angle_and_alignment, _length_comparison, review_machining
from amdfm.orientation import unit_direction


TOOL_FIELDS = ("tool_diameter_mm", "flute_length_mm", "reach_mm")
POLICY_VERSION = "measured-tool-proposal-1"


def _number(value, *, zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and (value >= 0 if zero else value > 0) else None


def _profile(values):
    return MachiningProfile(**{f.name: deepcopy(values[f.name]) for f in fields(MachiningProfile) if f.name in values})


def _generated_evidence(profile, automatic_fields):
    evidence = profile.get("condition_evidence")
    if not evidence or not automatic_fields:
        return
    # Keep the selected source and its original values; do not attribute a new
    # geometry proposal to a catalogue, manufacturer or the user's own input.
    for name in automatic_fields:
        value = profile[name]
        evidence["input_snapshot"][name] = value
        if name in evidence.get("fields", {}):
            evidence["fields"][name].update(effective=value, overridden=True, status="geometry_proposal")
        evidence.get("user_inputs", {}).pop(name, None)
        evidence.setdefault("generated_inputs", {})[name] = dict(effective=value, status="geometry_proposal", policy=POLICY_VERSION)
    evidence["overridden_fields"] = [key for key, row in evidence["fields"].items() if row.get("overridden")]


def recommend_tool_dimensions(report, *, model=None, diameter_fraction=0.8, length_allowance_mm=1.0):
    """Fill only absent dimensions; return explicit constraints and residuals.

    ``report`` must be a review for the current approach direction. ``model``
    optionally supplies axial extents of the very same measured partial
    cylinders and maps occluded triangles to their CAD faces. A cylindrical
    interval is never renamed as complete hole depth. Full cylinders use the
    explicit hole-milling assumption; separate drill requirements are retained.
    """
    fraction = _number(diameter_fraction)
    allowance = _number(length_allowance_mm, zero=True)
    if fraction is None or fraction >= 1 or allowance is None:
        raise ValueError("지름 비율은 0과 1 사이, 길이 여유는 유한한 0 이상의 값이어야 합니다.")
    if report.get("process") not in ("CNC", "MILLING_3AXIS"):
        raise ValueError("선택 접근축의 절삭 검토 결과가 필요합니다.")
    original = _profile(report.get("profile") or {})
    original.validate()
    proposed = original.to_dict()
    measured = {row.get("id"): row for row in report.get("findings", [])}
    ready = (measured.get("cnc_input", {}).get("measurements") or {}).get("cad_feature_dimensions_available") is True
    constraints, unresolved, geometry_changes, drill_requirements = [], [], [], []

    def issue(code, reason, *, face_id=None, field=None):
        row = dict(code=code, reason=reason)
        if face_id is not None:
            row["cad_face_id"] = face_id
        if field:
            row["field"] = field
        if row not in unresolved:
            unresolved.append(row)

    direction = unit_direction(report.get("direction", (0, 0, 1)))
    by_id, occluded_ids = {}, set()
    projection, projection_origin = None, None
    visibility = report.get("visibility") or {}
    blocked = list(visibility.get("occluded_face_indices") or measured.get("cnc_visibility", {}).get("face_indices") or [])
    if model is not None:
        if report.get("model_fingerprint") != model.fingerprint:
            raise ValueError("추천에 사용할 형상과 검토 결과가 다릅니다.")
        by_id = {row["face_id"]: row for row in model.cad_features}
        vertices = np.asarray(model.mesh.vertices, dtype=float)
        if vertices.ndim == 2 and len(vertices) and np.isfinite(vertices).all():
            projection_origin = vertices[0]
            projection = (vertices - projection_origin) @ direction
        if model.face_ids is not None:
            occluded_ids = {int(model.face_ids[index]) for index in blocked if 0 <= index < len(model.face_ids)}
    if blocked:
        issue("occluded_surfaces", "가려진 면에는 다른 접근 방향이 필요할 수 있습니다.")
    access_finding = measured.get("cnc_visibility", {})
    if not visibility or visibility.get("status") != "complete" or access_finding.get("status") == "unknown":
        issue("access_unresolved", "표면 접근 검토가 미완료입니다.")
    for key in ("cnc_coverage", "cnc_holes", "cnc_curved_corners", "cnc_rectangular_pockets"):
        measurements = measured.get(key, {}).get("measurements") or {}
        for name in ("incomplete_boundary_face_ids", "unresolved_cylinder_face_ids", "unsupported_face_ids", "unresolved_floor_face_ids"):
            for face_id in measurements.get(name) or []:
                issue(name, "치수를 확정하지 못한 특징은 자동 공구 조건에서 제외했습니다.", face_id=face_id)
    if not ready:
        issue("cad_dimensions_unavailable", "단일 솔리드 STEP의 측정 치수가 필요합니다.")
    else:
        for row in (measured.get("cnc_holes", {}).get("measurements") or {}).get("cylindrical_faces") or []:
            face_id = row.get("face_id")
            diameter, length = _number(row.get("diameter_mm")), _number(row.get("cylindrical_length_mm"))
            drill = dict(cad_face_id=face_id, nominal_diameter_mm=diameter, measured_cylindrical_interval_mm=length,
                         status="dimension_requirement", scope="드릴을 선택할 경우의 명목지름; 입구·드릴 끝·전체 깊이는 미확정")
            drill_requirements.append(drill)
            if row.get("axis_aligned") is not True:
                drill["status"] = "other_axis"
                issue("other_axis", "축이 다른 원통면은 접근 방향을 바꿔 검토하세요.", face_id=face_id)
                continue
            if face_id in occluded_ids:
                drill["status"] = "occluded"
                issue("occluded_feature", "가려진 원통면은 현재 방향의 자동 치수 산정에서 제외했습니다.", face_id=face_id)
                continue
            if diameter is None or length is None:
                drill["status"] = "unresolved"
                issue("missing_hole_dimensions", "원통면의 지름·축 구간 치수가 미확정입니다.", face_id=face_id)
                continue
            constraints.append(dict(kind="hole_milling", cad_face_id=face_id, diameter_max_mm=diameter,
                                    flute_min_mm=length, reach_min_mm=length, length_basis="cylindrical_interval"))
        for row in (measured.get("cnc_curved_corners", {}).get("measurements") or {}).get("cylindrical_faces") or []:
            face_id, radius = row.get("face_id"), _number(row.get("radius_mm"), zero=True)
            if face_id in occluded_ids:
                issue("occluded_feature", "가려진 오목면은 현재 방향의 자동 치수 산정에서 제외했습니다.", face_id=face_id)
                continue
            if radius is None:
                issue("missing_corner_radius", "오목면 반경이 미확정입니다.", face_id=face_id)
                continue
            if radius == 0:
                geometry_changes.append(dict(code="sharp_corner", cad_face_id=face_id, reason="내부 직각에는 반경 또는 코너 여유가 필요합니다."))
                continue
            length = _number(row.get("axial_extent_mm"))
            feature = by_id.get(face_id, {})
            if feature.get("kind") == "cylinder" and feature.get("role") == "inner" and not feature.get("full_circumference"):
                if not _axis_angle_and_alignment(feature["axis"], direction)[1]:
                    issue("other_axis", "오목면의 축이 현재 접근축과 다릅니다.", face_id=face_id)
                    continue
                raw_radius = _number(feature.get("diameter_mm"))
                if raw_radius is None or not math.isclose(raw_radius / 2, radius, rel_tol=1e-10, abs_tol=1e-9):
                    issue("inconsistent_corner_measurement", "형상과 보고서의 오목면 반경이 달라 자동 추천을 보류했습니다.", face_id=face_id)
                    continue
                length = _number(feature.get("axial_extent_mm"))
            if length is None:
                issue("missing_corner_length", "오목면의 축 구간 길이가 없어 날·돌출 길이 조건을 확정하지 못했습니다.", face_id=face_id)
            constraints.append(dict(kind="concave_cylinder", cad_face_id=face_id, diameter_max_mm=2 * radius,
                                    flute_min_mm=length, reach_min_mm=length, length_basis="cylindrical_interval"))
        for row in (measured.get("cnc_rectangular_pockets", {}).get("measurements") or {}).get("pockets") or []:
            face_id = row.get("floor_face_id")
            if face_id in occluded_ids:
                issue("occluded_feature", "가려진 포켓 바닥은 현재 방향의 자동 치수 산정에서 제외했습니다.", face_id=face_id)
                continue
            width, depth = _number(row.get("width_mm")), _number(row.get("wall_height_mm"))
            if width is None or depth is None:
                issue("missing_pocket_dimensions", "포켓의 폭·벽 높이가 미확정입니다.", face_id=face_id)
                continue
            radius = _number(row.get("internal_corner_radius_mm", 0), zero=True)
            if radius == 0:
                geometry_changes.append(dict(code="sharp_corner", cad_face_id=face_id, reason="내부 직각에는 반경 또는 코너 여유가 필요합니다."))
            elif radius is None:
                issue("missing_pocket_radius", "포켓 내부 반경이 미확정입니다.", face_id=face_id)
            constraints.append(dict(kind="rectangular_pocket", cad_face_id=face_id,
                                    diameter_max_mm=min(width, 2 * radius) if radius else width,
                                    flute_min_mm=depth, reach_min_mm=depth, length_basis="wall_height"))
        for row in (measured.get('cnc_learned_pockets',{}).get('measurements') or {}).get('pockets') or []:
            face_id=row.get('floor_face_id')
            if face_id in occluded_ids:
                issue('occluded_feature','가려진 포켓 바닥은 자동 치수 산정에서 제외했습니다.',face_id=face_id)
                continue
            entry,depth=_number(row.get('entry_circle_diameter_mm')),_number(row.get('wall_height_mm'))
            if entry is None or depth is None or row.get('measurement_method')!='Exact CAD face planes/vertices; closed prism boundary verified':
                issue('missing_pocket_dimensions','CAD에서 확인된 진입원·벽 높이가 필요합니다.',face_id=face_id)
                continue
            constraints.append(dict(kind='verified_polygon_pocket',cad_face_id=face_id,diameter_max_mm=entry,
                                    flute_min_mm=depth,reach_min_mm=depth,length_basis='wall_height'))
            geometry_changes.append(dict(code='sharp_corner',cad_face_id=face_id,reason='다각형 내부 코너에 엔드밀 반경 여유를 추가하세요.'))

    # A lower cylindrical segment cannot be reached by its segment length
    # alone. Use a disclosed common plane above the tessellated part, rather
    # than pretending each segment has a separate entrance. This can be long
    # when a remote boss sets that plane; it is not a minimum/toolpath solution.
    for requirement in constraints:
        feature_triangles = None
        if projection is not None and model.face_ids is not None and requirement["cad_face_id"] is not None:
            mask = np.asarray(model.face_ids) == requirement["cad_face_id"]
            if len(mask) == len(model.mesh.faces) and np.any(mask):
                feature_triangles = np.asarray(model.mesh.faces)[mask]
        if feature_triangles is not None:
            high = float(max(projection))
            low = float(np.min(projection[feature_triangles]))
            envelope_reach = high - low
            if _number(envelope_reach) is not None:
                requirement["reach_candidate_mm"] = max(envelope_reach, requirement["reach_min_mm"] or envelope_reach)
                requirement["reach_basis"] = "model_mesh_envelope_to_feature"
                requirement["reach_reference"] = dict(projection_origin_mm=projection_origin.tolist(),
                    entry_plane_projection_mm=high, feature_min_projection_mm=low,
                    measured_envelope_distance_mm=envelope_reach)
            else:
                issue("entry_depth_unmeasured", "형상 상단부터 특징까지의 진입 길이를 확정하지 못했습니다.", face_id=requirement["cad_face_id"])
        else:
            requirement["reach_basis"] = "feature_interval_only"
            issue("entry_depth_unmeasured", "진입 기준면부터 특징까지의 전체 길이는 미측정입니다.", face_id=requirement["cad_face_id"])
    if constraints:
        issue("holder_path_unverified", "공구 몸통·홀더와 진입 경로는 별도 확인이 필요합니다.")
    diameter_max = min((r["diameter_max_mm"] for r in constraints), default=None)
    flute_min = max((r["flute_min_mm"] for r in constraints if r["flute_min_mm"] is not None), default=None)
    reach_min = max((r.get("reach_candidate_mm", r["reach_min_mm"]) for r in constraints
                     if r.get("reach_candidate_mm", r["reach_min_mm"]) is not None), default=None)
    automatic_fields = []
    if proposed["tool_diameter_mm"] is None and diameter_max is not None:
        value = diameter_max * fraction
        if _number(value) is not None:
            proposed["tool_diameter_mm"] = value
            automatic_fields.append("tool_diameter_mm")
    if flute_min is not None:
        target_flute = flute_min + allowance
        if not math.isfinite(target_flute):
            issue("length_overflow", "길이와 여유를 합한 값이 계산 범위를 벗어났습니다.")
        else:
            if proposed["flute_length_mm"] is None:
                fixed_reach = proposed["reach_mm"]
                if fixed_reach is None or not _length_comparison(flute_min, fixed_reach)[0]:
                    proposed["flute_length_mm"] = min(target_flute, fixed_reach) if fixed_reach is not None else target_flute
                    automatic_fields.append("flute_length_mm")
                    if fixed_reach is not None and fixed_reach < target_flute:
                        issue("allowance_limited", "입력한 돌출 길이에 맞춰 날 길이의 추가 여유를 줄였습니다.", field="flute_length_mm")
                else:
                    issue("flute_reach_incompatible", "입력한 돌출 길이가 측정 길이보다 짧아 날 길이 자동 입력을 보류했습니다.", field="flute_length_mm")
    if reach_min is not None and proposed["reach_mm"] is None:
        target_reach = reach_min + allowance
        if math.isfinite(target_reach):
            proposed["reach_mm"] = max(target_reach, proposed["flute_length_mm"] or target_reach)
            automatic_fields.append("reach_mm")
        else:
            issue("length_overflow", "길이와 여유를 합한 값이 계산 범위를 벗어났습니다.")
    for name in TOOL_FIELDS:
        if proposed[name] is None:
            issue("missing_tool_dimension", "이 치수를 제안할 측정값이 부족합니다.", field=name)
    _generated_evidence(proposed, automatic_fields)
    _profile(proposed).validate()

    conflicts, comparisons = [], []
    for requirement in constraints:
        envelope = requirement.get("reach_candidate_mm")
        if proposed["reach_mm"] is not None and envelope is not None and _length_comparison(envelope, proposed["reach_mm"])[0]:
            issue("envelope_clearance_unverified", "돌출 길이가 전체 형상 상단 기준보다 짧습니다. 해당 위치의 실제 진입면을 확인하세요.",
                  face_id=requirement["cad_face_id"], field="reach_mm")
        for name, bound, upper in (("tool_diameter_mm", "diameter_max_mm", True),
                                   ("flute_length_mm", "flute_min_mm", False), ("reach_mm", "reach_min_mm", False)):
            value, limit = proposed[name], requirement[bound]
            if value is None or limit is None:
                continue
            exceeded, boundary = _length_comparison(value, limit) if upper else _length_comparison(limit, value)
            assumption_only = name == "flute_length_mm" and requirement["kind"] in ("hole_milling", "concave_cylinder")
            if exceeded and assumption_only:
                issue("full_height_flute_unverified", "날 길이가 원통 구간보다 짧습니다. 여러 깊이의 절입·목부 공구 조건을 확인하세요.",
                      face_id=requirement["cad_face_id"], field=name)
            comparison = dict(kind=requirement["kind"], cad_face_id=requirement["cad_face_id"], field=name,
                              value_mm=value, limit_mm=limit, relation="at_most" if upper else "at_least",
                              conflict=exceeded and not assumption_only, numerical_boundary=boundary,
                              assumption_only=assumption_only, assumption_shortfall=bool(exceeded and assumption_only))
            comparisons.append(comparison)
            if comparison["conflict"]:
                conflicts.append(comparison)
    for change in geometry_changes:
        change["suggested_minimum_radius_mm"] = proposed["tool_diameter_mm"] / 2 if proposed["tool_diameter_mm"] is not None else None
    complete = all(proposed[name] is not None for name in TOOL_FIELDS)
    known_coverage = bool(constraints) and all(r["flute_min_mm"] is not None for r in constraints)
    incomplete_dimensions = [row for row in unresolved if row["code"] not in ("access_unresolved", "holder_path_unverified", "allowance_limited")]
    coverage_complete = known_coverage and not incomplete_dimensions
    absent_features_status = "unavailable" if any(row["code"] not in ("access_unresolved", "missing_tool_dimension") for row in unresolved) else "not_applicable"
    status = ("unavailable" if not ready else "conflict" if conflicts else absent_features_status if not constraints and not geometry_changes
              else "partial" if not complete else "conditional" if unresolved or geometry_changes else "recommended")
    return dict(schema_version=POLICY_VERSION, status=status, complete=complete,
                values={name: proposed[name] for name in TOOL_FIELDS}, proposed_profile=proposed,
                original_profile=original.to_dict(), automatic_fields=automatic_fields,
                fixed_fields=[name for name in TOOL_FIELDS if getattr(original, name) is not None],
                direction=direction.tolist(), constraints=constraints, comparisons=comparisons, conflicts=conflicts,
                geometry_changes=geometry_changes, unresolved=unresolved, drill_requirements=drill_requirements,
                dimension_coverage_complete=coverage_complete,
                measured_constraints_satisfied=not conflicts if constraints else None,
                single_tool_dimension_match=False if conflicts or geometry_changes else True if complete and coverage_complete and not unresolved else None,
                assumptions=dict(diameter_fraction=fraction, length_allowance_mm=allowance,
                    policy="측정 개구·내부 반경의 지름 상한에 비율 적용; 축 구간·벽 높이에 길이 여유 추가",
                    provenance="앱의 편집 가능한 초기 제안 정책; 제조사 표준값·학습 예측·실재 제품 선택이 아님",
                    hole_strategy="원통 특징은 원호 밀링을 가정한 엔드밀 치수 제안; 드릴 명목지름 요구는 별도",
                    length_scope="날 길이는 벽 높이·원통 구간, 돌출은 형상 전체 메시 상단부터 특징 끝까지의 투영 거리 기준",
                    entry_reference="전체 형상 메시의 선택축 최대투영 평면; 떨어진 돌출부 때문에 길어질 수 있는 초기 후보이며 실제 최소 진입 길이가 아님",
                    unmeasured="실제 홀 입구·공구 몸통·홀더·고정구·경로 및 메시 표본 밖의 정확한 곡면 여유"))


def review_with_tool_recommendation(model, profile, direction=(0, 0, 1), *, visibility=False,
                                    diameter_fraction=0.8, length_allowance_mm=1.0):
    """Measure once, fill absent values, and recalculate the actual candidate."""
    initial = review_machining(model, profile, direction, visibility=visibility)
    from .external_features_review import attach_external_features
    attach_external_features(initial,model)
    recommendation = recommend_tool_dimensions(initial, model=model, diameter_fraction=diameter_fraction,
                                                length_allowance_mm=length_allowance_mm)
    if recommendation["automatic_fields"]:
        result = review_machining(model, _profile(recommendation["proposed_profile"]), direction)
        result["visibility"] = deepcopy(initial["visibility"])
        visibility_finding = next(row for row in initial["findings"] if row["id"] == "cnc_visibility")
        result["findings"] = [deepcopy(visibility_finding) if row["id"] == "cnc_visibility" else row for row in result["findings"]]
    else:
        result = initial
    if result is not initial:attach_external_features(result,model)
    recommendation["recomputed"] = True
    result["tool_recommendation"] = recommendation
    new_conditions = {"full_height_flute_unverified", "envelope_clearance_unverified"}
    if (recommendation["automatic_fields"] or recommendation["conflicts"]
            or any(row["code"] in new_conditions for row in recommendation["unresolved"])
            or any(getattr(profile, name) is None for name in TOOL_FIELDS)):
        conflicts, unresolved = recommendation["conflicts"], recommendation["unresolved"]
        ids = {row["cad_face_id"] for row in recommendation["constraints"] if row["cad_face_id"] is not None}
        ids.update(row["cad_face_id"] for row in unresolved if row.get("cad_face_id") is not None)
        face_indices = np.flatnonzero(np.isin(model.face_ids, list(ids))).tolist() if model.face_ids is not None else []
        status = ("not_applicable" if recommendation["status"] == "not_applicable" else "attention" if conflicts else
                  "unknown" if unresolved or not recommendation["complete"] else "observed")
        reason = ("현재 인식 범위에서 공구 치수와 비교할 내부 특징이 없습니다." if status == "not_applicable" else
                  f"입력한 공구 치수와 측정 특징의 제안 조건 {len(conflicts)}개가 맞지 않습니다." if conflicts else
                  "측정 특징에서 공구 치수를 채웠습니다. 실제 진입면·공구 목부·홀더 조건은 확인이 필요합니다." if recommendation["complete"] else
                  "측정 치수가 있는 항목만 제안했습니다. 나머지 공구 치수는 미확정입니다.")
        action = ("입력 치수와 표시한 한계를 비교하고 공구·접근 방향을 선택하세요." if conflicts else
                  "원호 밀링의 진입면과 공구 목부·홀더 조건을 확인하세요." if any(r["kind"] == "hole_milling" for r in recommendation["constraints"]) else
                  "표시한 위치의 진입면과 공구 목부·홀더 조건을 확인하세요.")
        result["findings"].append(dict(id="cnc_tool_recommendation", title="자동 공구 치수 제안", status=status,
            reason=reason, action=action,
            method="Measured feature constraints, disclosed diameter/length allowances and recomputed candidate dimensions",
            evidence=["CNC_TOOL_DIMENSIONS", "CNC_GEOMETRY", "CNC_ACCESS_SCOPE"],
            measurements=deepcopy({name: recommendation[name] for name in ("values", "automatic_fields", "fixed_fields",
                "constraints", "comparisons", "conflicts", "unresolved", "assumptions", "drill_requirements")}),
            cad_face_ids=sorted(ids), face_indices=face_indices, severity="review" if conflicts else "info",
            limitations=["측정한 구간 전체를 날 길이로 덮는 초기 가정입니다. 여러 깊이의 절입·목부 공구·다른 경로는 별도 비교합니다.",
                         "형상 전체 상단 기준 돌출 후보는 떨어진 돌출부 때문에 길어질 수 있으며 실제 최소 길이를 뜻하지 않습니다."]))
    return result
