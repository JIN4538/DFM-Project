"""Machining review controls and evidence-linked result components."""
from __future__ import annotations

import html
import json
import re
from urllib.parse import urlsplit

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from amdfm.models import json_bytes
from amdfm.orientation import direction_from_angles
from amdfm.presentation import model_figure
from .machining import MachiningProfile, review_machining
from .conditions import condition_html
from .conditions_view import (render_condition_picker, condition_context,
                              conditions_ready, render_condition_evidence, render_literature_library)
from .advisor import prioritize_actions, context_summary
from .advisor_view import render_advisor, render_applied_context
from .learned_review import analyze_report
from .conclusion_view import render_conclusion
from .location_navigation import request_problem_location, location_heading, finish_location_navigation
from .conclusion import conclusion_html


STATUS = {"attention": "조건 확인·수정 검토", "unknown": "판단에 필요한 정보 부족",
          "observed": "명시된 범위의 측정 완료", "not_detected": "인식 범위 내 미검출"}
VISIBILITY = {
    "occluded": ("앞이 가려진 표본", "다른 방향·가공 순서를 검토하세요.", "#c65102", "diamond"),
    "back_facing": ("공구 반대쪽을 향한 표본", "다른 셋업이 필요한 면인지 확인하세요.", "#663399", "square"),
    "tangent": ("공구축과 평행한 면의 표본", "측면 밀링·공구 반경을 별도 확인하세요.", "#52606d", "cross"),
    "unknown": ("계산 미확정 표본", "경계·시간 제한 등 원인을 확인하세요.", "#111827", "x"),
    "visible": ("직선이 가려지지 않은 표본", "이 방향에서 보이는 측정점입니다.", "#1476b8", "circle"),
}


def _source_web_url(source):
    url = source.get("url")
    try:
        parsed = urlsplit(url) if isinstance(url, str) else None
    except ValueError:
        parsed = None
    return url if parsed and parsed.scheme.lower() in ("http", "https") and parsed.netloc else None


def _source_details(source):
    """Keep evidence purpose and reading limits in both UI and portable report."""
    labels = (("scope", "이 검토에서 사용하는 이유와 범위"), ("locator", "확인할 쪽·항목"),
              ("access", "원문 확인 범위"), ("local_path", "저장소 PDF 위치"))
    return [(label, source[key]) for key, label in labels if source.get(key)]


@st.cache_data(max_entries=4, show_spinner=False)
def cached_machining(fingerprint, profile, direction, visibility, code_revision, _model, auto_tool=False,
                     diameter_fraction=.8, length_allowance_mm=1.):
    if auto_tool:
        from .tool_recommendation import review_with_tool_recommendation
        report = review_with_tool_recommendation(_model, MachiningProfile(**profile), direction, visibility=visibility,
                                                diameter_fraction=diameter_fraction, length_allowance_mm=length_allowance_mm)
    else:
        report = review_machining(_model, MachiningProfile(**profile), direction, visibility=visibility)
    report["code_revision"] = code_revision
    from .external_features_review import attach_external_features
    if 'external_feature_recognition' not in report:attach_external_features(report, _model)
    from .verified_holes import attach_verified_holes
    attach_verified_holes(report, _model)
    return report


def machining_html(report, model=None):
    """Portable, readable conditions and results; raw values remain available."""
    from amdfm.visuals import model_svg

    esc = lambda value: html.escape(str(value), quote=True)

    def table(rows):
        return pd.DataFrame(rows).to_html(index=False, escape=True, float_format=lambda value: f"{value:.8g}") if rows else ""

    def source_link(source):
        title, url = esc(source.get("title", "근거")), _source_web_url(source)
        return f'<a href="{esc(url)}">{title}</a>' if url else title

    profile = report["profile"]
    condition_labels = {
        "machine": "절삭 장비", "material": "절삭 재료",
        "tool_diameter_mm": "엔드밀 지름 (mm)", "flute_length_mm": "날 길이 (mm)",
        "reach_mm": "장착 후 돌출 길이 · 공구 끝~홀더 (mm)",
        "hole_depth_ratio_limit": "사용자 지정 원통 구간 길이/지름 기준",
        "basis": "공구·기준의 출처",
    }
    conditions = [{"적용 조건": label, "값": "미입력·미비교" if profile.get(key) is None else profile[key]}
                  for key, label in condition_labels.items()]
    illustration = ""
    if model is not None:
        # CNC keeps source coordinates; the inherited AM wording would wrongly
        # imply that this neutral illustration was rotated to the tool axis.
        illustration = model_svg(model, report).replace(
            "검토 방향으로 배치한 입력 메시 참고도", "원본 좌표의 입력 메시 참고도").replace(
            "입력 메시의 검토 방향 배치 · 정밀 치수 도면 아님", "원본 좌표의 입력 메시 · 정밀 치수 도면 아님")
        illustration += '<p>원본 좌표의 형상 참고도입니다. 공구축에 맞춰 회전한 그림이나 정밀 치수 도면이 아닙니다. 항목별 위치는 앱의 측정 위치 선택과 CAD 면 번호를 함께 확인하세요.</p>'
    else:
        illustration = '<p>형상 참고도는 이 보고서에 포함되지 않았습니다. 위치는 원본 형상과 CAD 면 번호로 확인하세요.</p>'
    sections = []
    source_by_id = {source["id"]: source for source in report["sources"] if source.get("id")}
    for finding in report["findings"]:
        rows = feature_rows(finding, profile)
        references = [source_by_id[key] for key in finding.get("evidence", []) if key in source_by_id]
        linked_evidence = ('<p><strong>이 항목의 근거:</strong> ' + ' / '.join(source_link(source) for source in references) + '</p>') if references else ''
        sections.append(f'<section><h2>{esc(finding["title"])}</h2><p><b>{esc(STATUS.get(finding["status"], finding["status"]))}</b></p>'
            f'<p>{esc(finding["reason"])}</p><p><strong>다음 행동:</strong> {esc(finding["action"])}</p>'
            f'{table(rows)}<details><summary>계산 원자료</summary><pre>{esc(json.dumps(finding["measurements"], ensure_ascii=False, indent=2))}</pre></details>'
            f'<p>{esc(" / ".join(finding["limitations"]))}</p>{linked_evidence}</section>')
    sources = ''.join('<li>' + source_link(source) + ''.join(
        f'<p><strong>{esc(label)}:</strong> {esc(value)}</p>'
        for label, value in _source_details(source)) + '</li>' for source in report["sources"])
    decisions = machining_decisions(report)
    decision_html = '<details><summary>전체 개선 항목</summary>'
    if decisions['cards']:
        decision_html += ''.join(
            f'<section><h3>{i}. {esc(card["title"])}</h3>'
            + ''.join(f'<p>{esc(value)}</p>' for value in card['comparisons'])
            + f'<p>{esc(card["reason"])}</p><p><strong>할 일:</strong> {esc(card["action"])}</p></section>'
            for i, card in enumerate(decisions['cards'], 1))
    else:
        decision_html += '<p>판단에 필요한 정보·검토가 남아 있습니다.</p>' if decisions['pending'] else '<p>검사한 범위에서 수정 후보가 검출되지 않았습니다.</p>'
    if decisions['missing_inputs']:
        decision_html += '<p><strong>치수 비교에 필요한 입력:</strong> ' + esc(' · '.join(decisions['missing_inputs'])) + '</p>'
    if decisions['pending']:
        decision_html += '<p><strong>아직 판단하지 못한 항목:</strong> ' + esc(' · '.join(f['title'] for f in decisions['pending'])) + '</p>'
    decision_html += '</details>'
    return ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>절삭 설계 검토</title><style>body{max-width:1050px;margin:40px auto;padding:0 24px;font-family:system-ui;line-height:1.7}'
        'section{border-top:1px solid #cbd5e1;padding:16px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}'
        'table{border-collapse:collapse;display:block;overflow-x:auto;max-width:100%}th,td{padding:8px;border:1px solid #cbd5e1}'
        'svg{max-width:640px;width:100%;height:auto}p{overflow-wrap:anywhere}</style></head><body>'
        f'<h1>절삭 설계 검토</h1><p>{esc(report["input"].get("filename", ""))}</p>'
        f'<p>{esc(context_summary(report.get("review_context",{}),"CNC"))}</p>'
        f'<p>선택 공구축 (모델 X, Y, Z): {esc(report["direction"])} / 검토 시각: {esc(report["created_utc"])}</p>'
        '<p>고정축 밀링의 기하 검토 · 공구는 표시한 축의 반대 방향으로 진입합니다.</p>'
        + conclusion_html(report) + decision_html + '<details><summary>형상·조건·항목별 근거</summary>' + illustration + f'<h2>이 결과에 적용한 조건</h2>{table(conditions)}'
        + condition_html(profile.get('condition_evidence')) +
        '<p>‘아니오’는 해당 치수가 기준을 초과하지 않았다는 뜻입니다. ‘수치 경계’는 계산 오차 범위에서 같은 값입니다.</p>'
        f'<details><summary>조건 원자료</summary><pre>{esc(json.dumps(profile, ensure_ascii=False, indent=2))}</pre></details>'
        f'<details><summary>사용자 요구·해석 출처</summary><pre>{esc(json.dumps(report.get("review_context",{}), ensure_ascii=False, indent=2))}</pre></details>'
        + ''.join(sections) + f'<h2>별도 확인이 필요한 범위</h2><p>{esc(" / ".join(report["unassessed"]))}</p>'
        f'<h2>근거</h2><ul>{sources}</ul><p>입력 SHA: {esc(report["input"].get("source_sha256"))}<br>'
        f'코드 SHA: {esc(report.get("code_revision"))}</p></details></body></html>')


def feature_rows(finding, profile=None):
    """Keep dimensions and explicit comparison conditions beside each other."""
    measures = finding["measurements"]
    if finding["id"] == "cnc_tool_recommendation":
        from .tool_recommendation_presentation import TOOL_LABELS
        return [{"CAD 면": row.get("cad_face_id"), "비교 항목": TOOL_LABELS.get(row.get("field"), row.get("field")),
                 "공구 값 (mm)": row.get("value_mm"), "형상 비교값 (mm)": row.get("limit_mm"),
                 "관계": "상한" if row.get("relation") == "at_most" else "하한",
                 "확인 결과": "수정 검토" if row.get("conflict") else "절입 방식 확인" if row.get("assumption_shortfall")
                    else "수치 경계" if row.get("numerical_boundary") else "치수 조건 내",
                 "기준": "구간 전체 절삭 가정" if row.get("assumption_only") else "측정 치수"}
                for row in measures.get("comparisons", [])]
    rows = measures.get("cylindrical_faces") or measures.get("pockets")
    if not rows:
        if finding["id"] == "cnc_visibility" and measures.get("sample_state_counts"):
            return [{"표본 분류": title, "표본 수": measures["sample_state_counts"].get(key, "미확정"), "해석·다음 행동": action}
                    for key, (title, action, _, _) in VISIBILITY.items()]
        return []
    labels = {"face_id": "CAD 면", "diameter_mm": "지름 (mm)", "cylindrical_length_mm": "원통 구간 길이 (mm)",
        "length_diameter_ratio": "구간 길이 / 지름", "axis_aligned": "선택 축과 나란함", "axis_angle_deg": "축 차이 (°)",
        "tool_too_large": "공구 지름 > 특징 지름", "segment_exceeds_reach": "원통 구간 > 돌출 길이",
        "exceeds_ratio": "입력 비율 기준 초과", "radius_mm": "오목면 반경 (mm)",
        "floor_face_id": "바닥 CAD 면", "width_mm": "바닥 폭 (mm)", "length_mm": "바닥 길이 (mm)",
        "wall_height_mm": "벽 높이 (mm)", "width_too_small": "공구보다 좁음",
        "exceeds_flute_length": "벽 높이 > 날 길이", "exceeds_reach": "벽 높이 > 돌출 길이",
        "internal_corner_radius_mm":"내부 코너 반경 (mm)"}
    if finding['id']=='cnc_learned_pockets':
        labels.update(entry_circle_diameter_mm='바닥 진입원 지름 (mm)',width_too_small='공구 지름 > 진입원 지름')
    if finding["id"] == "cnc_curved_corners":
        labels["tool_too_large"] = "공구 반경 > 오목면 반경"
    display = lambda value: "미입력·미비교" if value is None else "예" if value is True else "아니오" if value is False else value
    def comparison(row, key):
        if key in row.get("numerical_boundary_comparisons", []):
            return "수치 경계·별도 확인"
        if key in ("tool_too_large", "segment_exceeds_reach") and row.get("axis_aligned") is False and row.get(key) is None:
            return "축 불일치·미비교"
        return display(row.get(key))

    shown = []
    for row in rows:
        item = {labels[key]: comparison(row, key) for key in row if key in labels}
        if row.get('measurement_source') == 'native-circular-rims-1':
            item.pop('원통 구간 길이 (mm)', None)
            item['구멍 깊이 (mm)'] = row['depth_mm']
            item['구멍 종류'] = '관통' if row['hole_kind']=='through' else '막힌 구멍'
            item['입구 방향'] = '일치' if row['entry_matches_direction'] else '바닥 쪽' if row['entry_blocked'] else '다른 축'
        if profile is not None:
            if finding["id"] == "cnc_curved_corners":
                diameter = profile.get("tool_diameter_mm")
                radius = diameter / 2 if diameter is not None else None
                # Both values are radii. The difference is only a scalar
                # comparison, never a clearance or physical success margin.
                item = {"CAD 면": row.get("face_id"), "오목면 반경 (mm)": row.get("radius_mm"),
                        "공구 반경 (mm)": display(radius),
                        "반경 차이 · 면−공구 (mm)": display(row["radius_mm"] - radius if radius is not None else None),
                        "공구 반경 > 오목면 반경": comparison(row, "tool_too_large")}
            elif finding["id"] == "cnc_holes":
                item["입력 공구 지름 (mm)"] = display(profile.get("tool_diameter_mm"))
                item["입력 돌출 길이 (mm)"] = display(profile.get("reach_mm"))
                if profile.get("hole_depth_ratio_limit") is not None:
                    item["입력 구간 길이/지름 기준"] = profile["hole_depth_ratio_limit"]
            elif finding["id"] in ("cnc_rectangular_pockets","cnc_learned_pockets"):
                for key, label in (("tool_diameter_mm", "입력 공구 지름 (mm)"),
                                   ("flute_length_mm", "입력 날 길이 (mm)"),
                                   ("reach_mm", "입력 돌출 길이 (mm)")):
                    item[label] = display(profile.get(key))
        if row.get('measurement_source') == 'native-circular-rims-1':
            bad = any(row.get(k) for k in ('tool_too_large','segment_exceeds_reach','exceeds_ratio'))
            compared = row.get('tool_too_large') is not None and row.get('segment_exceeds_reach') is not None
            item = {'지름 (mm)':row['diameter_mm'], '깊이 (mm)':row['depth_mm'],
                    '종류':'관통' if row['hole_kind']=='through' else '막힌 구멍',
                    '입구 방향':'일치' if row['entry_matches_direction'] else '바닥 쪽' if row['entry_blocked'] else '다른 축',
                    '치수 비교':'조정 필요' if bad else '맞음' if compared else '미비교'}
            if profile is not None:
                item.update({'공구 지름 (mm)':display(profile.get('tool_diameter_mm')),
                             '돌출 길이 (mm)':display(profile.get('reach_mm'))})
        shown.append(item)
    return shown


def measurement_display_table(rows):
    """Round only the view copy; numeric sorting and raw report values survive."""
    labels = {
        "바닥 진입원 지름 (mm)": "포켓에 들어가는 원의 지름 (mm)",
        "공구 지름 > 진입원 지름": "공구가 포켓에 들어가는 원보다 큼",
        "벽 높이 > 날 길이": "벽 높이 > 절삭 날 길이",
        "입력 날 길이 (mm)": "입력 절삭 날 길이 (mm)",
    }
    def rounded(value):
        if isinstance(value, (float, np.floating)) and np.isfinite(value):
            return float(f"{value:.4g}")
        return value
    return pd.DataFrame([{labels.get(key, key): rounded(value) for key, value in row.items()}
                         for row in rows])


def machining_display_text(text):
    """Expand CAD shorthand in prose without rewriting stored findings."""
    text = text.replace("바닥 진입원 지름", "포켓에 들어가는 원의 지름")
    text = text.replace("진입원 최소 Ø", "포켓에 들어가는 원의 최소 지름 ")
    text = text.replace("내부 코너", "안쪽 코너")
    text = re.sub(r"\bR\s*(?=\d)", "둥근 반경 ", text)
    return re.sub(r"(?<!절삭 )날 길이", "절삭 날 길이", text)


def machining_figure(model, report=None, finding_id="", *, direction=(0,0,1), cad_face_ids=None):
    original = next((f for f in report["findings"] if f["id"] == finding_id), None) if report else None
    feature_only = original is None and report is not None and cad_face_ids is not None
    if report is not None and cad_face_ids is not None:
        # Selection changes the view only, never the report or its conclusions.
        face_indices = (np.flatnonzero(np.isin(model.face_ids, cad_face_ids)).tolist()
                        if model.face_ids is not None else [])
        if feature_only:
            finding_id='_selected_cad_feature'
            report={**report,'findings':[*report['findings'],dict(id=finding_id,title='선택한 특징',status='observed',
                face_indices=face_indices,cad_face_ids=list(cad_face_ids))]}
        report = {**report, "findings": [
            {**f, "face_indices": face_indices, "cad_face_ids": list(cad_face_ids)}
            if f["id"] == finding_id else f for f in report["findings"]]}
    fig = model_figure(model, report, finding_id, axis_label="공구가 오는 쪽", axis_vector=direction)
    for trace in fig.data:
        if trace.type == "mesh3d":
            trace.flatshading = True
    if cad_face_ids is not None and len(fig.data) > 1 and fig.data[1].type == "mesh3d":
        # Blue means a selected measurement. Orange is reserved for locations
        # already requiring attention in this finding, not every selected face.
        attention_faces = set(original["face_indices"]) if original and original["status"] == "attention" else set()
        fig.data[1].facecolor = ["#c65102" if index in attention_faces else "#1476b8"
                                 for index in face_indices[:250_000]]
        fig.data[1].color = "#1476b8"
        if feature_only and face_indices:
            # Local crop is a view operation; the original analysis/export mesh
            # and its dimensions stay intact. Only the selected feature uses it.
            vertices=model.mesh.vertices[model.mesh.faces[face_indices].ravel()]
            matrix=np.asarray(report['current_orientation']['transform'])
            vertices=vertices@matrix[:3,:3].T+matrix[:3,3]
            low,high=vertices.min(0),vertices.max(0)
            margin=max(float(np.max(high-low))*.2,float(np.max(model.mesh.extents))*.03)
            fig.update_layout(scene={name+'axis':dict(range=[float(low[i]-margin),float(high[i]+margin)]) for i,name in enumerate('xyz')},
                uirevision=model.fingerprint+'-feature-'+','.join(map(str,cad_face_ids)))
    if report is not None and cad_face_ids is not None and report.get('verified_hole_inventory'):
        from .hole_view import mark_hole_mouths
        mark_hole_mouths(fig, report, cad_face_ids, direction)
    return fig


def feature_locations(finding):
    """Stable CAD identifiers connect measurements to selectable geometry."""
    measures = finding["measurements"]
    result = {}
    for row in measures.get("cylindrical_faces", []) + measures.get("pockets", []):
        face_id = row.get("face_id", row.get("floor_face_id"))
        if face_id is None:
            continue
        if "radius_mm" in row:
            label = f"오목면 반경 {row['radius_mm']:.6g} mm"
        elif row.get('measurement_source') == 'native-circular-rims-1':
            kind = '관통 구멍' if row['hole_kind'] == 'through' else '막힌 구멍'
            label = f"{kind} Ø {row['diameter_mm']:.6g} mm · 깊이 {row['depth_mm']:.6g} mm"
        elif "diameter_mm" in row:
            label = f"원통 지름 {row['diameter_mm']:.6g} mm · 구간 길이 {row['cylindrical_length_mm']:.6g} mm"
        else:
            label = (f"포켓에 들어가는 원 Ø {row['entry_circle_diameter_mm']:.4g} mm" if row.get('entry_circle_diameter_mm') else f"포켓 바닥 폭 {row['width_mm']:.4g} mm")+f" · 벽 높이 {row['wall_height_mm']:.4g} mm"
        result[str(face_id)] = f"CAD 면 {face_id} · {label}"
    for face_id in measures.get("unresolved_floor_face_ids", []):
        result.setdefault(str(face_id), f"CAD 면 {face_id} · 포켓 치수 미확정 위치")
    if not result:
        for face_id in finding.get("cad_face_ids", []):
            result[str(face_id)] = f"CAD 면 {face_id} · 추가 확인 위치"
    return result


def machining_decisions(report):
    """Prioritize recorded observations without promoting missing data to pass.

    The engine's status and measurements remain untouched. A location card is
    a navigation aid, not a new machining-feasibility rule.
    """
    profile = report["profile"]
    findings = report["findings"]
    attention = [f for f in findings if f["status"] == "attention"]
    pending = [f for f in findings if f["status"] == "unknown"]
    cards = []
    for finding in attention:
        measures = finding["measurements"]
        rows = measures.get("cylindrical_faces", []) + measures.get("pockets", [])
        flags = ("tool_too_large", "segment_exceeds_reach", "exceeds_ratio",
                 "width_too_small", "exceeds_flute_length", "exceeds_reach")
        first = next((r for r in rows if any(r.get(key) is True for key in flags)
                      or r.get("axis_aligned") is False), rows[0] if rows else {})
        face = first.get("face_id", first.get("floor_face_id"))
        comparisons = []
        action = finding["action"]
        fmt = lambda value: f"{value:,.6g}"
        if finding["id"] == "cnc_curved_corners" and first:
            diameter = profile.get("tool_diameter_mm")
            if diameter is not None and first.get("radius_mm") is not None:
                comparisons.append(f"형상 반경 {fmt(first['radius_mm'])} mm / 공구 반경 {fmt(diameter / 2)} mm")
        elif finding["id"] == "cnc_holes" and first:
            if first.get("axis_aligned") is False:
                comparisons.append(f"선택한 공구축과 원통축의 차이 {fmt(first['axis_angle_deg'])}° · 치수 비교 보류")
            if first.get("tool_too_large") is True:
                comparisons.append(f"내부 지름 {fmt(first['diameter_mm'])} mm < 공구 지름 {fmt(profile['tool_diameter_mm'])} mm")
            if first.get("segment_exceeds_reach") is True:
                comparisons.append(f"원통 구간 {fmt(first['cylindrical_length_mm'])} mm > 돌출 길이 {fmt(profile['reach_mm'])} mm")
            if first.get("exceeds_ratio") is True:
                comparisons.append(f"구간 길이/지름 {fmt(first['length_diameter_ratio'])} > 입력 기준 {fmt(profile['hole_depth_ratio_limit'])}")
        elif finding["id"] == "cnc_rectangular_pockets" and first:
            comparisons.append(f"포켓 폭 {fmt(first['width_mm'])} mm · 벽 높이 {fmt(first['wall_height_mm'])} mm · 내부 직각")
            for flag, feature, setting, label in (
                ("width_too_small", "width_mm", "tool_diameter_mm", "포켓 폭 / 공구 지름"),
                ("exceeds_flute_length", "wall_height_mm", "flute_length_mm", "벽 높이 / 날 길이"),
                ("exceeds_reach", "wall_height_mm", "reach_mm", "벽 높이 / 돌출 길이"),
            ):
                if first.get(flag) is True:
                    comparisons.append(f"{label}: {fmt(first[feature])} / {fmt(profile[setting])} mm · 확인 필요")
            actions = []
            if first.get("width_too_small") is True:
                actions.append(f"폭 {fmt(first['width_mm'])} mm에 가공 여유를 확보할 더 작은 공구를 검토하거나 포켓 폭을 넓히세요.")
            if first.get("exceeds_reach") is True:
                actions.append("포켓 깊이·접근 방향·재고정·장착 조건을 재검토하고, 실제 진입 깊이와 홀더 여유를 CAM에서 확인하세요.")
            if first.get("exceeds_flute_length") is True:
                actions.append("분할 절입·목부 공구로 측벽에 접근할 수 있는지 간섭을 확인하세요. 긴 공구가 항상 해결책은 아닙니다.")
            if actions:
                actions.append("내부 직각에는 반경이나 코너 여유를 추가하세요.")
                action = " ".join(actions)
        elif finding["id"] == "cnc_visibility":
            counts = measures.get("sample_state_counts", {})
            if counts.get("occluded") is not None:
                comparisons.append(f"앞이 가려진 측정점 {counts['occluded']:,}개 · 전체 면이나 공구 충돌 판정은 아님")
        cards.append(dict(id=finding["id"], title=finding["title"], reason=finding["reason"],
                          action=action, comparisons=comparisons, face_id=face))
    has_holes = any(f["id"] == "cnc_holes" and f["measurements"].get("cylindrical_faces") for f in findings)
    has_corners = any(f["id"] == "cnc_curved_corners" and f["measurements"].get("cylindrical_faces") for f in findings)
    has_pockets = any(f["measurements"].get("pockets") for f in findings)
    required = (("tool_diameter_mm", "공구 지름", has_holes or has_corners or has_pockets),
                ("flute_length_mm", "날 길이", has_pockets),
                ("reach_mm", "장착 후 돌출 길이", has_holes or has_pockets))
    missing = [label for key, label, needed in required if needed and profile.get(key) is None]
    cards=prioritize_actions(cards,report.get('review_context',{}))
    return dict(cards=cards, pending=pending, missing_inputs=missing)


def focus_machining_finding(finding_id, face_id=None):
    if face_id is None:
        report = st.session_state.get("cnc_report")
        if report:
            card = next((item for item in machining_decisions(report)["cards"]
                         if item["id"] == finding_id), None)
            face_id = card.get("face_id") if card else None
    st.session_state["cnc_finding"] = finding_id
    st.session_state["cnc_location_details"] = True
    request_problem_location('cnc')
    st.session_state["cnc_pending_location"] = str(face_id) if face_id is not None else "all"
    if finding_id == "cnc_visibility":
        st.session_state["cnc_sample_state"] = "all"


def render_machining_decisions(report, *, learned_display=None):
    """Keep every rule finding accessible without repeating the AI cards."""
    decisions = machining_decisions(report)
    cards, pending = decisions["cards"], decisions["pending"]
    learned_display = learned_display or {}
    displayed = set(learned_display.get("displayed_ids", []))
    unmatched = [card for card in cards if card["id"] not in displayed]
    blockers = [finding for finding in report["findings"]
                if finding["id"] == "cnc_input" and finding["status"] in ("attention", "unknown")]
    for finding in blockers:
        st.error(f"{finding['title']} · {finding['action']}")
    if cards:
        if not learned_display.get("rendered"):
            st.warning(f"확인할 문제 {len(cards)}개 · 먼저 {cards[0]['title']}")
        elif unmatched:
            st.caption("추가 규칙 검토 · " + " / ".join(card["title"] for card in unmatched))
        with st.expander(f"전체 개선 항목 {len(cards)}개 · 치수와 조치",
                         expanded=not learned_display.get("rendered")):
            for index, card in enumerate(cards, 1):
                with st.container(border=True):
                    st.markdown(f"**{index}. {card['title']}**")
                    if card["comparisons"]:
                        for comparison in card["comparisons"]:
                            st.write(comparison)
                    else:
                        st.write(card["reason"])
                    st.markdown(f"**할 일** · {card['action']}")
                    st.button("이 위치 보기", key="cnc_focus_" + card["id"],
                              on_click=focus_machining_finding, args=(card["id"], card["face_id"]))
    elif pending:
        st.caption(f"추가 확인 {len(pending)}개")
    elif not learned_display.get("rendered"):
        st.info("검토한 항목에서 수정 후보가 없습니다.")
    if decisions["missing_inputs"]:
        st.info("추가 입력: " + " · ".join(decisions["missing_inputs"]))
    if pending:
        with st.expander(f"아직 판단하지 못한 항목 {len(pending)}개"):
            for finding in pending:
                st.markdown(f"**{finding['title']}** · {finding['reason']}")
                st.write(finding["action"])
                st.button("이 항목 보기", key="cnc_pending_" + finding["id"],
                          on_click=focus_machining_finding, args=(finding["id"],))


def visibility_figure(model, report, direction, category="all"):
    # Point measurements are displayed as points; do not paint their full faces.
    fig = machining_figure(model, direction=direction)
    fig.data[0].opacity = .25
    for state, (label, _, color, symbol) in VISIBILITY.items():
        rows = [r for r in (report.get("visibility") or {}).get("samples", [])
                if r["state"] == state and category in ("all", state)]
        if not rows:
            continue
        points = np.array([r["point_mm"] for r in rows])
        fig.add_trace(go.Scatter3d(x=points[:, 0], y=points[:, 1], z=points[:, 2], mode="markers",
            marker=dict(size=5, color=color, symbol=symbol), name=label,
            customdata=[r["source_face"] for r in rows],
            hovertemplate="표본 면 %{customdata}<extra>%{fullData.name}</extra>"))
    fig.update_layout(showlegend=True, legend=dict(orientation="h", y=-.05, x=0))
    return fig


def render_machining(model, filename, data, code_revision):
    with st.sidebar:
        st.divider()
        st.markdown("**절삭 조건 · 고정축 밀링**")
        condition_library = render_condition_picker("CNC")
    context = render_advisor("CNC", condition_library)
    machine, material = context['equipment'], context['material']
    with st.sidebar:
        axes = {"+Z · 위쪽에서": (0,0,1), "−Z · 아래쪽에서": (0,0,-1), "+X": (1,0,0), "−X": (-1,0,0), "+Y": (0,1,0), "−Y": (0,-1,0)}
        label = st.selectbox("공구가 오는 방향", [*axes, "직접 각도 입력"], key="cnc_direction", persist_state="session",
                             help="화살표는 부품에서 공구 쪽을 향합니다. 공구는 반대 방향으로 진입합니다.")
        if label == "직접 각도 입력":
            tilt = st.number_input("모델 +Z에서 기울기 (°)", min_value=0., max_value=180., value=0., step=1., format="%.6f", key="cnc_tilt", persist_state="session")
            azimuth = st.number_input("모델 +X에서 방위각 (°)", min_value=0., max_value=360., value=0., step=1., format="%.6f", key="cnc_azimuth", persist_state="session")
            direction = tuple(direction_from_angles(tilt, azimuth))
        else:
            direction = axes[label]
        with st.container(border=True):
            with st.expander("보유 공구 지정 (선택)"):
                auto_tool = st.toggle("빈 공구 치수 자동 제안", value=True, key="cnc_auto_tool", persist_state="session")
                diameter = st.number_input("엔드밀 지름 (mm)", min_value=.001, value=None, step=.1, format="%.4f", key="cnc_diameter", persist_state="session",
                                           help="값을 입력하면 그대로 검토합니다. 빈 항목은 형상에서 제안합니다.")
                flute = st.number_input("재료를 깎는 날의 길이 (mm)", min_value=.001, value=None, step=.1, format="%.4f", key="cnc_flute", persist_state="session",
                                        help="공구 전체 길이가 아니라 절삭날이 있는 부분의 길이입니다. 모르면 비워 두세요.")
                reach = st.number_input("홀더 밖으로 나온 공구 길이 (mm)", min_value=.001, value=None, step=.1, format="%.4f", key="cnc_reach", persist_state="session",
                                        help="공구를 고정하는 홀더 앞면부터 공구 끝까지의 거리입니다. 모르면 비워 두세요.")
            with st.expander("자동 제안 조정·추가 기준 (선택)"):
                diameter_percent = st.number_input("자동 공구 지름 · 들어갈 수 있는 폭 대비 (%)", min_value=1., max_value=99.9,
                    value=80., step=5., key="cnc_auto_diameter_percent", persist_state="session",
                    help="예: 80%이면 측정한 지름 상한보다 20% 작은 공구를 제안합니다. 직접 입력한 공구에는 적용하지 않습니다.")
                length_allowance = st.number_input("자동 공구 길이 · 깊이에 더할 여유 (mm)", min_value=0., value=1., step=.5,
                    key="cnc_auto_length_allowance", persist_state="session",
                    help="측정한 깊이에 이 길이를 더해 제안합니다. 직접 입력한 공구에는 적용하지 않습니다.")
                ratio = st.number_input("깊은 구멍 확인 · 길이÷지름 기준 (선택)", min_value=.01, value=None, step=.1, format="%.4f", key="cnc_ratio", persist_state="session",
                                        help="예: 5를 입력하면 원통 구간 길이가 지름의 5배를 넘는 곳을 찾습니다. 단차가 있는 구멍은 각 원통 구간을 따로 비교합니다.")
                basis = st.text_input("공구·기준의 출처", value="사용자 지정 공구·검토 조건", key="cnc_basis", persist_state="session")
            visibility = st.checkbox("선택 방향에서 가려진 표면도 확인", value=True, key="cnc_visibility", persist_state="session",
                                     help="최대 512개 표본·10초 안에서 계산합니다. 미확인 영역은 별도로 표시합니다.")
            submitted = st.button("절삭 설계 검토", key='run_cnc_review', type="primary", width="stretch",
                                              disabled=not conditions_ready(condition_library, "CNC"))
    profile_values = dict(machine=machine, material=material, tool_diameter_mm=diameter,
                          flute_length_mm=flute, reach_mm=reach, hole_depth_ratio_limit=ratio, basis=basis)
    profile = MachiningProfile(**profile_values,
        condition_evidence=condition_context(condition_library, "CNC", profile_values))
    settings = json_bytes([model.fingerprint, profile.to_dict(), direction, visibility, auto_tool,
                           diameter_percent, length_allowance, context, code_revision]).decode()
    if (submitted or st.session_state.pop('cnc_auto_review',False)) and conditions_ready(condition_library, "CNC"):
        try:
            with st.spinner("CAD 특징과 선택 공구 조건을 비교하는 중…"):
                report = cached_machining(model.fingerprint, profile.to_dict(), direction, visibility, code_revision, model,
                    auto_tool=auto_tool, diameter_fraction=diameter_percent / 100, length_allowance_mm=length_allowance)
            report['review_context']=context
            report['learned_review']=analyze_report(report)
            st.session_state["cnc_report"] = report
            st.session_state["cnc_report_settings"] = settings
            st.session_state["cnc_location_details"] = False
            st.rerun()
        except (ValueError, MemoryError) as exc:
            st.error(str(exc))
            return
    report = (st.session_state.get("cnc_report") if st.session_state.get("cnc_report_settings") == settings
              and conditions_ready(condition_library, "CNC") else None)
    if report is None:
        st.info("형상을 검토하면 문제점과 공구 치수를 함께 제안합니다." if auto_tool else "형상을 검토하고 입력한 공구 조건과 비교합니다.")
        st.button('이 형상으로 절삭 검토 시작',type='primary',key='cnc_start_from_model',
                  on_click=lambda: st.session_state.update(cnc_auto_review=True),
                  disabled=not conditions_ready(condition_library,'CNC'))
        st.plotly_chart(machining_figure(model, direction=direction), width="stretch", config={"scrollZoom": False})
        with st.expander("검토 범위"):
            st.write("한 방향에서 공구를 넣는 밀링을 검토합니다. 구멍·안쪽 코너·포켓과 가려진 표면을 찾습니다.")
            st.caption("포켓 치수는 수직 벽을 가진 단순 삼각·사각·육각 형상에서 비교합니다.")
        return
    unknown = [f for f in report["findings"] if f["status"] == "unknown"]
    render_applied_context(report, 'CNC')
    render_conclusion(report,on_select=focus_machining_finding,key_prefix='cnc')
    from .hole_view import render_hole_overview
    render_hole_overview(report, on_select=focus_machining_finding)
    from .cad_edit_preview import render_preview
    render_preview(report, model, data, filename, code_revision)
    from .feature_learning_view import render_feature_candidates
    render_feature_candidates(model,report,direction)
    # Keep widget options and labels stable. Reordering options by severity on
    # the same key can leave the browser's selected index on a different item.
    lookup = {f["id"]: f for f in report["findings"]}
    finding_context=json_bytes([model.fingerprint,report['profile'],report['direction'],report.get('review_context',{})]).decode()
    if (st.session_state.get("cnc_finding_context") != finding_context
            or st.session_state.get("cnc_finding") not in lookup):
        ordered=machining_decisions(report)['cards']
        st.session_state["cnc_finding"] = (ordered or unknown or report["findings"])[0]["id"]
        st.session_state["cnc_finding_model"] = model.fingerprint
        st.session_state["cnc_finding_context"] = finding_context
    hole_focus = st.session_state.pop('cnc_pending_hole_focus', None)
    if hole_focus is not None:
        focus_machining_finding('cnc_holes', hole_focus)
    # The first screen contains one conclusion. Geometry and detailed tables
    # are built only after the user opens the location panel or follows a
    # conclusion's location button.
    if st.toggle("문제 위치·측정값 보기", key="cnc_location_details"):
        location_heading('cnc')
        with st.container(border=True):
            _render_machining_location(model, report, direction, lookup)
        finish_location_navigation('cnc')
    with st.expander("적용 조건·전체 검토 항목"):
        columns = st.columns(3)
        for column, title, key in zip(columns, ["엔드밀 지름", "날 길이", "장착 후 돌출 길이"],
                                      ["tool_diameter_mm", "flute_length_mm", "reach_mm"]):
            value = report["profile"].get(key)
            column.metric(title, "미입력" if value is None else f"{value:,.6g} mm")
        st.caption("공구가 오는 방향: " + ", ".join(f"{v:.6g}" for v in report["direction"]) + " (모델 좌표)")
        render_condition_evidence(report["profile"].get("condition_evidence"))
        st.dataframe(pd.DataFrame([{"항목": f["title"], "상태": STATUS.get(f["status"], f["status"]),
                                   "결과": f["reason"], "다음 행동": f["action"]}
                                  for f in report["findings"]]), hide_index=True)
        st.caption("미검토 범위: " + " · ".join(report.get("unassessed", [])))
    st.download_button("검토 보고서 저장", machining_html(report, model), "machining_review.html", "text/html",
                       key="cnc_save_report", icon=":material/download:",
                       help="결론, 개선안, 형상, 적용 조건을 담은 HTML 파일입니다. 브라우저에서 열 수 있습니다.")
    with st.expander("근거·원본 데이터"):
        with st.container(horizontal=True):
            st.download_button("검토 데이터 JSON", json_bytes(report), "machining_review.json", "application/json")
            st.download_button("입력 STEP 원본", data, filename, "application/octet-stream")
        for source in report["sources"]:
            url = _source_web_url(source)
            st.markdown(f"[{source['title']}]({url})" if url else f"**{source['title']}**")
            for label, value in _source_details(source):
                if label == "이 검토에서 사용하는 이유와 범위":
                    st.write(f"{label}: {value}")
                else:
                    st.caption(f"{label}: {value}")
        st.json(report, expanded=False)
    render_literature_library("CNC")


def _render_machining_location(model, report, direction, lookup):
    """Optional geometry inspection; selecting a location never edits results."""
    selected = st.selectbox("확인할 항목", list(lookup), format_func=lambda k: lookup[k]["title"], key="cnc_finding")
    finding = lookup[selected]
    location = "all"
    if selected == "cnc_visibility" and report.get("visibility"):
        measures = report["visibility"]["measurements"]
        omitted = measures.get("omitted_face_count")
        st.caption(f"미표본 면 {omitted:,}개 · 표시한 점 기준"
                   if omitted is not None else "표본 범위 미확정")
        state = st.selectbox("표시할 측정점", ["all", *VISIBILITY], format_func=lambda key: "모든 측정점" if key == "all" else VISIBILITY[key][0], key="cnc_sample_state")
        st.plotly_chart(visibility_figure(model, report, direction, state), width="stretch", config={"scrollZoom": False})
    else:
        locations = feature_locations(finding)
        highlighted = None
        if locations:
            location_context = (model.fingerprint, selected, tuple(locations))
            if st.session_state.get("cnc_location_context") != location_context:
                st.session_state["cnc_location"] = "all"
                st.session_state["cnc_location_context"] = location_context
            pending_location = st.session_state.pop("cnc_pending_location", None)
            if pending_location in ("all", *locations):
                st.session_state["cnc_location"] = pending_location
            location = st.selectbox("확인할 위치", ["all", *locations],
                format_func=lambda k: "이 항목의 측정 위치 모두" if k == "all" else locations[k], key="cnc_location")
            selected_ids=[int(k) for k in locations] if location == 'all' else [int(location)]
            highlighted=set(selected_ids)
            for row in finding['measurements'].get('pockets',[]):
                if row.get('floor_face_id') in selected_ids:
                    highlighted.update(row.get('face_ids',[]))
                    highlighted.update(row.get('wall_face_ids',[]))
            for row in finding['measurements'].get('cylindrical_faces', []):
                if row.get('face_id') in selected_ids:
                    highlighted.update(row.get('face_ids', []))
            highlighted=sorted(highlighted)
        st.plotly_chart(machining_figure(model, report, selected, direction=direction, cad_face_ids=highlighted), width="stretch", config={"scrollZoom": False})
        st.caption("파랑: 선택 위치 · 주황: 조건 확인 위치"
                   if locations else "별도로 표시할 CAD 위치가 없습니다.")
    displayed_finding = selected_location_finding(finding, location)
    st.caption('항목 전체 · ' + STATUS.get(finding['status'],finding['status']))
    st.write(machining_display_text(finding['reason']))
    if finding['status']=='attention':
        st.markdown(f"**할 일** · {machining_display_text(finding['action'])}")
    rows = feature_rows(displayed_finding, report["profile"])
    if rows:
        st.markdown("**선택한 위치의 측정값**" if location != "all" else "**측정값 비교**")
        table=measurement_display_table(rows)
        formats={name:st.column_config.NumberColumn(format='%.4g') for name in table.columns
                 if pd.api.types.is_float_dtype(table[name])}
        if '포켓에 들어가는 원의 지름 (mm)' in table:
            formats['포켓에 들어가는 원의 지름 (mm)'] = st.column_config.Column(
                help='포켓 바닥 윤곽 안에 들어가는 가장 큰 원의 지름입니다. 공구 지름과 비교합니다.')
        if '입력 절삭 날 길이 (mm)' in table:
            formats['입력 절삭 날 길이 (mm)'] = st.column_config.Column(
                help='공구 전체 길이가 아니라 재료를 깎는 날이 있는 부분의 길이입니다.')
        st.dataframe(table, column_config=formats, hide_index=True, width="stretch")
        measured_rows = displayed_finding["measurements"].get("cylindrical_faces", []) + displayed_finding["measurements"].get("pockets", [])
        if any(r.get("numerical_boundary_comparisons") for r in measured_rows):
            st.info("기준과 수치상 같은 경계값이 있습니다. 계산 오차 범위에서는 초과로 판정하지 않습니다.")
    if finding.get("limitations"):
        with st.expander("측정 방법·확인하지 못한 범위"):
            for limitation in finding["limitations"]:
                st.write(limitation)


def selected_location_finding(finding, location):
    """Filter displayed measurements with the same CAD ID as the highlighted view."""
    if location == "all":
        return finding
    measures = finding["measurements"]
    selected = dict(measures)
    for key in ("cylindrical_faces", "pockets"):
        if key in measures:
            selected[key] = [row for row in measures[key]
                             if str(row.get("face_id", row.get("floor_face_id"))) == str(location)]
    return {**finding, "measurements": selected}
