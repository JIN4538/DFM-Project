"""User intent as review context, never as an inferred manufacturing limit.

Matching is an explicit-name search over the checked condition library. A match
is a candidate to inspect, not equipment/material compatibility or validation.
All returned structures are independent, JSON-safe snapshots of their inputs.
"""
from __future__ import annotations

from copy import deepcopy
import json
import re
import unicodedata


PRIORITY_LABELS = {
    "balanced": "종합 균형", "support": "서포트 후보 줄이기", "height": "빌드 높이 낮추기",
    "contact": "평평한 바닥 확보", "strength": "강도 관련 형상 확인",
    "surface": "표면 관련 형상 확인", "accuracy": "치수 관련 항목 확인",
    "cost": "비용 관련 형상 확인", "tool_access": "공구 접근 확인",
}
PROCESSES = {"unknown", "MEX", "VPP", "PBF_POLYMER", "PBF_METAL", "CNC"}
_UNKNOWN_NAMES = {"", "미확정", "미정", "모름", "알 수 없음", "unknown", "unspecified", "not specified"}
_PRIORITY_IDS = {
    "balanced": (), "support": ("overhang", "layers"), "height": ("build",),
    "contact": ("contact",), "strength": ("wall",),
    "surface": ("sections", "overhang", "cnc_curved_corners"),
    "accuracy": ("cad_holes", "wall", "cnc_holes", "cnc_curved_corners"),
    "cost": ("overhang", "layers", "build"),
    "tool_access": ("cnc_visibility", "cnc_holes", "cnc_rectangular_pockets", "cnc_curved_corners", "cavities"),
}


def _text(value, field):
    if not isinstance(value, str):
        raise ValueError(f"{field}: 문자열이 필요합니다.")
    return value.strip()


def _process(value):
    value = _text(value, "process")
    value = "unknown" if value.casefold() == "unknown" else value.upper()
    if value not in PROCESSES:
        raise ValueError("지원 범위의 공정이 아닙니다.")
    return value


def _priority(value):
    value = _text(value, "priority").lower()
    if value not in PRIORITY_LABELS:
        raise ValueError("지원하는 검토 목적을 선택하세요.")
    return value


def review_context(intent, *, mode="manual", provenance=None):
    """Return an independent serializable snapshot; do not mutate/apply intent.

    Provenance is deliberately restricted because this context can be exported.
    Unknown provenance keys (including credentials and raw provider payloads)
    are discarded. Name/notes fields remain user text, never executable rules.
    """
    if not isinstance(intent, dict):
        raise ValueError("검토 요청은 객체여야 합니다.")
    mode = _text(mode, "mode")
    if not mode:
        raise ValueError("입력 방식을 기록해야 합니다.")
    notes = intent.get("notes", [])
    if not isinstance(notes, list) or not all(isinstance(note, str) for note in notes):
        raise ValueError("notes: 문자열 목록이 필요합니다.")
    clean_provenance = {}
    if provenance is not None:
        if not isinstance(provenance, dict):
            raise ValueError("provenance: 객체가 필요합니다.")
        for key in ("provider", "model", "response_id"):
            if key not in provenance or provenance[key] is None:
                continue
            value = _text(provenance[key], key)
            if len(value) > 200 or re.search(r"(?i)(?:\bbearer\s+|\bsk-[a-z0-9_-]{8,}|api[_ -]?key\s*[:=])", value):
                raise ValueError("출처 식별자에 인증 정보나 긴 원문을 기록할 수 없습니다.")
            if value:
                clean_provenance[key] = value
    result = dict(schema_version=1, priority=_priority(intent.get("priority", "balanced")),
                  equipment=_text(intent.get("equipment", ""), "equipment"),
                  material=_text(intent.get("material", ""), "material"),
                  process=_process(intent.get("process", "unknown")),
                  notes=[note.strip() for note in notes if note.strip()], mode=mode,
                  provenance=clean_provenance)
    return json.loads(json.dumps(result, ensure_ascii=False, allow_nan=False))


def _tokens(value, *, joined=True):
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    if value in _UNKNOWN_NAMES:
        return set()
    # Formatting-only equivalence: VF-2 == VF2; Form 4 == Form4; M 290 == M290.
    # Model suffixes remain intact: MK4 is not MK4S, and VF2 is not VF2SS.
    if joined:
        value = re.sub(r"([a-z])[-_\s]+(?=\d)", r"\1", value)
    return set(re.findall(r"[a-z0-9]+|[가-힣]+", value))


def _name_match(query, value):
    # Retain the unjoined representation too: in 'Hydro 6061' the number is
    # a material grade, whereas 'Form 4' is a model spelling. No grade/model
    # alias is guessed from that distinction.
    available = _tokens(value) | _tokens(value, joined=False)
    return any(tokens and tokens <= available
               for tokens in (_tokens(query), _tokens(query, joined=False)))


def profile_candidates(intent, library, process):
    """Find named conditions to inspect; no numerical inference or auto apply.

    An explicit equipment query must match all its name tokens. A material-only
    record can still be offered when its equipment is unspecified, with that
    limitation exposed. Machine matches with material mismatches rank last.
    Notes and priority never supply machine aliases or numeric parameters.
    """
    context = review_context(intent)
    process = _process(process)
    if process == "unknown":
        process = context["process"]
    if process == "unknown" or context["process"] not in ("unknown", process):
        return []
    equipment, material = _tokens(context["equipment"]), _tokens(context["material"])
    if not equipment and not material:
        return []
    candidates = []
    for profile in library.profiles_for(process):
        machine_tokens = _tokens(profile.get("machine", ""))
        material_tokens = _tokens(profile.get("material", ""))
        machine_match = bool(equipment and _name_match(context["equipment"], profile.get("machine", "")))
        tool_match = bool(equipment and profile.get("category") == "tool"
                          and _name_match(context["equipment"], profile["label"]))
        equipment_match = machine_match or tool_match
        material_match = bool(material and _name_match(context["material"], profile.get("material", "")))
        material_status = ("not_requested" if not material else "unspecified" if not material_tokens else
                           "name_match" if material_match else "mismatch")
        if equipment_match:
            rank = 0 if material_match else 1 if not material else 2 if not material_tokens else 5
            match_type = "tool_name" if tool_match else "equipment_name"
        elif material_match and (not equipment or not machine_tokens):
            rank = 3 if not equipment else 4
            match_type = "material_name"
        else:
            continue
        reasons = []
        if equipment_match:
            reasons.append(("공구명" if tool_match else "장비명") + "의 입력 문자열과 일치하는 자료입니다.")
        else:
            reasons.append("재료명의 입력 문자열과 일치하는 자료입니다.")
        if material_status == "mismatch":
            reasons.append(f"재료 불일치: 요청 ‘{context['material']}’, 자료 ‘{profile.get('material', '')}’. 해당 재료 조건을 그대로 적용하지 마세요.")
        elif material_status == "unspecified":
            reasons.append("이 자료에는 요청 재료의 적용 조건이 지정되어 있지 않습니다.")
        elif material_status == "name_match":
            reasons.append("재료 이름이 검색 조건에 맞지만 등급·상태·장비 조합의 적합성은 별도 확인해야 합니다.")
        if equipment and not equipment_match:
            reasons.append("요청한 장비의 조건이 없는 재료 자료입니다.")
        elif not equipment:
            reasons.append("장비는 지정되지 않았으므로 자료의 대상 장비를 확인하세요.")
        if tool_match:
            reasons.append("공구명 검색 결과이며 장착 장비·재료 적합성을 판정한 결과가 아닙니다.")
        reasons.append("목록을 고른 것만으로 수치나 기준을 적용하지 않습니다. 모델 세부판·재료·출처 조건을 확인하세요.")
        candidates.append((rank, dict(identifier=profile["id"], title=profile["label"],
                                     explanation=" ".join(reasons), process=process,
                                     match_type=match_type, material_status=material_status)))
    return [row for _, row in sorted(candidates, key=lambda pair: (pair[0], pair[1]["title"], pair[1]["identifier"]))]


def priority_effect(process, priority):
    """Describe the actual process-specific ranking and action-list effects."""
    process, priority = _process(process), _priority(priority)
    if process == "unknown":
        return f"‘{PRIORITY_LABELS[priority]}’ 요구를 기록합니다. 공정을 선택하면 적용 가능한 비교 방식을 안내하며, 물리 성능·비용은 계산하지 않습니다."
    if process == "CNC" and priority in ("support", "height", "contact"):
        return "이 적층 목표는 절삭 검토에 적용하지 않습니다. 공구·형상의 관측 문제와 미확인 항목 순서를 유지합니다."
    if process == "PBF_POLYMER" and priority in ("support", "contact"):
        return "고분자 PBF에는 서포트·바닥 접착 목표를 적용하지 않습니다. 방향은 기존처럼 높이만 비교하며 열변형·분말 배출은 미검토입니다."
    if process in ("VPP", "PBF_METAL") and priority == "contact":
        return "이 공정에는 바닥 면적 우선 목표를 적용하지 않습니다. 방향은 하향면 후보와 높이를 같은 비중으로 비교하며 부착 성능은 계산하지 않습니다."
    if process == "CNC":
        return {
            "balanced": "공구·형상에서 관측된 문제를 먼저, 필요한 조건과 미확인 계산을 그다음에 보여줍니다. 절삭 방향의 종합 순위는 계산하지 않습니다.",
            "strength": "강도 요구를 기록하고 기존 조치 순서를 유지합니다. 절삭력·공구 처짐·강성은 계산하지 않습니다.",
            "surface": "오목면·공구 반경 비교 조치를 먼저 보여줍니다. 표면 거칠기나 표면 품질은 예측하지 않습니다.",
            "accuracy": "원통·공구 반경 등 치수 비교 조치를 먼저 보여줍니다. 제조 오차나 공차 만족을 예측하지 않습니다.",
            "cost": "비용 요구를 기록하고 기존 조치 순서를 유지합니다. 가공 시간·견적·공정 비용은 계산하지 않습니다.",
            "tool_access": "표면 가림·원통·포켓의 접근 관련 조치를 먼저 보여줍니다. 유한 공구·홀더의 전체 경로 충돌은 CAM에서 별도 확인해야 합니다.",
        }[priority]
    if priority == "balanced":
        criteria = ("높이만" if process == "PBF_POLYMER" else
                    "하향면 후보·높이·평평한 바닥 면적을 같은 비중으로" if process == "MEX" else
                    "하향면 후보·높이를 같은 비중으로")
        return f"방향은 {criteria} 비교합니다. 관측된 문제를 먼저 보여주며 이 순위는 물리적 최적이나 제조 성공 확률이 아닙니다."
    if priority in ("support", "height", "contact"):
        if process == "PBF_POLYMER":
            return "현재 고분자 PBF의 방향 지표는 높이 하나이므로 기본 비교와 순위가 같습니다. 실제 출력 시간은 계산하지 않습니다."
        target = {"support": "하향면 후보 면적", "height": "빌드 높이", "contact": "평평한 바닥 면적"}[priority]
        limit = {"support": "실제 서포트 양", "height": "실제 출력 시간", "contact": "실제 접착력"}[priority]
        return f"방향 비교에서 {target}의 비중을 다른 지표의 3배로 둡니다. 개발자가 정한 선호 반영 방식이며 {limit}을 계산하지 않습니다."
    effect = {
        "strength": "벽 관련 조치를 먼저 보여줍니다. 하중·강도·안전율 해석이나 최적 강도 방향 계산은 수행하지 않습니다.",
        "surface": ("단면 관련 조치를 먼저 보여줍니다. 표면 거칠기나 품질은 예측하지 않습니다." if process == "PBF_POLYMER" else
                    "단면·하향면 관련 조치를 먼저 보여줍니다. 표면 거칠기나 품질은 예측하지 않습니다."),
        "accuracy": "구멍·벽 치수 관련 조치를 먼저 보여줍니다. 제조 오차나 공차 만족을 예측하지 않습니다.",
        "cost": ("비용 요구를 기록하며 견적·실제 비용은 계산하지 않습니다." if process == "PBF_POLYMER" else
                 ("하향면·층간 지지 후보" if process == "MEX" else "하향면 후보") + " 관련 조치를 먼저 보여줍니다. 견적·실제 비용은 계산하지 않습니다."),
        "tool_access": "내부 형상 관련 조치를 먼저 보여줍니다. 후가공·제거 공구의 진입 경로는 계산하지 않습니다.",
    }[priority]
    return effect + " 방향 추천의 기본 기하 비교 비중은 유지합니다."


def context_summary(context, process):
    context = review_context(context, mode=context.get("mode", "manual"), provenance=context.get("provenance"))
    _process(process)
    names = f"장비 {context['equipment'] or '미확정'} · 재료 {context['material'] or '미확정'}"
    mode = "직접 입력" if context["mode"] == "manual" else "AI 요청 해석" if context["mode"] in ("ai", "llm") else context["mode"]
    return f"{names} · 중점: {PRIORITY_LABELS[context['priority']]} · 요청 입력: {mode}"


def prioritize_actions(actions, context):
    """Reorder only within decision classes; input/build constraints stay first."""
    context = review_context(context)
    preferred = _PRIORITY_IDS[context["priority"]]
    rows = deepcopy(list(actions))
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("조치 항목은 객체여야 합니다.")
    def order(pair):
        index, item = pair
        identifier = item.get("id")
        kind = item.get("action_kind")
        if kind is None:
            kind = "condition" if item.get("pending") is True or item.get("status") == "unknown" else "candidate"
        group = {"candidate": 1, "condition": 2, "calculation": 3}.get(kind, 3)
        if identifier in ("input", "cnc_input") and item.get("status") not in ("observed", "not_detected"):
            return (0, 0, 0, index)
        hard_constraint = 0 if identifier == "build" and group == 1 else 1
        preference = preferred.index(identifier) if group == 1 and identifier in preferred else len(preferred)
        return (group, hard_constraint, preference, index)
    return [row for _, row in sorted(enumerate(rows), key=order)]
