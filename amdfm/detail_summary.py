"""User decisions from measured detail results; no new manufacturing limits.

Success is deliberately scoped to the supplied wall samples or layer checks.
Unknown values, incomplete scopes and small positive candidates remain distinct.
The returned dictionaries are presentation data and never change the report.
"""
from __future__ import annotations

import math
from numbers import Real


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _number(value, *, positive=False):
    value = _finite(value)
    if value is None or value < 0 or (positive and value == 0):
        return None
    return value


def _count(value):
    value = _number(value)
    return int(value) if value is not None and value.is_integer() else None


def _display(value):
    # Significant figures preserve arbitrarily small positive measurements.
    return f"{value:,.4g}"


def summarize_wall(detail, minimum_wall_mm=None):
    """Explain a normal-chord sample result relative to a supplied criterion.

    A criterion can be supplied explicitly, or read from the result's stored
    measurements. It is a user criterion, never a universal process limit.
    """
    detail = detail or {}
    measurement = detail.get("measurements") or {}
    limit = _number(minimum_wall_mm if minimum_wall_mm is not None else
                    measurement.get("minimum_wall_mm"), positive=True)
    minimum = _number(measurement.get("minimum_mm"), positive=True)
    p05 = _number(measurement.get("area_weighted_p05_mm"), positive=True)
    requested = _count(measurement.get("requested_samples"))
    valid = _count(measurement.get("valid_samples"))
    missing = _count(measurement.get("missing_samples"))
    samples = measurement.get("samples") or []
    distances = [_number(row.get("normal_chord_mm"), positive=True) for row in samples]
    sample_consistent = (not samples or (len(samples) == valid
        and all(value is not None for value in distances)
        and minimum is not None and min(distances) == minimum))
    counts_match = (requested is not None and requested > 0 and valid == requested
                    and missing == 0 and sample_consistent)
    measurable = (detail.get("status") in ("measured", "partial")
                  and minimum is not None and valid is not None and valid > 0)
    complete = (measurable and detail.get("status") == "measured" and counts_match
                and (p05 is None or p05 >= minimum))
    below_faces = []
    below_count = None
    if limit is not None and measurable:
        if samples:
            below_samples = [row for row, distance in zip(samples, distances)
                             if distance is not None and distance < limit]
            below_faces = list(dict.fromkeys(row["source_face"] for row in below_samples
                                            if _count(row.get("source_face")) is not None))
            below_count = len(below_samples)
        elif limit == _number(measurement.get("minimum_wall_mm"), positive=True):
            below_faces = list(dict.fromkeys(measurement.get("below_limit_face_indices") or []))
            below_count = (len(below_faces) or None) if minimum < limit else 0
        elif minimum >= limit:
            below_count = 0
    result = dict(status="not_run", level="info", title="벽 검토를 실행해 얇은 위치를 확인하세요",
        observation="아직 벽의 법선 방향 거리를 측정하지 않았습니다.",
        next_action="'벽 검토 실행'을 누르세요. 측정 뒤 사용할 장비·재료의 최소 벽 기준과 비교합니다.",
        scope="면에서 안쪽으로 잰 거리 표본입니다. 평행한 벽에서는 두께로 해석할 수 있지만, 곡면·모서리의 거리와 전체 최소 벽두께는 다를 수 있습니다.",
        reason=detail.get("reason", ""), complete=complete, criterion_available=limit is not None,
        counts=dict(requested=requested, valid=valid, missing=missing, below_limit=below_count),
        minimum_mm=minimum if measurable else None, p05_mm=p05 if measurable else None,
        minimum_wall_mm=limit, below_limit_face_indices=below_faces,
        highlight_face_indices=below_faces or list(measurement.get("thinnest_face_indices") or []))
    if not detail:
        return result
    if detail.get("status") == "not_applicable":
        result.update(status="not_applicable", title="이 조건에는 벽 검토를 적용하지 않습니다",
                      observation=result["reason"] or "적용 대상이 아닌 검토입니다.",
                      next_action="현재 공정에 적용되는 다른 검토 항목을 확인하세요.")
        return result
    if not measurable:
        result.update(status="unknown", level="warning", title="벽을 측정하지 못했습니다",
                      observation=result["reason"] or "확인 가능한 거리 표본이 없습니다.",
                      next_action="입력 진단을 확인하고 단일 솔리드를 선택한 뒤 다시 실행하세요.")
        return result
    observation = f"유효 표본 {valid:,}개에서 가장 짧은 거리는 {_display(minimum)} mm입니다."
    if not complete:
        observation += (f" 요청한 {requested:,}개 중 일부 표본은 미확인입니다." if requested else
                        " 전체 요청 표본의 확인 여부를 확정하지 못했습니다.")
    result["observation"] = observation
    if limit is not None and minimum < limit:
        result.update(status="attention", level="warning", title="입력한 벽 기준보다 작은 구간이 있습니다",
            next_action=f"강조된 위치를 확인하세요. 기준 {_display(limit)} mm와 비교해 벽 보강·형상 수정을 검토하고, 곡면·모서리는 CAD에서 실제 두께를 확인하세요.")
    elif not complete:
        result.update(status="partial", level="warning", title="벽의 일부 표본을 확인하지 못했습니다",
            next_action="측정된 얇은 위치를 먼저 확인하세요. 미확인 구간은 CAD에서 두께를 직접 확인하고, 필요하면 단일 솔리드로 재검토하세요." +
                        (" 사용할 장비·재료의 최소 벽 기준도 입력하세요." if limit is None else ""))
    elif limit is None:
        result.update(status="criterion_needed", title="벽은 측정됐지만 비교 기준이 없습니다",
            next_action="사용할 장비·재료의 최소 벽 기준(mm)과 근거를 입력하세요. 현재 측정값을 그 기준과 비교해 확인할 위치를 표시합니다.")
    else:
        result.update(status="within_criterion", level="success", title="검사한 표본에서 입력한 벽 기준 미만이 없습니다",
            next_action=f"표본 최솟값 {_display(minimum)} mm는 입력 기준 {_display(limit)} mm 이상입니다. 아래 표시된 얇은 위치가 설계 의도와 맞는지 확인하고 다른 검토 항목으로 진행하세요.")
    return result


_CHECKS = (
    ("thin", "선폭보다 가는 단면 후보", "설정한 선폭의 경로로 채우기 어려울 수 있는 단면 영역입니다.",
     "해당 높이를 실제 슬라이서에서 확인하세요. 경로가 생략되면 선폭 설정이나 형상을 조정하세요."),
    ("unsupported", "아래층의 지지가 부족한 후보", "이전 층과 설정한 경사 허용 범위를 벗어난 영역입니다.",
     "해당 높이에서 브리지·서포트 경로를 확인하고, 필요하면 방향이나 서포트 설정을 바꾸세요."),
    ("single_layer", "한 층에만 나타나는 후보", "바로 위·아래 측정 단면에 없는 영역입니다.",
     "해당 높이의 얇은 돌출부가 의도한 형상인지 확인하고, 필요하면 두께나 층 높이를 조정하세요."),
)


def summarize_layers(detail):
    """Explain MEX candidate areas, retaining partial and per-check scopes.

    A zero-candidate success needs every requested row, every contour, every
    candidate metric and every metric's complete comparison scope. The engine's
    status alone is insufficient. Raw row positions remain separate from the
    one-based layer numbers shown to people.
    """
    detail = detail or {}
    rows = detail.get("layers") or []
    expected = _count(detail.get("expected_layers"))
    reported_examined = _count(detail.get("examined_layers"))
    reported_complete = _count(detail.get("complete_layers"))
    contour_count = sum(row.get("complete") is True for row in rows)
    counts_match = (expected is not None and expected > 0 and expected == len(rows)
                    and reported_examined == len(rows) and reported_complete == contour_count
                    and contour_count == len(rows))
    sequence_match = all(_count(row.get("index")) == i for i, row in enumerate(rows))
    heights = [_finite(row.get("z_mm")) for row in rows]
    heights_valid = all(value is not None for value in heights) and all(
        a < b for a, b in zip(heights, heights[1:]))
    checks, affected = [], {}
    fully_measured = set(range(len(rows)))
    for key, label, description, action in _CHECKS:
        values = [_number(row.get(key + "_candidate_area_mm2")) for row in rows]
        known = [i for i, value in enumerate(values) if value is not None]
        full = [i for i in known if rows[i].get("complete") is True
                and rows[i].get(key + "_full_scope") is True]
        fully_measured.intersection_update(full)
        positive = [i for i in known if values[i] > 0]
        checks.append(dict(key=key, label=label, known_layers=len(known),
                           fully_measured_layers=len(full), candidate_layers=len(positive) if known else None,
                           maximum_area_mm2=max((values[i] for i in known), default=None),
                           description=description, next_action=action))
        for i in positive:
            if i not in affected:
                index = _count(rows[i].get("index"))
                affected[i] = dict(rows[i], row_position=i,
                                   display_layer=index + 1 if index is not None else None,
                                   types=[], action=[], full_scope=i in full)
            affected[i]["types"].append(label)
            affected[i]["action"].append(action)
            affected[i]["full_scope"] &= i in full
    complete = (detail.get("status") == "complete" and counts_match and sequence_match
                and heights_valid and len(fully_measured) == len(rows))
    affected_rows = [affected[i] for i in sorted(affected)]
    for row in affected_rows:
        row["action"] = " ".join(row["action"])
    result = dict(status="not_run", level="info", title="MEX 층간 검토로 확인할 높이를 찾으세요",
        observation="아직 층간 검토를 실행하지 않았습니다.",
        next_action="실제 슬라이서에 사용할 층 높이·선폭을 맞춘 뒤 '층간 검토 실행'을 누르세요.",
        scope="층 중간 단면에서 세 종류의 형상 후보를 찾습니다. 실제 경로·브리지 성공·접착력의 판정은 슬라이서와 제작 조건에서 확인합니다.",
        reason=detail.get("reason", ""), complete=complete,
        counts=dict(expected=expected, examined=len(rows) if detail else None,
                    complete_contours=contour_count if rows else None,
                    fully_measured=len(fully_measured) if rows else None,
                    candidate_layers=len(affected_rows) if any(c["known_layers"] for c in checks) else None,
                    unresolved=max(0, expected-len(fully_measured)) if expected is not None else None),
        checks=checks, affected_rows=affected_rows,
        default_row_index=affected_rows[0]["row_position"] if affected_rows else None,
        raw_rows=rows)
    if not detail:
        return result
    if detail.get("status") == "not_applicable":
        result.update(status="not_applicable", title="MEX 층간 검토는 현재 공정에 적용되지 않습니다",
            observation=result["reason"] or "이 검토는 필라멘트 압출 공정의 선폭과 층간 지지를 다룹니다.",
            next_action="현재 공정의 단면 변화·벽·배출 경로 등 적용되는 항목을 확인하세요.")
    elif affected_rows:
        result.update(status="attention", level="warning",
            title=f"확인할 후보가 있는 {len(affected_rows):,}개 층을 찾았습니다",
            observation=(f"검사한 {len(rows):,}개 층 중 아래 목록의 높이를 먼저 확인하세요." +
                         (" 일부 범위는 미확인이라 후보 수가 늘어날 수 있습니다." if not complete else "")),
            next_action="첫 후보 층부터 원인을 확인하세요. 표에 적힌 높이를 실제 슬라이서 미리보기에서 찾아 경로·서포트와 대조하세요.")
    elif complete:
        result.update(status="no_candidates", level="success",
            title=f"검사한 {len(rows):,}개 층에서 세 종류의 후보가 발견되지 않았습니다",
            observation="선폭보다 가는 단면·아래층 지지 부족·한 층만의 형상 후보가 모두 0입니다.",
            next_action="이 세 항목에서 우선 수정할 후보는 없습니다. 벽과 다른 검토 항목을 확인한 뒤 실제 슬라이서에서 경로·첫 층·서포트를 최종 확인하세요.")
    elif rows:
        result.update(status="partial", level="warning", title="일부 층간 검토를 확인하지 못했습니다",
            observation=("확인 가능한 범위에서는 후보가 발견되지 않았지만, 전체 요청 범위의 검토 완료를 확정하지 못했습니다."
                         if any(c["known_layers"] for c in checks) else
                         "세 종류 지표의 확인 가능한 면적값이 없습니다."),
            next_action="전체 층 표에서 미확인 항목과 계산 사유를 확인하세요. 단일 솔리드·입력 결함을 점검하고 다시 검토하세요.")
    else:
        result.update(status="unknown", level="warning", title="층간 결과를 계산하지 못했습니다",
            observation=result["reason"] or "확인 가능한 층간 결과가 없습니다.",
            next_action="계산 사유를 확인하세요. 단일 솔리드와 실제 층 높이를 확인한 뒤 다시 실행하세요.")
    return result
