"""Stable, disclosed geometric direction recommendation, not process validation.

Equal or user-prioritized weighting of normalized geometry is a product decision
policy, not an empirical manufacturing model. The fixed search alone defines normalization;
adding the current custom direction cannot change its winner. Physical properties,
time, support volume, or success probabilities are never inferred from the score.
"""
from __future__ import annotations

from copy import deepcopy
import math

from .orientation import DIRECTIONS
from .profiles import UNASSESSED


POLICY_VERSION = "preference-geometric-regret/2"
_FIELDS = {
    "height_mm": ("빌드 높이", "mm", "min"),
    "overhang_projected_area_sum_mm2": ("하향면 후보의 투영면적 합", "mm²", "min"),
    "contact_triangle_area_mm2": ("평평한 바닥 면적", "mm²", "max"),
}
_PROCESS_FIELDS = {
    "MEX": ("overhang_projected_area_sum_mm2", "height_mm", "contact_triangle_area_mm2"),
    "VPP": ("overhang_projected_area_sum_mm2", "height_mm"),
    "PBF_METAL": ("overhang_projected_area_sum_mm2", "height_mm"),
    "PBF_POLYMER": ("height_mm",),
}
_TIE_TOLERANCE = 1e-10  # Dimensionless numerical comparison, not process tolerance.
_PRIORITY_MULTIPLIER = 3.  # Disclosed preference policy, not experimental calibration.
_PRIORITY_FIELDS = {
    "support": "overhang_projected_area_sum_mm2",
    "height": "height_mm",
    "contact": "contact_triangle_area_mm2",
}
_PRIORITY_LABELS = {
    "balanced": "종합 균형", "support": "서포트 줄이기", "height": "높이 낮추기",
    "contact": "평평한 바닥 넓히기", "strength": "강도", "surface": "표면 품질",
    "accuracy": "치수 정확도", "cost": "비용", "tool_access": "공구 접근성",
}


def _priority_policy(report, fields):
    """Map an explicit user preference only to already available geometry.

    Unrecognized or unsupported preferences use the unchanged balanced policy
    with a visible explanation. Physical objectives are never assigned a proxy
    silently (for example height is not substituted for cost or strength).
    """
    context = report.get("review_context")
    if context is None:
        raw = "balanced"
    elif isinstance(context, dict):
        raw = context.get("priority", "balanced")
    else:
        raw = None
    requested = raw if isinstance(raw, str) else None
    target = _PRIORITY_FIELDS.get(requested)
    supported = requested == "balanced" or (target is not None and target in fields)
    effective = requested if supported else "balanced"
    weights = {field: _PRIORITY_MULTIPLIER if field == target and supported else 1. for field in fields}
    total = sum(weights.values())
    weights = {field: value/total for field, value in weights.items()}
    if requested == "balanced":
        note = "계산 가능한 기하 지표를 같은 비중으로 비교하는 기본 정책입니다."
    elif supported:
        if len(fields) == 1:
            note = "현재 공정에서 방향별로 비교하는 지표는 높이 하나이므로, 높이 우선과 기본 높이 비교의 순위가 같습니다."
        else:
            note = (f"선택한 「{_PRIORITY_LABELS[requested]}」를 반영해 「{_FIELDS[target][0]}」의 비중을 "
                    "다른 지표의 3배로 두고 전체 비중을 정규화했습니다. 이는 개발자가 정한 선호 반영 정책이며 물리적 최적이나 성공 확률이 아닙니다.")
    elif requested in _PRIORITY_LABELS:
        note = (f"선택한 「{_PRIORITY_LABELS[requested]}」는 이 공정의 방향 비교 지표로 판단할 수 없어 "
                "종합 균형 정책을 유지합니다. 이 결과가 해당 요구를 만족한다고 판단한 것은 아닙니다.")
    else:
        note = "알 수 없거나 형식이 올바르지 않은 우선순위여서 종합 균형 정책을 유지합니다. 우선순위 입력을 확인하세요."
    return weights, dict(requested_priority=requested, effective_priority=effective,
                         priority_supported=supported, priority_note=note,
                         priority_multiplier=_PRIORITY_MULTIPLIER if supported and target else 1.,
                         weighting="priority" if supported and target else "equal")


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _stable_key(row):
    """Tie representative never depends on the current direction or row order."""
    name = str(row.get("name", ""))
    base = list(DIRECTIONS)
    return (base.index(name) if name in base else len(base), name, tuple(row.get("direction", ())))


def _search_row(row):
    # Explicit role is authoritative. Old saved reports have the historical name.
    return row.get("candidate_role", "current_only" if row.get("name") == "현재 지정 방향" else "search") == "search"


def _near(a, b):
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-8)


def _current_comparison(current, recommended, criteria, best_score, space_required):
    if not current or (space_required and current.get("build_fit") is not True):
        return dict(status="unavailable", is_equivalent=False, is_better=False, keep_current=False,
                    differences=[])
    differences = []
    for criterion in criteria:
        field = criterion["field"]
        if not _number(current.get(field)):
            return dict(status="unavailable", is_equivalent=False, is_better=False, keep_current=False,
                        differences=[])
        old, new = current[field], recommended[field]
        signed = (new-old) * (-1 if criterion["direction"] == "max" else 1)
        differences.append(dict(field=field, label=criterion["label"], unit=criterion["unit"],
                                current=old, recommended=new, delta=new-old,
                                change="same" if _near(old, new) else "improvement" if signed < 0 else "tradeoff"))
    changes = {x["change"] for x in differences}
    equivalent = changes == {"same"}
    better = "tradeoff" in changes and "improvement" not in changes
    # Distinct trade-offs may have an equal policy score. Do not force a switch.
    comparable = True
    current_score = 0.
    for criterion in criteria:
        value = current[criterion["field"]]
        low, high = criterion["minimum"], criterion["maximum"]
        if criterion["constant"]:
            comparable = comparable and _near(value, low)
            continue
        regret = (value-low)/(high-low) if criterion["direction"] == "min" else (high-value)/(high-low)
        current_score += criterion["weight"] * regret
    policy_equal_or_better = comparable and current_score <= best_score + _TIE_TOLERANCE
    return dict(status="equivalent" if equivalent else "current_better" if better else
                "no_policy_improvement" if policy_equal_or_better else "candidate_improves",
                is_equivalent=equivalent or (comparable and abs(current_score-best_score) <= _TIE_TOLERANCE),
                is_better=better or (comparable and current_score < best_score-_TIE_TOLERANCE),
                keep_current=equivalent or better or policy_equal_or_better,
                differences=differences)


def recommend_orientation(report):
    """Return one deterministic representative and an actionable current comparison.

    ``recommended`` always comes from the fixed search set. ``keep_current`` can
    be true for a tied/better current custom direction without moving that fixed
    representative. Incomplete required measurements block the combined ranking:
    incomparable candidate coverage is never silently normalized into a winner.
    """
    profile = report.get("profile", {})
    process = profile.get("process")
    fields = _PROCESS_FIELDS.get(process, ())
    weights, priority_policy = _priority_policy(report, fields)
    space_required = profile.get("build_volume_mm") is not None
    assumed_scale = report.get("model", {}).get("unit_status") == "assumed"
    rows = [deepcopy(r) for r in report.get("orientations", []) if _search_row(r)]
    result = dict(status="unavailable", title="방향 비교 결과가 필요합니다", observation="", next_action="설계 검토를 실행하세요.",
                  recommended=None, alternatives=[], ranking=[], criteria=[], missing_criteria=[],
                  candidate_count=len(rows), eligible_count=0, excluded_count=0, incomplete_candidates=[],
                  policy=dict(version=POLICY_VERSION, **priority_policy, score_meaning="relative geometric regret; lower is preferred; not a probability",
                              candidate_scope="fixed search candidates only; current-only direction excluded",
                              normalization="min-max within complete, space-eligible fixed candidates; span <= 64 floating-point ULP of maximum contributes zero",
                              tie_break="+Z, -Z, +X, -X, +Y, -Y, then stable candidate name and direction",
                              basis="개발자가 정한 후보 선택 정책이며 표준·제조 실험에서 보정한 가중치가 아닙니다."),
                  limitations=["유한한 후보에서 계산한 기하량을 비교합니다. 연속 공간의 제조 최적 방향·출력 성공·시간·강도 판정은 아닙니다.",
                               "하향면 투영면적 합은 서포트 양이 아니며, 바닥 면적은 접착력을 뜻하지 않습니다.",
                               "빌드 평면의 추가 회전은 0°·90°만 비교합니다."] + list(UNASSESSED.get(process, [])),
                  current_is_equivalent=False, current_is_better=False, keep_current=False,
                  current_comparison={"status": "unavailable", "differences": []},
                  action="review", all_tied=False, assumed_scale=assumed_scale)
    if not priority_policy["priority_supported"]:
        result["limitations"].insert(0, priority_policy["priority_note"])
    if assumed_scale:
        result["limitations"].insert(0, "입력 파일의 실제 치수는 미확정입니다. 선택한 단위를 가정한 형상 비교이며, 공간 적합과 절대 길이·면적은 치수 확인 뒤 확정하세요.")
    if not fields:
        result.update(title="지원하는 적층 공정을 선택하세요", next_action="적층 공정을 선택하고 다시 검토하세요.")
        return result
    if not rows:
        return result
    eligible = []
    for row in rows:
        if row.get("build_fit") is False:
            result["excluded_count"] += 1
            continue
        missing = [field for field in fields if not _number(row.get(field))]
        if space_required and row.get("build_fit") is not True:
            missing.append("build_fit")
        if missing:
            result["incomplete_candidates"].append(dict(name=row.get("name"), fields=missing))
        else:
            eligible.append(row)
    result["eligible_count"] = len(eligible)
    if result["incomplete_candidates"]:
        result["missing_criteria"] = sorted({f for row in result["incomplete_candidates"] for f in row["fields"]})
        result.update(title="측정이 미확정인 항목이 있어 종합 추천을 보류합니다",
                      observation="미확정 값을 좋은 값으로 간주하지 않았습니다. 방향별 같은 항목이 모두 계산되어야 비교할 수 있습니다.",
                      next_action="입력 형상의 닫힘·면 방향과 검사 메시지를 확인한 뒤 다시 검토하세요.")
        return result
    if not eligible:
        if space_required and report.get("current_orientation", {}).get("build_fit") is True:
            # An arbitrary user angle may fit even when every fixed search
            # direction fails. Do not turn a finite-search failure into advice
            # to split a part that already has a fitting measured placement.
            result.update(status="current_only_fit", title="현재 방향을 유지하세요 · 입력 공간에 들어갑니다",
                          observation="고정 탐색 후보는 모두 공간을 초과하지만, 사용자가 지정한 현재 방향은 입력한 공간에 들어갑니다. 현재 각도를 자동 후보의 실패 때문에 바꿀 필요는 없습니다.",
                          next_action="현재 방향으로 형상 검토를 이어가세요. 공간에 들어간다는 사실과 실제 출력 가능 여부는 구분합니다.",
                          action="keep", keep_current=True,
                          current_comparison=dict(status="current_only_fit", is_equivalent=False, is_better=False,
                                                  keep_current=True, differences=[]))
            return result
        result.update(status="no_fit", title="검토한 후보 중 입력 공간에 들어가는 방향이 없습니다",
                      observation="이번에 비교한 후보에서는 입력 공간을 만족하는 방향을 찾지 못했습니다. 탐색하지 않은 모든 각도까지 불가능하다는 뜻은 아닙니다.",
                      next_action="장비 공간·여유와 형상 치수를 확인하거나 부품 분할·다른 장비를 검토하세요.")
        return result
    material_warnings = any(f.get("id") in ("assembly", "shells", "surface_input") and f.get("status") == "attention"
                            for f in report.get("findings", []))
    if report.get("summary", {}).get("review_status") == "partial_geometry" or material_warnings:
        result.update(title="입력 형상을 먼저 확인해야 합니다", observation="신뢰할 수 있는 재료 형상으로 확정되지 않아 종합 방향 추천을 보류합니다.",
                      next_action="형상 진단에 표시된 닫힘·면 방향을 확인하고, 여러 부품이면 검토할 단일 솔리드를 선택하세요.")
        return result
    for field in fields:
        label, unit, direction = _FIELDS[field]
        values = [r[field] for r in eligible]
        low, high = min(values), max(values)
        # Do not amplify last-bit round-off on equal geometry into a full-scale
        # preference. This is floating-point precision, not a millimetre tolerance.
        constant = high-low <= 64*math.ulp(float(high))
        result["criteria"].append(dict(field=field, label=label, unit=unit, direction=direction,
                                       weight=weights[field], minimum=low, maximum=high, constant=constant))
    for row in eligible:
        contributions = {}
        for criterion in result["criteria"]:
            field, low, high = criterion["field"], criterion["minimum"], criterion["maximum"]
            regret = 0. if criterion["constant"] else ((row[field]-low)/(high-low) if criterion["direction"] == "min" else (high-row[field])/(high-low))
            contributions[field] = regret * criterion["weight"]
        row["policy_score"] = sum(contributions.values())
        row["policy_contributions"] = contributions
    minimum = min(r["policy_score"] for r in eligible)
    ties = sorted([r for r in eligible if abs(r["policy_score"]-minimum) <= _TIE_TOLERANCE], key=_stable_key)
    others = sorted([r for r in eligible if r not in ties], key=lambda r: (r["policy_score"], _stable_key(r)))
    result.update(status="limited" if process == "PBF_POLYMER" or assumed_scale else "recommended", recommended=ties[0],
                  alternatives=ties[1:], ranking=ties+others, all_tied=len(ties) == len(eligible))
    recommended = result["recommended"]
    comparison = _current_comparison(report.get("current_orientation"), recommended, result["criteria"], minimum, space_required)
    result.update(current_comparison=comparison, current_is_equivalent=comparison["is_equivalent"],
                  current_is_better=comparison["is_better"], keep_current=comparison["keep_current"])
    labels = "·".join(c["label"] for c in result["criteria"])
    weighting_text = "같은 비중으로" if priority_policy["weighting"] == "equal" else "선택한 우선순위의 비중으로"
    result["observation"] = f"공간 조건을 만족한 {len(eligible)}개 후보에서 {labels}의 상대 차이를 {weighting_text} 종합했습니다."
    if not space_required:
        result["observation"] = result["observation"].replace("공간 조건을 만족한", "크기 제한 없이 비교한")
    if process == "PBF_POLYMER":
        result["observation"] = f"고분자 PBF에서는 현재 비교 가능한 지표인 높이만으로 {len(eligible)}개 후보를 정렬했습니다. 열변형·패킹·분말 배출까지 종합한 추천은 아닙니다."
    if priority_policy["requested_priority"] != "balanced":
        result["observation"] += " " + priority_policy["priority_note"]
    if assumed_scale:
        result["observation"] = "선택한 단위를 실제 크기라고 가정한 결과입니다. " + result["observation"]
    if result["keep_current"]:
        result.update(title="현재 방향을 유지하세요", action="keep",
                      next_action="비교한 지표에서 추천 후보로 바꿀 이점이 없습니다. 현재 방향을 유지하고, 남은 조치가 없으면 보고서를 저장하세요.")
    else:
        result.update(title=f"먼저 적용할 추천 방향: {recommended['name']}", action="apply",
                      next_action=f"{recommended['name']} 방향을 적용하고 자동으로 다시 검토한 문제 위치를 확인하세요.")
    return result
