"""Machining review controls and evidence-linked result components."""
from __future__ import annotations

import html
import json
from urllib.parse import urlsplit

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from amdfm.models import json_bytes
from amdfm.orientation import direction_from_angles
from amdfm.presentation import model_figure
from .machining import MachiningProfile, review_machining


STATUS = {"attention": "조건 확인·수정 검토", "unknown": "판단에 필요한 정보 부족",
          "observed": "명시된 범위의 측정 완료", "not_detected": "인식 범위 내 미검출"}
VISIBILITY = {
    "occluded": ("앞이 가려진 표본", "다른 방향·가공 순서를 검토하세요.", "#c65102", "diamond"),
    "back_facing": ("공구 반대쪽을 향한 표본", "다른 셋업이 필요한 면인지 확인하세요.", "#663399", "square"),
    "tangent": ("공구축과 평행한 면의 표본", "측면 밀링·공구 반경을 별도 확인하세요.", "#52606d", "cross"),
    "unknown": ("계산 미확정 표본", "경계·시간 제한 등 원인을 확인하세요.", "#111827", "x"),
    "visible": ("직선이 가려지지 않은 표본", "공구·홀더까지 통과하는지는 아직 미확인입니다.", "#1476b8", "circle"),
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
def cached_machining(fingerprint, profile, direction, visibility, code_revision, _model):
    report = review_machining(_model, MachiningProfile(**profile), direction, visibility=visibility)
    report["code_revision"] = code_revision
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
    return ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>절삭 설계 검토</title><style>body{max-width:1050px;margin:40px auto;padding:0 24px;font-family:system-ui;line-height:1.7}'
        'section{border-top:1px solid #cbd5e1;padding:16px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}'
        'table{border-collapse:collapse;display:block;overflow-x:auto;max-width:100%}th,td{padding:8px;border:1px solid #cbd5e1}'
        'svg{max-width:640px;width:100%;height:auto}p{overflow-wrap:anywhere}</style></head><body>'
        f'<h1>절삭 설계 검토</h1><p>{esc(report["input"].get("filename", ""))}</p>'
        f'<p>선택 공구축 (모델 X, Y, Z): {esc(report["direction"])} / 검토 시각: {esc(report["created_utc"])}</p>'
        '<p>축은 부품에서 공구 쪽을 향합니다. 공구는 반대 방향으로 진입합니다. 기하 검토이며 실제 가공 성공 판정이 아닙니다.</p>'
        + illustration + f'<h2>이 결과에 적용한 조건</h2>{table(conditions)}'
        '<p>아래 표의 ‘아니오’는 해당 국소 치수 비교에서 초과하지 않았다는 뜻입니다. 수치 경계는 계산 오차 범위에서 같은 값이며 제조 공차나 가공 여유가 아닙니다. 입구·전체 진입 깊이·실제 경로는 별도 확인 대상입니다.</p>'
        f'<details><summary>조건 원자료</summary><pre>{esc(json.dumps(profile, ensure_ascii=False, indent=2))}</pre></details>'
        + ''.join(sections) + f'<h2>별도 확인이 필요한 범위</h2><p>{esc(" / ".join(report["unassessed"]))}</p>'
        f'<h2>근거</h2><ul>{sources}</ul><p>입력 SHA: {esc(report["input"].get("source_sha256"))}<br>'
        f'코드 SHA: {esc(report.get("code_revision"))}</p></body></html>')


def feature_rows(finding, profile=None):
    """Keep dimensions and explicit comparison conditions beside each other."""
    measures = finding["measurements"]
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
        "exceeds_flute_length": "벽 높이 > 날 길이", "exceeds_reach": "벽 높이 > 돌출 길이"}
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
            elif finding["id"] == "cnc_rectangular_pockets":
                for key, label in (("tool_diameter_mm", "입력 공구 지름 (mm)"),
                                   ("flute_length_mm", "입력 날 길이 (mm)"),
                                   ("reach_mm", "입력 돌출 길이 (mm)")):
                    item[label] = display(profile.get(key))
        shown.append(item)
    return shown


def machining_figure(model, report=None, finding_id="", *, direction=(0,0,1), cad_face_ids=None):
    original = next((f for f in report["findings"] if f["id"] == finding_id), None) if report else None
    if report is not None and cad_face_ids is not None:
        # Selection changes the view only, never the report or its conclusions.
        face_indices = (np.flatnonzero(np.isin(model.face_ids, cad_face_ids)).tolist()
                        if model.face_ids is not None else [])
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
        elif "diameter_mm" in row:
            label = f"원통 지름 {row['diameter_mm']:.6g} mm · 구간 길이 {row['cylindrical_length_mm']:.6g} mm"
        else:
            label = f"포켓 바닥 폭 {row['width_mm']:.6g} mm · 벽 높이 {row['wall_height_mm']:.6g} mm"
        result[str(face_id)] = f"CAD 면 {face_id} · {label}"
    for face_id in measures.get("unresolved_floor_face_ids", []):
        result.setdefault(str(face_id), f"CAD 면 {face_id} · 포켓 치수 미확정 위치")
    if not result:
        for face_id in finding.get("cad_face_ids", []):
            result[str(face_id)] = f"CAD 면 {face_id} · 추가 확인 위치"
    return result


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
        axes = {"+Z · 위쪽에서": (0,0,1), "−Z · 아래쪽에서": (0,0,-1), "+X": (1,0,0), "−X": (-1,0,0), "+Y": (0,1,0), "−Y": (0,-1,0)}
        label = st.selectbox("공구가 오는 방향", [*axes, "직접 각도 입력"], key="cnc_direction", persist_state="session")
        if label == "직접 각도 입력":
            tilt = st.number_input("모델 +Z에서 기울기 (°)", min_value=0., max_value=180., value=0., step=1., format="%.6f", key="cnc_tilt", persist_state="session")
            azimuth = st.number_input("모델 +X에서 방위각 (°)", min_value=0., max_value=360., value=0., step=1., format="%.6f", key="cnc_azimuth", persist_state="session")
            direction = tuple(direction_from_angles(tilt, azimuth))
        else:
            direction = axes[label]
        st.caption("화살표는 부품에서 공구 쪽을 향합니다. 공구는 반대 방향으로 진입합니다.")
        with st.form("cnc_conditions"):
            st.caption("원통형 엔드밀의 치수입니다. 비워 두면 해당 공구 비교를 보류합니다.")
            diameter = st.number_input("엔드밀 지름 (mm)", min_value=.001, value=None, step=.1, format="%.4f", key="cnc_diameter", persist_state="session")
            flute = st.number_input("날 길이 (mm)", min_value=.001, value=None, step=.1, format="%.4f", key="cnc_flute", persist_state="session",
                                    help="실제 절삭날의 축방향 길이입니다. 공구 전체 길이나 감소 목부 길이와 다릅니다.")
            reach = st.number_input("장착 후 돌출 길이 · 끝~홀더 (mm)", min_value=.001, value=None, step=.1, format="%.4f", key="cnc_reach", persist_state="session",
                                    help="장착한 공구 끝에서 홀더 앞면까지의 거리입니다. 카탈로그 Reach/LBS와 다를 수 있으며, 홀더 형상은 이 검토에 포함하지 않습니다.")
            with st.expander("재료·장비·근거와 추가 기준"):
                machine = st.text_input("절삭 장비", value="미확정", key="cnc_machine", persist_state="session")
                material = st.text_input("절삭 재료", value="미확정", key="cnc_material", persist_state="session")
                st.caption("장비·재료명은 조건 기록용입니다. 재료별 절삭력·처짐 계산에는 사용하지 않습니다.")
                ratio = st.number_input("원통 구간 길이/지름 검토 기준 (선택)", min_value=.01, value=None, step=.1, format="%.4f", key="cnc_ratio", persist_state="session",
                                        help="선택한 원통면 구간의 길이÷지름과 비교할 사용자 기준입니다. 전체 홀 깊이가 아니며, 보편적인 합격선은 없습니다. 기준 출처를 함께 기록하세요.")
                basis = st.text_input("공구·기준의 출처", value="사용자 지정 공구·탐색 조건; 실제 가공 검증 전", key="cnc_basis", persist_state="session")
            visibility = st.checkbox("선택 방향에서 가려진 표면도 확인", value=False, key="cnc_visibility", persist_state="session")
            submitted = st.form_submit_button("절삭 설계 검토", type="primary", width="stretch")
        st.caption("입력한 새 공구 조건은 위 실행 버튼을 누르면 결과에 적용됩니다.")
        st.caption("현재는 단일 STEP의 원통면·제한된 직사각 포켓과 표면 표본을 검토합니다.")
    profile = MachiningProfile(machine, material, diameter, flute, reach, ratio, basis)
    settings = json_bytes([model.fingerprint, profile.to_dict(), direction, visibility, code_revision]).decode()
    st.caption("원통형 엔드밀 · 고정축 밀링의 기하 검토 · 위치와 공구 조건을 비교합니다.")
    st.caption("포켓 치수는 직선 4변 바닥과 같은 높이의 네 수직 벽에서만 비교합니다. 다른 포켓·자유곡면은 미검토입니다.")
    if submitted:
        try:
            with st.spinner("CAD 특징과 선택 공구 조건을 비교하는 중…"):
                report = cached_machining(model.fingerprint, profile.to_dict(), direction, visibility, code_revision, model)
            st.session_state["cnc_report"] = report
            st.session_state["cnc_report_settings"] = settings
        except (ValueError, MemoryError) as exc:
            st.error(str(exc))
            return
    report = st.session_state.get("cnc_report") if st.session_state.get("cnc_report_settings") == settings else None
    if report is None:
        st.info("공구 치수를 알고 있다면 왼쪽에 입력하고 ‘절삭 설계 검토’를 실행하세요. 비워 두어도 CAD 특징은 측정할 수 있습니다.")
        st.plotly_chart(machining_figure(model, direction=direction), width="stretch", config={"scrollZoom": False})
        st.caption("새 형상·조건에는 이전 검토 결과를 표시하지 않습니다.")
        return
    attention = [f for f in report["findings"] if f["status"] == "attention"]
    unknown = [f for f in report["findings"] if f["status"] == "unknown"]
    if attention:
        st.warning(f"먼저 확인할 항목 {len(attention)}개: " + " / ".join(f["title"] for f in attention))
    elif unknown:
        st.info("아래 항목의 측정 결과를 확인하세요. 공구 조건 또는 실행하지 않은 검토가 남아 있어 가공 가능 여부는 확정하지 않습니다.")
    else:
        st.info("검사한 범위에서 선택 조건과의 충돌 후보를 찾지 못했습니다. 아래 검토 범위와 별도 확인 항목을 확인하세요.")
    if unknown:
        st.caption("정보·검토가 더 필요한 항목: " + " / ".join(f["title"] for f in unknown))
    st.markdown("**이 결과에 적용된 공구 조건**")
    columns = st.columns(3)
    for column, title, key in zip(columns, ["엔드밀 지름", "날 길이", "장착 후 돌출 길이"],
                                  ["tool_diameter_mm", "flute_length_mm", "reach_mm"]):
        value = report["profile"].get(key)
        column.metric(title, "미입력" if value is None else f"{value:,.6g} mm")
    st.caption("공구가 오는 방향: " + ", ".join(f"{v:.6g}" for v in report["direction"]) + " (모델 좌표)")
    # Keep widget options and labels stable. Reordering options by severity on
    # the same key can leave the browser's selected index on a different item.
    lookup = {f["id"]: f for f in report["findings"]}
    if (st.session_state.get("cnc_finding_model") != model.fingerprint
            or st.session_state.get("cnc_finding") not in lookup):
        st.session_state["cnc_finding"] = (attention or unknown or report["findings"])[0]["id"]
        st.session_state["cnc_finding_model"] = model.fingerprint
    selected = st.selectbox("확인할 항목", list(lookup), format_func=lambda k: lookup[k]["title"], key="cnc_finding")
    finding = lookup[selected]
    with st.container(border=True):
        st.markdown(f"**{finding['title']}**")
        st.caption(STATUS[finding["status"]])
        st.write(finding["reason"])
        st.markdown(f"**다음 행동** · {finding['action']}")
    rows = feature_rows(finding, report["profile"])
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        if selected != "cnc_visibility":
            st.caption("‘아니오’는 해당 치수 비교에서 초과하지 않았다는 뜻입니다. 입구·전체 진입 깊이·공구 경로는 별도 확인이 필요합니다.")
        measured_rows = finding["measurements"].get("cylindrical_faces", []) + finding["measurements"].get("pockets", [])
        if any(r.get("numerical_boundary_comparisons") for r in measured_rows):
            st.info("기준과 수치상 같은 경계값이 있습니다. 소수점 계산 오차 범위에서는 초과로 판정하지 않습니다. 공구 공차와 실제 가공 여유는 별도로 확인하세요.")
    if selected == "cnc_visibility" and report.get("visibility"):
        measures = report["visibility"]["measurements"]
        omitted = measures.get("omitted_face_count")
        st.caption(f"미표본 면: {omitted:,}개. 표시한 점에서만 검사했습니다. 면 전체의 접근성이나 성공률이 아닙니다."
                   if omitted is not None else "표본 범위를 확정하지 못했습니다. 가림이 없는 것으로 해석하지 않습니다.")
        state = st.selectbox("표시할 표본", ["all", *VISIBILITY], format_func=lambda key: "모든 표본" if key == "all" else VISIBILITY[key][0], key="cnc_sample_state")
        st.plotly_chart(visibility_figure(model, report, direction, state), width="stretch", config={"scrollZoom": False})
    else:
        locations = feature_locations(finding)
        highlighted = None
        if locations:
            location_context = (model.fingerprint, selected, tuple(locations))
            if st.session_state.get("cnc_location_context") != location_context:
                st.session_state["cnc_location"] = "all"
                st.session_state["cnc_location_context"] = location_context
            location = st.selectbox("확인할 위치", ["all", *locations],
                format_func=lambda k: "이 항목의 측정·확인 위치 모두" if k == "all" else locations[k], key="cnc_location")
            highlighted = [int(k) for k in locations] if location == "all" else [int(location)]
        st.plotly_chart(machining_figure(model, report, selected, direction=direction, cad_face_ids=highlighted), width="stretch", config={"scrollZoom": False})
        st.caption("파란색: 선택한 측정·추가 확인 위치. 주황색: 이 항목에서 조건 확인이 필요한 위치. 실제 판단은 표의 비교값과 다음 행동을 함께 확인하세요."
                   if locations else "이 항목에는 별도로 표시할 CAD 위치가 없습니다. 회색은 가공 통과 표시가 아닙니다.")
    with st.expander("이 결과가 확인한 범위"):
        for limitation in finding["limitations"]:
            st.write(limitation)
        st.write("**아직 별도 확인이 필요한 내용**")
        for item in report["unassessed"]:
            st.write(f"• {item}")
    with st.expander("모든 항목과 계산 원자료"):
        st.dataframe(pd.DataFrame([{"항목": f["title"], "결과": f["reason"], "다음 행동": f["action"]} for f in report["findings"]]), hide_index=True)
        st.json(report)
    with st.expander("근거와 내보내기"):
        st.caption("각 문헌은 아래에 적힌 계산의 이유와 범위에 연결됩니다. 문헌을 인용했다는 사실만으로 해당 알고리즘의 구현이나 실제 가공 성공이 검증되는 것은 아닙니다.")
        for source in report["sources"]:
            url = _source_web_url(source)
            st.markdown(f"[{source['title']}]({url})" if url else f"**{source['title']}**")
            for label, value in _source_details(source):
                if label == "이 검토에서 사용하는 이유와 범위":
                    st.write(f"{label}: {value}")
                else:
                    st.caption(f"{label}: {value}")
        st.caption("형상·공구 검토의 근거입니다. 제조사 서비스의 권장값을 보편적인 한계로 사용하지 않습니다.")
        with st.container(horizontal=True):
            st.download_button("절삭 검토 JSON", json_bytes(report), "machining_review.json", "application/json")
            st.download_button("절삭 검토 HTML", machining_html(report, model), "machining_review.html", "text/html")
            st.download_button("입력 형상 원본", data, filename, "application/octet-stream")
    st.caption("가공 경로·고정·절삭 물리 검증은 포함하지 않습니다. 계산 완료는 실제 가공 성공 판정이 아닙니다.")
