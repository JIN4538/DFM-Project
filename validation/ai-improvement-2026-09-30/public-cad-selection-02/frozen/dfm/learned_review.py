"""Locally fitted rule/action models, with numeric verification at inference.

Only measured quantities and declared conditions enter the fitted models.
Coverage/state gates are separate; missing data never becomes a zero feature.
JSON trees are data, never executable/pickled objects.  Training is reproducible
with scripts/train_rule_model.py; inference needs only the standard library.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "data/models/rule_review_v1.json"
SCHEMA = "dfm-rule-model-1"
FEATURE_VERSION = "numeric-rule-inputs-2-conditioned"
TEACHER_FILES = ("amdfm/analysis.py", "amdfm/detail_summary.py", "amdfm/orientation.py",
                 "dfm/machining.py", "dfm/accessibility.py", "dfm/learned_review.py")
TASKS = {
    "wall": ("wall_ratio_margin_asinh",),
    "overhang": ("area_numeric_epsilon_margin_asinh",),
    "contact": ("area_numeric_epsilon_margin_asinh",),
    "cavities": ("internal_shell_count",),
    "build": ("x_available_margin_asinh", "y_available_margin_asinh", "z_available_margin_asinh"),
    "cad_holes": ("diameter_limit_margin_asinh", "limit_present", "axis_dot_margin_asinh", "polymer_process"),
    "layers": ("thin_area_log1p", "unsupported_area_log1p", "single_layer_area_log1p"),
    "cnc_holes": ("tool_diameter_margin_asinh", "reach_margin_asinh", "depth_ratio_margin_asinh", "axis_sine_margin_asinh",
                  "tool_present", "reach_present", "depth_limit_present"),
    "cnc_curved_corners": ("tool_diameter_margin_asinh", "tool_present"),
    "cnc_rectangular_pockets": ("tool_width_margin_asinh", "flute_margin_asinh", "reach_margin_asinh",
                                "tool_present", "flute_present", "reach_present"),
    "cnc_visibility": ("normal_dot_margin_asinh", "obstruction_distance_log1p"),
}
ACTION_IDS = {
    "wall": ("thicken_wall",), "overhang": ("reduce_downward_faces",),
    "contact": ("align_flat_base",), "cavities": ("review_enclosed_space",),
    "build": ("change_placement_or_space",),
    "cad_holes": ("enlarge_hole", "reorient_hole"),
    "layers": ("widen_thin_section", "support_layer", "thicken_single_layer"),
    "cnc_holes": ("smaller_tool", "longer_reach", "review_depth_ratio", "change_setup"),
    "cnc_curved_corners": ("smaller_tool_or_larger_radius",),
    "cnc_rectangular_pockets": ("smaller_tool_or_wider_pocket", "review_flute_length", "longer_reach", "add_corner_relief"),
    "cnc_visibility": ("change_setup",),
}
LABELS = {"wall": "벽", "overhang": "하향면", "contact": "바닥", "cavities": "밀폐 공간",
          "build": "배치 공간", "cad_holes": "구멍", "layers": "층간 형상",
          "cnc_holes": "구멍과 공구", "cnc_curved_corners": "내부 반경",
          "cnc_rectangular_pockets": "포켓", "cnc_visibility": "접근 방향"}
ACTION_TEXT = {
    "thicken_wall": ("벽 보강", "표시된 벽을 입력 기준까지 보강하세요."),
    "reduce_downward_faces": ("하향면 줄이기", "추천 방향을 적용하거나 표시된 면의 경사를 바꾸세요."),
    "align_flat_base": ("평평한 바닥 확보", "바닥으로 사용할 면을 빌드판과 나란하게 배치하세요."),
    "review_enclosed_space": ("밀폐 공간 검토", "밀폐 기능을 확인하고 공정에 맞는 내부 형상·배출 경로를 검토하세요."),
    "change_placement_or_space": ("배치 공간 초과", "다른 방향을 비교하거나 부품이 들어가는 공간을 선택하세요."),
    "enlarge_hole": ("구멍 지름 확대", "강조된 구멍을 입력한 최소 지름 이상으로 변경하세요."),
    "reorient_hole": ("구멍 방향 변경", "구멍 축을 적층 방향으로 돌리거나 천장 형상을 변경하세요."),
    "widen_thin_section": ("가는 단면 보강", "표시된 높이의 얇은 부분을 넓히거나 선폭 조건을 바꾸세요."),
    "support_layer": ("층간 지지 보완", "표시된 높이에서 방향·경사·지지 형상을 변경하세요."),
    "thicken_single_layer": ("얇은 돌출부 보강", "한 층에만 나타나는 부분의 두께나 층 높이를 조정하세요."),
    "smaller_tool": ("공구 지름 줄이기", "내부 원통 지름보다 작은 공구로 변경하거나 구멍을 넓히세요."),
    "longer_reach": ("공구 도달 길이 검토", "측정 구간과 돌출 길이를 대조하고 다른 접근 방향·공구 조건을 비교하세요."),
    "review_depth_ratio": ("깊이·지름 비율 검토", "입력 기준에 맞게 깊이를 줄이거나 지름·공구 조건을 바꾸세요."),
    "change_setup": ("다른 접근 방향 필요", "강조된 위치를 향하는 방향 또는 재고정 방향을 비교하세요."),
    "smaller_tool_or_larger_radius": ("공구와 내부 반경 불일치", "더 작은 공구를 선택하거나 내부 반경을 넓히세요."),
    "smaller_tool_or_wider_pocket": ("공구보다 좁은 포켓", "포켓을 넓히거나 더 작은 공구를 선택하세요."),
    "review_flute_length": ("포켓과 날 길이 검토", "벽 높이에 맞는 날 길이·목부 공구·가공 순서를 검토하세요."),
    "add_corner_relief": ("포켓 모서리 수정", "내부 직각에 공구 반경 또는 코너 여유를 추가하세요."),
}


def _number(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("숫자 측정값이 필요합니다")
    value = float(value)
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError("유한한 측정값의 범위를 확인하세요")
    return value


def _optional(value):
    return None if value is None else _number(value, positive=True)


def _ratio(a, b):
    value = a / b
    if not math.isfinite(value):
        raise ValueError("측정값 비율 범위를 확인하세요")
    return value


def _cmp_ratio(a, b):
    # Current CNC teacher's absolute and relative floating-point band.
    tolerance = max(1e-9, max(abs(a), abs(b)) * 1e-10)
    return _ratio(a, b + tolerance)


def _raw_features(task, values):
    """Primitive dimensionless comparisons before monotonic conditioning."""
    v = values
    if task == "wall":
        return [_ratio(_number(v["minimum_mm"], positive=True), _number(v["limit_mm"], positive=True))]
    if task in ("overhang", "contact"):
        return [_ratio(_number(v["area_mm2"]), 1e-8)]
    if task == "cavities":
        count = _number(v["shell_count"])
        if not count.is_integer():
            raise ValueError("공동 수는 정수입니다")
        return [count]
    if task == "build":
        tol = _number(v["tolerance_mm"])
        return [_ratio(_number(v[a], positive=True), _number(v[b], positive=True) + tol)
                for a, b in (("x_mm", "ax_mm"), ("y_mm", "ay_mm"), ("z_mm", "az_mm"))]
    if task == "cad_holes":
        diameter = _number(v["diameter_mm"], positive=True)
        limit = _optional(v.get("limit_mm"))
        dot = _number(v["axis_dot"])
        if dot > 1 + 1e-12 or v["process"] not in ("MEX", "VPP", "PBF_POLYMER", "PBF_METAL"):
            raise ValueError("구멍 방향 또는 공정 범위 오류")
        return [_ratio(diameter, limit) if limit else 1., float(limit is not None), min(1., dot), float(v["process"] == "PBF_POLYMER")]
    if task == "layers":
        return [_number(v[k]) for k in ("thin_area", "unsupported_area", "single_layer_area")]
    if task == "cnc_holes":
        diameter = _number(v["diameter_mm"], positive=True)
        length = _number(v["length_mm"], positive=True)
        tool, reach, limit = [_optional(v.get(k)) for k in ("tool_mm", "reach_mm", "ratio_limit")]
        angle = _number(v["angle_deg"])
        if angle > 90 + 1e-10:
            raise ValueError("축 각도 범위 오류")
        return [_cmp_ratio(tool, diameter) if tool else 0., _cmp_ratio(length, reach) if reach else 0.,
                _ratio(length / diameter, limit * (1 + 1e-10)) if limit else 0.,
                math.sin(math.radians(angle)) / 1e-8, float(tool is not None), float(reach is not None), float(limit is not None)]
    if task == "cnc_curved_corners":
        radius = _number(v["radius_mm"], positive=True)
        tool = _optional(v.get("tool_mm"))
        return [_cmp_ratio(tool, 2 * radius) if tool else 0., float(tool is not None)]
    if task == "cnc_rectangular_pockets":
        width, height = [_number(v[k], positive=True) for k in ("width_mm", "height_mm")]
        tool, flute, reach = [_optional(v.get(k)) for k in ("tool_mm", "flute_mm", "reach_mm")]
        return [_cmp_ratio(tool, width) if tool else 0., _cmp_ratio(height, flute) if flute else 0.,
                _cmp_ratio(height, reach) if reach else 0., float(tool is not None), float(flute is not None), float(reach is not None)]
    if task == "cnc_visibility":
        dot = float(v["normal_dot"])
        if isinstance(v["normal_dot"], bool) or not math.isfinite(dot) or abs(dot) > 1 + 1e-12:
            raise ValueError("법선 방향 범위 오류")
        return [dot, _number(v["obstruction_mm"]) if v.get("obstruction_mm") is not None else 0.]
    raise ValueError("학습 지원 범위 밖입니다")


def features_for(task, values):
    """Numeric margins with continuous, monotonic near-boundary conditioning.

    asinh avoids losing x~1 boundary differences during float32 tree inference.
    These are signed numeric distances, not boolean labels or rule statuses.
    """
    x = _raw_features(task, values)
    margin = lambda value, center=1.: math.asinh((value - center) / 1e-10)
    if task in ("wall", "overhang", "contact"):
        return [margin(x[0])]
    if task == "build":
        return [margin(v) for v in x]
    if task == "cad_holes":
        return [margin(x[0]), x[1], margin(x[2], .70710678), x[3]]
    if task == "layers":
        return [math.log1p(v / 1e-24) for v in x]
    if task == "cnc_holes":
        return [margin(v) for v in x[:4]] + x[4:]
    if task == "cnc_curved_corners":
        return [margin(x[0]), x[1]]
    if task == "cnc_rectangular_pockets":
        return [margin(v) for v in x[:3]] + x[3:]
    if task == "cnc_visibility":
        return [math.asinh((x[0] - 1e-10) / 1e-12), math.log1p(x[1] / 1e-24)]
    return x


def teacher_mask(task, values):
    """Current numeric rule teacher, independently checked against engine tests.

    This is supervised rule distillation, not independently measured truth.
    Teacher function outputs never enter features_for().
    """
    x = _raw_features(task, values)
    if task == "wall":
        return int(x[0] < 1)
    if task in ("overhang", "contact"):
        return int(x[0] > 1) if task == "overhang" else int(x[0] <= 1)
    if task == "cavities":
        return int(x[0] > 0)
    if task == "build":
        return int(any(v > 1 for v in x))
    if task == "cad_holes":
        return int(x[1] > 0 and x[0] < 1) + 2 * int(x[3] == 0 and x[2] < .70710678)
    if task == "layers":
        return sum((1 << i) for i, value in enumerate(x) if value > 0)
    if task == "cnc_holes":
        from .machining import _length_comparison
        aligned = x[3] <= 1
        tool, reach, limit = [values.get(k) for k in ("tool_mm", "reach_mm", "ratio_limit")]
        return (int(aligned and tool is not None and _length_comparison(tool, values["diameter_mm"])[0])
                + 2 * int(aligned and reach is not None and _length_comparison(values["length_mm"], reach)[0])
                + 4 * int(limit is not None and values["length_mm"] / values["diameter_mm"] > limit * (1 + 1e-10)) + 8 * int(not aligned))
    if task == "cnc_curved_corners":
        from .machining import _length_comparison
        return int(values.get("tool_mm") is not None and _length_comparison(values["tool_mm"], 2 * values["radius_mm"])[0])
    if task == "cnc_rectangular_pockets":
        from .machining import _length_comparison
        checks = ((values.get("tool_mm"), values["width_mm"]), (values["height_mm"], values.get("flute_mm")),
                  (values["height_mm"], values.get("reach_mm")))
        return 8 + sum((1 << i) for i, (a, b) in enumerate(checks) if a is not None and b is not None and _length_comparison(a, b)[0])
    if task == "cnc_visibility":
        return int(x[0] > 1e-10 and x[1] > 0)
    raise ValueError("학습 지원 범위 밖입니다")


def source_hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in TEACHER_FILES}


def _strict_json(raw):
    def reject(value):
        raise ValueError("비유한 JSON 값")
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError("중복 JSON 키")
            result[key] = value
        return result
    return json.loads(raw, parse_constant=reject, object_pairs_hook=pairs)


@lru_cache(maxsize=2)
def _read_model(path, stamp, size, manifest_stamp, manifest_size):
    path = Path(path)
    if size > 20_000_000 or manifest_size > 100_000:
        raise ValueError("학습 파일 크기 오류")
    raw = path.read_bytes()
    manifest = _strict_json(path.with_suffix(".manifest.json").read_bytes())
    checksum = hashlib.sha256(raw).hexdigest()
    if not isinstance(manifest, dict) or manifest.get("sha256") != checksum:
        raise ValueError("학습 파일 체크섬 불일치")
    model = _strict_json(raw)
    if not isinstance(model, dict) or model.get("schema") != SCHEMA or model.get("feature_version") != FEATURE_VERSION:
        raise ValueError("학습 모델 형식 불일치")
    if set(model.get("teacher_sources", {})) != set(TEACHER_FILES):
        raise ValueError("학습 근거 목록 불일치")
    if set(model.get("tasks", {})) != set(TASKS):
        raise ValueError("학습 항목 목록 불일치")
    for task, record in model["tasks"].items():
        if not isinstance(record, dict) or record.get("features") != list(TASKS[task]):
            raise ValueError("입력 특징 순서 불일치")
        classes, trees = record.get("classes"), record.get("trees")
        if not isinstance(classes, list) or not classes or len(set(classes)) != len(classes) or any(
                isinstance(c, bool) or not isinstance(c, int) or not 0 <= c < 2 ** len(ACTION_IDS[task]) for c in classes):
            raise ValueError("학습 행동 클래스 오류")
        if not isinstance(trees, list) or not 1 <= len(trees) <= 128:
            raise ValueError("학습 트리 수 오류")
        domain = record.get("domain")
        if not isinstance(domain, list) or len(domain) != len(TASKS[task]):
            raise ValueError("학습 범위 오류")
        for lower, upper in domain:
            if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in (lower, upper)) or lower > upper:
                raise ValueError("학습 범위 오류")
        for nodes in trees:
            if not isinstance(nodes, list) or not 1 <= len(nodes) <= 50_000:
                raise ValueError("학습 노드 수 오류")
            for index, node in enumerate(nodes):
                if not isinstance(node, list) or len(node) != 5:
                    raise ValueError("학습 노드 형식 오류")
                feature, threshold, left, right, votes = node
                if not isinstance(feature, int) or isinstance(feature, bool) or not isinstance(threshold, (float, int)) or not math.isfinite(threshold):
                    raise ValueError("학습 분기 오류")
                if feature == -2:
                    if not isinstance(votes, list) or len(votes) != len(classes) or any(
                            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in votes) or abs(sum(votes) - 1) > 1e-6:
                        raise ValueError("학습 잎 노드 오류")
                elif not (0 <= feature < len(TASKS[task]) and isinstance(left, int) and isinstance(right, int)
                          and index < left < len(nodes) and index < right < len(nodes)):
                    raise ValueError("학습 트리 순환·분기 오류")
    model["artifact_sha256"] = checksum
    return model


def load_model(model_path=None):
    path = Path(model_path or MODEL_PATH)
    manifest_path = path.with_suffix(".manifest.json")
    stat, manifest_stat = path.stat(), manifest_path.stat()
    model = _read_model(str(path.resolve()), stat.st_mtime_ns, stat.st_size, manifest_stat.st_mtime_ns, manifest_stat.st_size)
    if model["teacher_sources"] != source_hashes():
        raise ValueError("판정 규칙이 학습 이후 변경됐습니다. 재학습이 필요합니다")
    return model


def predict_mask(model, task, features):
    """Raw fitted prediction, before verification; None means out of domain."""
    record = model["tasks"][task]
    if len(features) != len(record["features"]):
        return None
    # Convert to float32 like sklearn at inference, without a numpy dependency.
    import struct
    xs = []
    for value, (lower, upper) in zip(features, record["domain"]):
        if not math.isfinite(value) or value < lower or value > upper:
            return None
        try:
            xs.append(struct.unpack("f", struct.pack("f", value))[0])
        except (OverflowError, struct.error):
            return None
    total = [0.] * len(record["classes"])
    for nodes in record["trees"]:
        index = 0
        while nodes[index][0] != -2:
            feature, threshold, left, right, _ = nodes[index]
            index = left if xs[feature] <= threshold else right
        for i, vote in enumerate(nodes[index][4]):
            total[i] += vote
    return record["classes"][max(range(len(total)), key=lambda i: total[i])]


def _actions(task, mask):
    return [name for i, name in enumerate(ACTION_IDS[task]) if mask & (1 << i)]


def _empty_item(task, reason, *, state="review"):
    return dict(finding_id=task, label=LABELS[task], state=state, origin="unavailable", predicted_issue=None,
                action_id=None, action_ids=[], model_action_ids=[], title=f"{LABELS[task]} · 추가 확인",
                action=reason, evidence=[], agreement=None, scope="학습 판단 보류", reason=reason,
                evaluated_rows=0, learned_rows=0, fallback_rows=0, recommendations=[])


def _dimension(value):
    return "미입력" if value is None else f"{_number(value, positive=True):,.4g} mm"


def _extract(report, task, finding):
    """Return scenarios, measurement strings, coverage, and missing reason.

    Existing status is a coverage gate only, never a model feature or label.
    Explicit observed candidates are additionally preserved by analyze_report.
    """
    p, m = report.get("profile", {}), finding.get("measurements", {})
    process = p.get("process", report.get("process"))
    if (task.startswith("cnc_") and process not in ("MILLING_3AXIS", "CNC") or
            not task.startswith("cnc_") and process not in ("MEX", "VPP", "PBF_POLYMER", "PBF_METAL")):
        return [], [], False, "현재 공정의 학습 적용 대상이 아닙니다"
    if task == "build" and p.get("build_volume_mm") is None:
        return [], [], False, "크기 제한 미적용"
    if task in ("contact", "overhang") and (process == "PBF_POLYMER" or task == "contact" and process != "MEX"):
        return [], [], False, "현재 공정의 학습 적용 대상이 아닙니다"
    if task == "wall":
        from amdfm.detail_summary import summarize_wall
        s = summarize_wall(report.get("details", {}).get("wall"), p.get("minimum_wall_mm"))
        if s["minimum_mm"] is None:
            return [], [], False, "벽 추가 계산으로 측정값을 확인하세요"
        if s["minimum_wall_mm"] is None:
            return [], [], False, "비교할 최소 벽 기준을 입력하세요"
        return [dict(minimum_mm=s["minimum_mm"], limit_mm=s["minimum_wall_mm"])], [f"최소 표본 {s['minimum_mm']:,.4g} mm / 기준 {s['minimum_wall_mm']:,.4g} mm"], s["complete"], "일부 벽 표본 미확인"
    if task == "layers":
        from amdfm.detail_summary import summarize_layers
        if process != "MEX":
            return [], [], False, "현재 공정의 학습 적용 대상이 아닙니다"
        s = summarize_layers(report.get("details", {}).get("layers"))
        scenario = {}
        for check in s["checks"]:
            if check["maximum_area_mm2"] is None:
                return [], [], False, "층간 측정을 완료하세요"
            scenario[check["key"] + "_area"] = check["maximum_area_mm2"]
        return [scenario], [f"수정 후보가 있는 층 {s['counts']['candidate_layers'] or 0}개"], s["complete"], "일부 층간 범위 미확인"
    if finding.get("status") in ("unknown", "not_applicable") and task not in ("cnc_holes", "cnc_curved_corners", "cnc_rectangular_pockets", "cnc_visibility"):
        return [], [], False, "필요한 측정 또는 조건을 확인하세요"
    if task == "overhang":
        area = m.get("projected_area_sum_mm2")
        boundary = m.get("threshold_equal_face_count", 0)
        return [dict(area_mm2=area)], [f"하향면 투영 합 {_number(area):,.4g} mm²"], not boundary, "기준 각도 부근 면을 확인하세요"
    if task == "contact":
        area = m.get("area_mm2")
        return [dict(area_mm2=area)], [f"평평한 바닥 {_number(area):,.4g} mm²"], True, ""
    if task == "cavities":
        count = m.get("internal_shell_count")
        return [dict(shell_count=count)], [f"내부 밀폐 경계 {_number(count):g}개"], True, ""
    if task == "build":
        available = p.get("build_volume_mm")
        if not available:
            return [], [], False, "크기 제한 미적용"
        dims = m.get("placed_extents_mm")
        clearance = _number(p.get("clearance_mm", 0))
        if len(dims or []) != 3 or len(available) != 3:
            raise ValueError("배치 치수 오류")
        values = dict(zip(("x_mm", "y_mm", "z_mm"), dims))
        values.update(zip(("ax_mm", "ay_mm", "az_mm"), [_number(v, positive=True) - 2 * clearance for v in available]))
        values["tolerance_mm"] = max(1e-9, max(dims) * 1e-10)
        return [values], ["형상 " + " × ".join(f"{v:,.4g}" for v in dims) + " mm"], True, ""
    if task == "cad_holes":
        if m.get("inner_face_count") is None:
            return [], [], False, "구멍 치수는 단일 솔리드 STEP에서 확인하세요"
        direction = report.get("direction", report.get("current_orientation", {}).get("direction"))
        if direction is None:
            direction = report.get("current_orientation", {}).get("direction")
        norm = math.sqrt(sum(float(v) ** 2 for v in direction))
        if norm <= 0 or not math.isfinite(norm):
            raise ValueError("검토 방향 오류")
        rows = []
        for row in m.get("cylindrical_faces", []):
            if row.get("role") == "inner":
                axis = row["axis"]
                anorm = math.sqrt(sum(float(v) ** 2 for v in axis))
                dot = abs(sum(a * b for a, b in zip(axis, direction)) / (anorm * norm))
                rows.append(dict(diameter_mm=row["diameter_mm"], limit_mm=p.get("minimum_hole_mm"), axis_dot=dot, process=process))
        if len(rows) != m.get("inner_face_count"):
            raise ValueError("구멍 측정 수 불일치")
        complete = not rows or p.get("minimum_hole_mm") is not None
        evidence = [f"내측 원통면 {len(rows)}개"]
        if rows:
            evidence.insert(0, f"최소 지름 {_dimension(min(r['diameter_mm'] for r in rows))} / 홀 기준 {_dimension(p.get('minimum_hole_mm'))}")
        return rows, evidence, complete, "최소 홀 기준 미입력"
    if task == "cnc_holes":
        rows = [dict(diameter_mm=r["diameter_mm"], length_mm=r["cylindrical_length_mm"], angle_deg=r["axis_angle_deg"],
                     tool_mm=p.get("tool_diameter_mm"), reach_mm=p.get("reach_mm"), ratio_limit=p.get("hole_depth_ratio_limit"))
                for r in m.get("cylindrical_faces", [])]
        if m.get("face_count") is not None and m["face_count"] != len(rows):
            raise ValueError("원통면 측정 수 불일치")
        complete = (m.get("face_count") is not None and not m.get("unresolved_cylinder_face_ids")
                    and (not rows or p.get("tool_diameter_mm") is not None and p.get("reach_mm") is not None))
        evidence = [f"내부 원통면 {len(rows)}개"]
        if rows:
            evidence = [f"최소 지름 {_dimension(min(r['diameter_mm'] for r in rows))} / 공구 {_dimension(p.get('tool_diameter_mm'))}",
                        f"최장 원통 구간 {_dimension(max(r['length_mm'] for r in rows))} / 돌출 {_dimension(p.get('reach_mm'))}"]
            if any(r["angle_deg"] > math.degrees(math.asin(1e-8)) for r in rows):
                evidence.insert(0, f"선택 축과 최대 {max(r['angle_deg'] for r in rows):,.4g}° 차이")
        return rows, evidence, complete, "공구 조건 또는 원통면 미확인"
    if task == "cnc_curved_corners":
        rows = [dict(radius_mm=r["radius_mm"], tool_mm=p.get("tool_diameter_mm")) for r in m.get("cylindrical_faces", [])]
        complete = finding.get("status") not in ("unknown", "not_applicable") and not m.get("unresolved_cylinder_face_ids")
        evidence = [f"오목 원통면 {len(rows)}개"]
        if rows:
            tool = p.get("tool_diameter_mm")
            evidence.insert(0, f"최소 내부 반경 {_dimension(min(r['radius_mm'] for r in rows))} / 공구 반경 {_dimension(tool / 2 if tool is not None else None)}")
        return rows, evidence, complete, "공구 지름 또는 오목면 미확인"
    if task == "cnc_rectangular_pockets":
        rows = [dict(width_mm=r["width_mm"], height_mm=r["wall_height_mm"], tool_mm=p.get("tool_diameter_mm"),
                     flute_mm=p.get("flute_length_mm"), reach_mm=p.get("reach_mm")) for r in m.get("pockets", [])]
        if m.get("count") is not None and m["count"] != len(rows):
            raise ValueError("포켓 측정 수 불일치")
        complete = (m.get("count") is not None and not m.get("unresolved_floor_face_ids") and not m.get("incomplete_boundary_face_ids")
                    and (not rows or all(p.get(k) is not None for k in ("tool_diameter_mm", "flute_length_mm", "reach_mm"))))
        evidence = [f"직사각 포켓 {len(rows)}개"]
        if rows:
            evidence = [f"최소 폭 {_dimension(min(r['width_mm'] for r in rows))} / 공구 {_dimension(p.get('tool_diameter_mm'))}",
                        f"최대 벽 높이 {_dimension(max(r['height_mm'] for r in rows))} / 날 {_dimension(p.get('flute_length_mm'))} · 돌출 {_dimension(p.get('reach_mm'))}"]
        return rows, evidence, complete, "공구 조건 또는 일부 포켓 미확인"
    if task == "cnc_visibility":
        visibility = report.get("visibility") or {}
        rows = [dict(normal_dot=r["normal_dot_direction"], obstruction_mm=r.get("obstruction_distance_mm"))
                for r in visibility.get("samples", [])
                if r.get("state") in ("visible", "occluded", "back_facing", "tangent") and not r.get("reason")]
        complete = visibility.get("status") == "complete" and len(rows) == m.get("selected_samples") and bool(rows)
        return rows, [f"가려진 표본 {sum(teacher_mask(task, r) > 0 for r in rows)} / 확인한 표본 {len(rows)}개"], complete, "접근 표본 미확인"
    raise ValueError("지원하지 않는 학습 항목")


def analyze_report(report, *, model_path=None):
    """Return concise, JSON-safe learned conclusions without mutating report."""
    model, model_error = None, None
    try:
        model = load_model(model_path)
    except (OSError, ValueError, KeyError, TypeError, OverflowError, RecursionError):
        model_error = "학습 파일 또는 규칙 버전이 맞지 않아 규칙 계산으로 확인했습니다"
    findings = {f.get("id"): f for f in report.get("findings", []) if isinstance(f, dict)}
    process = report.get("profile", {}).get("process", report.get("process"))
    tasks = [key for key in TASKS if key in findings]
    if process == "MEX" and "layers" not in tasks:
        tasks.append("layers")
    items = []
    for task in tasks:
        finding = findings.get(task, {})
        item = _empty_item(task, "측정값을 확인하세요")
        try:
            rows, evidence, complete, reason = _extract(report, task, finding)
            if not rows:
                if complete and finding.get("status") != "attention":
                    item.update(state="clear", origin="rule_fallback", predicted_issue=False, title=f"{LABELS[task]} · 인식 범위의 수정 후보 없음",
                                action="다른 검토 항목을 확인하세요", evidence=evidence, reason="인식 범위에 해당 특징이 없습니다", scope="특징 인식 범위")
                else:
                    item = _empty_item(task, reason, state="unavailable" if "적용 대상" in reason or reason == "크기 제한 미적용" else "review")
                items.append(item)
                continue
            combined, predicted_combined, learned, fallback, disagreements = 0, 0, 0, 0, 0
            for values in rows:
                features = features_for(task, values)
                teacher = teacher_mask(task, values)
                predicted = predict_mask(model, task, features) if model else None
                combined |= teacher
                if predicted is not None:
                    predicted_combined |= predicted
                if predicted == teacher:
                    learned += 1
                else:
                    fallback += 1
                    disagreements += int(predicted is not None)
            actions, raw_actions = _actions(task, combined), _actions(task, predicted_combined)
            issue = bool(actions)
            # No learned result may clear an already observed rule candidate.
            unexplained_candidate = finding.get("status") == "attention" and not issue
            state = "confirmed" if issue else "review" if not complete or unexplained_candidate else "clear"
            if unexplained_candidate:
                complete = False
                reason = "기존 검토의 후보와 입력 측정값을 다시 확인하세요"
            title = (f"{LABELS[task]} · 개선 {len(actions)}가지" if len(actions) > 1 else ACTION_TEXT[actions[0]][0]) if actions else f"{LABELS[task]} · 수정 후보 없음" if state == "clear" else f"{LABELS[task]} · 추가 확인"
            action = " ".join(ACTION_TEXT[a][1] for a in actions) if actions else "다른 검토 항목을 확인하세요" if state == "clear" else reason
            if task == "wall" and issue:
                action = f"표시된 벽을 기준 {rows[0]['limit_mm']:,.4g} mm까지 보강하고 다시 검토하세요."
            if task == "cavities" and issue and process == "MEX":
                action = "밀폐 기능을 유지하며 내부 천장 경사 또는 분할 구조를 비교하세요."
            recommendations = [dict(id=a, title=ACTION_TEXT[a][0], action=ACTION_TEXT[a][1]) for a in actions]
            if len(actions) == 1:
                recommendations[0]["action"] = action
            prediction_complete = model is not None and learned + disagreements == len(rows)
            item.update(state=state, origin="learned_verified" if fallback == 0 else "rule_fallback",
                        predicted_issue=(bool(predicted_combined) if prediction_complete or predicted_combined else None),
                        action_id=actions[0] if actions else None, action_ids=actions, model_action_ids=raw_actions,
                        title=title, action=action, evidence=evidence, agreement=(disagreements == 0 if model and fallback == disagreements else None),
                        scope="측정 범위" if complete else "일부 측정 범위", reason=model_error or ("예측과 규칙 차이를 재계산으로 보완" if disagreements else
                            "학습 범위 밖 측정을 규칙 계산으로 확인" if fallback else reason if not complete else ""),
                        evaluated_rows=len(rows), learned_rows=learned, fallback_rows=fallback,
                        disagreement_rows=disagreements, complete=complete, prediction_complete=prediction_complete,
                        recommendations=recommendations)
        except (ValueError, TypeError, KeyError, ZeroDivisionError, OverflowError):
            item = _empty_item(task, "필요한 치수·조건의 누락 또는 범위를 확인하세요")
        items.append(item)
    summary = {state: sum(item["state"] == state for item in items) for state in ("confirmed", "clear", "review", "unavailable")}
    summary.update({origin: sum(item["origin"] == origin for item in items) for origin in ("learned_verified", "rule_fallback")})
    metadata = ({"id": model["id"], "algorithm": model["algorithm"], "sha256": model["artifact_sha256"],
                 "teacher_sha256": model["teacher_sources"], "training_rows": model["training_rows"],
                 "validation": model["validation"]} if model else {"id": None, "reason": model_error})
    return dict(schema_version="dfm-learned-review-1", status="unavailable" if model is None or not items else "partial" if summary["review"] or summary["rule_fallback"] else "ready",
                model=metadata, items=items, summary=summary,
                note="내장 지도학습 모델의 개선 후보를 현재 측정값·입력 기준으로 재확인합니다.")
