"""Plain-language presentation of section measurements, without new DFM rules.

Completion describes computation coverage. The volume difference is a numerical
cross-check of the same mesh and has no pass/fail threshold in this module.
Row indices returned here are positions in ``detail['rows']`` for UI selection.
"""
from __future__ import annotations

from decimal import Decimal
import math
from numbers import Real


_NEXT_STEPS = {
    "MEX": "두 단면의 차이가 의도한 형상인지 먼저 확인하세요. 가는 부분이나 돌출부가 있다면 MEX 층간 검토와 실제 슬라이서에서 경로·서포트를 확인하세요.",
    "VPP": "두 단면의 차이가 의도한 형상인지 먼저 확인하세요. 필요한 경우 방향별 단면과 서포트 접촉 위치를 비교하고, 장비·수지 조건에 맞춰 배출 경로를 확인하세요.",
    "PBF_POLYMER": "두 단면의 재료 분포가 설계 의도에 맞는지 먼저 확인하세요. 내부 공간이 있다면 CAD에서 분말 배출 경로를 확인하세요.",
    "PBF_METAL": "두 단면의 차이가 의도한 형상인지 먼저 확인하세요. 서포트 검토가 필요한 하향면이 있다면 방향별 배치와 서포트 접촉 위치를 비교하세요.",
}


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _count(value):
    number = _finite(value)
    return int(number) if number is not None and number >= 0 and number.is_integer() else None


def _number(value, places=3):
    """Human formatting only; never suppress a positive measurement as zero."""
    if value == 0:
        return "0"
    minimum = 10.0 ** -places
    if 0 < abs(value) < minimum:
        return ("−" if value < 0 else "") + "<" + f"{minimum:.{places}f}"
    return f"{value:,.{places}f}".rstrip("0").rstrip(".")


def _height_pair(before, after):
    left, right = _number(before), _number(after)
    if left == right:
        # Closely spaced valid samples must not appear to have identical heights.
        left, right = (format(Decimal(str(value)), "f") for value in (before, after))
    return left, right


def _adjacent(before, after):
    """Do not reconnect missing rows or skipped event intervals for a headline."""
    if before.get("complete") is not True or after.get("complete") is not True:
        return False
    for key, permitted in (("index", (1,)), ("interval_index", (0, 1))):
        left, right = before.get(key), after.get(key)
        if left is None and right is None:
            continue
        left, right = _count(left), _count(right)
        if left is None or right is None or right-left not in permitted:
            return False
    z_before, z_after = _finite(before.get("z_mm")), _finite(after.get("z_mm"))
    return z_before is not None and z_after is not None and z_before < z_after


def _volume_summary(detail, status, mesh_volume_mm3):
    volume = dict(available=False, relative_difference_percent=None, display="확인 불가",
                  section_volume_mm3=None, mesh_volume_mm3=None, explanation="")
    if status != "complete":
        volume["explanation"] = "전체 단면 계산이 완료되지 않아 전체 체적을 비교하지 않았습니다."
        return volume
    method = detail.get("method", "")
    if detail.get("sampling_method") == "vertex_events_gauss2" or method.startswith("vertex_event"):
        section = _finite(detail.get("volume_quadrature_estimate_mm3"))
    elif method.startswith("uniform_midpoint"):
        section = _finite(detail.get("volume_midpoint_estimate_mm3"))
    else:
        section = _finite(detail.get("volume_quadrature_estimate_mm3"))
        if section is None:
            section = _finite(detail.get("volume_midpoint_estimate_mm3"))
    mesh = _finite(mesh_volume_mm3)
    if section is None or section < 0 or mesh is None or mesh <= 0:
        volume["explanation"] = "비교 가능한 단면 체적과 양의 메시 체적이 모두 필요합니다."
        return volume
    percent = abs(section-mesh)/mesh*100
    if not math.isfinite(percent):
        volume["explanation"] = "체적 상대차가 유한한 수로 계산되지 않았습니다."
        return volume
    display = "0%" if percent == 0 else "<0.0001%" if percent < 0.0001 else _number(percent, 4)+"%"
    volume.update(available=True, relative_difference_percent=percent, display=display,
                  section_volume_mm3=section, mesh_volume_mm3=mesh,
                  explanation="같은 메시의 체적을 두 방법으로 계산해 비교한 값입니다. 제조 적합성이나 실제 치수 정확도의 합격 기준은 아닙니다.")
    return volume


def summarize_sections(detail, process, mesh_volume_mm3=None):
    """Return novice-facing text and a valid sample pair, without mutating inputs.

    Largest change means only the largest supplied positive symmetric difference
    between immediately adjacent completed samples. No interpolation, global
    maximum claim, manufacturing verdict or heuristic accuracy threshold is used.
    """
    rows = detail.get("rows") or []
    completed = sum(row.get("complete") is True for row in rows)
    requested = _count(detail.get("requested_samples"))
    reported_completed = _count(detail.get("complete_samples"))
    reported_examined = _count(detail.get("examined_samples"))
    declared_status = detail.get("status", "unknown")
    counts_match = (requested is not None and requested > 0 and completed == len(rows) == requested
                    and reported_completed == completed and reported_examined == len(rows))
    intervals = detail.get("intervals") or []
    intervals_complete = not intervals or all(item.get("complete") is True for item in intervals)
    if declared_status == "complete" and counts_match and intervals_complete:
        status, title, level = "complete", "단면 계산 완료", "info"
    elif declared_status == "partial" or (declared_status == "complete" and completed):
        status, title, level = "partial", "일부 단면을 확인하지 못했습니다", "warning"
    else:
        status, title, level = "unknown", "단면 결과를 확정하지 못했습니다", "warning"
    count_text = (f"요청한 {requested:,}개 중 {completed:,}개 계산 완료" if requested is not None
                  else f"{completed:,}개 계산 완료 · 요청 수 미확정")
    completion_text = count_text+". 완료는 단면 계산 상태를 뜻합니다."
    reason = detail.get("reason") or ""
    if declared_status == "complete" and status != "complete" and not reason:
        reason = "완료 표시와 단면 수 또는 구간 상태가 일치하지 않아 전체 완료로 표시하지 않았습니다."

    pairs = []
    for index in range(1, len(rows)):
        before, after = rows[index-1], rows[index]
        change = _finite(after.get("symmetric_change_from_previous_mm2"))
        areas = [_finite(row.get("area_mm2")) for row in (before, after)]
        if (not _adjacent(before, after) or change is None or change < 0
                or any(area is None or area < 0 for area in areas)):
            continue
        pairs.append(dict(previous_row_index=index-1, row_index=index,
                          z_before_mm=float(before["z_mm"]), z_after_mm=float(after["z_mm"]),
                          area_before_mm2=areas[0], area_after_mm2=areas[1],
                          symmetric_change_mm2=change))
    changed = [pair for pair in pairs if pair["symmetric_change_mm2"] > 0]
    change = max(changed, key=lambda pair: pair["symmetric_change_mm2"]) if changed else None
    if change is not None:
        left, right = _height_pair(change["z_before_mm"], change["z_after_mm"])
        change_text = (
            f"검토한 표본에서 변화 면적이 가장 큰 인접 단면: 높이 {left} → {right} mm. "
            f"단면적 {_number(change['area_before_mm2'])} → {_number(change['area_after_mm2'])} mm², "
            f"서로 겹치지 않는 면적 {_number(change['symmetric_change_mm2'])} mm²입니다."
        )
        change["text"] = change_text
        default_row_index = change["row_index"]
    else:
        change_text = ("확인한 단면 사이에서 변화가 관측되지 않았습니다."
                       if pairs else "비교 가능한 인접 단면 쌍이 없습니다.")
        default_row_index = next((i for i, row in enumerate(rows) if row.get("complete") is True), None)

    next_step = _NEXT_STEPS.get(process, "선택한 단면의 윤곽을 확인하고, 사용할 공정과 장비·재료의 설계 기준을 정하세요.")
    if not pairs:
        next_step = ("미확정 이유와 계산 한도를 먼저 확인하세요. 가능한 단면 윤곽을 확인한 뒤, "
                     "입력 형상 또는 단면 배치 방법을 조정해 다시 검토하세요.")
    elif status != "complete":
        next_step = "미확정 이유와 빠진 검토 범위를 먼저 확인하세요. " + next_step
    return dict(status=status, completion_title=title, completion_text=completion_text,
                completion_level=level, reason=reason,
                interpretation="제작해도 되는지: 이 단면 결과만으로 결정할 수 없습니다.",
                next_step=next_step, default_row_index=default_row_index,
                change=change, change_text=change_text,
                volume=_volume_summary(detail, status, mesh_volume_mm3))
