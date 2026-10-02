"""Machining review controls and evidence-linked result components."""
from __future__ import annotations

import html
import json

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


@st.cache_data(max_entries=4, show_spinner=False)
def cached_machining(fingerprint, profile, direction, visibility, code_revision, _model):
    report = review_machining(_model, MachiningProfile(**profile), direction, visibility=visibility)
    report["code_revision"] = code_revision
    return report


def machining_html(report):
    esc = lambda x: html.escape(str(x))
    sections = []
    for finding in report["findings"]:
        rows = feature_rows(finding)
        table = (pd.DataFrame(rows).to_html(index=False, escape=True) if rows else '')
        sections.append(f'<section><h2>{esc(finding["title"])}</h2><p><b>{esc(STATUS[finding["status"]])}</b></p><p>{esc(finding["reason"])}</p>'
            f'<p><strong>다음 행동:</strong> {esc(finding["action"])}</p>'
            f'{table}<details><summary>계산 원자료</summary><pre>{esc(json.dumps(finding["measurements"], ensure_ascii=False, indent=2))}</pre></details>'
            f'<p>{esc(" / ".join(finding["limitations"]))}</p></section>')
    sources = ''.join(f'<li><a href="{esc(s["url"])}">{esc(s["title"])}</a></li>' for s in report["sources"])
    return (f'<!doctype html><html lang="ko"><meta charset="utf-8"><title>절삭 설계 검토</title>'
        f'<style>body{{max-width:1050px;margin:40px auto;padding:0 24px;font-family:system-ui;line-height:1.7}}'
        f'section{{border-top:1px solid #cbd5e1;padding:16px 0}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}'
        f'table{{border-collapse:collapse;display:block;overflow-x:auto}}th,td{{padding:8px;border:1px solid #cbd5e1}}</style>'
        f'<h1>절삭 설계 검토</h1><p>{esc(report["input"].get("filename", ""))}</p>'
        f'<p>선택 공구축: {esc(report["direction"])} / 검토 시각: {esc(report["created_utc"])}</p>'
        f'<p>축은 부품에서 공구 쪽을 향합니다. 공구는 반대 방향으로 진입합니다. 기하 검토이며 실제 가공 성공 판정이 아닙니다.</p>'
        f'<h2>검토 조건</h2><pre>{esc(json.dumps(report["profile"],ensure_ascii=False,indent=2))}</pre>'
        + ''.join(sections) + f'<h2>별도 확인이 필요한 범위</h2><p>{esc(" / ".join(report["unassessed"]))}</p>'
        f'<h2>근거</h2><ul>{sources}</ul><p>입력 SHA: {esc(report["input"].get("source_sha256"))}<br>'
        f'코드 SHA: {esc(report.get("code_revision"))}</p></html>')


def feature_rows(finding):
    measures = finding["measurements"]
    rows = measures.get("cylindrical_faces") or measures.get("pockets")
    if not rows:
        if finding["id"] == "cnc_visibility" and measures.get("sample_state_counts"):
            return [{"표본 분류": title, "표본 수": measures["sample_state_counts"].get(key, 0), "해석·다음 행동": action}
                    for key, (title, action, _, _) in VISIBILITY.items()]
        return []
    labels = {"face_id": "CAD 면", "diameter_mm": "지름 (mm)", "cylindrical_length_mm": "원통 구간 길이 (mm)",
        "length_diameter_ratio": "구간 길이 / 지름", "axis_aligned": "선택 축과 나란함",
        "tool_too_large": "공구 지름 > 특징 지름", "segment_exceeds_reach": "원통 구간 > 도달 길이",
        "exceeds_ratio": "입력 비율 기준 초과", "radius_mm": "오목면 반경 (mm)",
        "floor_face_id": "바닥 CAD 면", "width_mm": "바닥 폭 (mm)", "length_mm": "바닥 길이 (mm)",
        "wall_height_mm": "벽 높이 (mm)", "width_too_small": "공구보다 좁음",
        "exceeds_flute_length": "벽 높이 > 날 길이", "exceeds_reach": "벽 높이 > 도달 길이"}
    return [{labels[k]: ("미입력·미비교" if v is None else "예" if v is True else "아니오" if v is False else v)
                for k, v in r.items() if k in labels} for r in rows]


def machining_figure(model, report=None, finding_id="", *, direction=(0,0,1)):
    fig = model_figure(model, report, finding_id, axis_label="공구가 오는 쪽", axis_vector=direction)
    for trace in fig.data:
        if trace.type == "mesh3d":
            trace.flatshading = True
    return fig


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
            tilt = st.number_input("모델 +Z에서 기울기 (°)", min_value=0., max_value=180., value=0., key="cnc_tilt", persist_state="session")
            azimuth = st.number_input("모델 +X에서 방위각 (°)", min_value=0., max_value=360., value=0., key="cnc_azimuth", persist_state="session")
            direction = tuple(direction_from_angles(tilt, azimuth))
        else:
            direction = axes[label]
        st.caption("화살표는 부품에서 공구 쪽을 향합니다. 공구는 반대 방향으로 진입합니다.")
        with st.form("cnc_conditions"):
            st.caption("원통형 엔드밀의 치수입니다. 비워 두면 해당 공구 비교를 보류합니다.")
            diameter = st.number_input("엔드밀 지름 (mm)", min_value=.001, value=None, key="cnc_diameter", persist_state="session")
            flute = st.number_input("날 길이 (mm)", min_value=.001, value=None, key="cnc_flute", persist_state="session")
            reach = st.number_input("도달 길이 · 공구 끝~홀더 (mm)", min_value=.001, value=None, key="cnc_reach", persist_state="session")
            with st.expander("재료·장비·근거와 추가 기준"):
                machine = st.text_input("절삭 장비", value="미확정", key="cnc_machine", persist_state="session")
                material = st.text_input("절삭 재료", value="미확정", key="cnc_material", persist_state="session")
                ratio = st.number_input("원통 구간 길이/지름 검토 기준 (선택)", min_value=.01, value=None, key="cnc_ratio", persist_state="session")
                basis = st.text_input("공구·기준의 출처", value="사용자 지정 공구·탐색 조건; 실제 가공 검증 전", key="cnc_basis", persist_state="session")
            visibility = st.checkbox("선택 방향에서 가려진 표면도 확인", value=False, key="cnc_visibility", persist_state="session")
            submitted = st.form_submit_button("절삭 설계 검토", type="primary", width="stretch")
        st.caption("현재는 단일 STEP의 원통면·제한된 직사각 포켓과 표면 표본을 검토합니다.")
    profile = MachiningProfile(machine, material, diameter, flute, reach, ratio, basis)
    settings = json_bytes([model.fingerprint, profile.to_dict(), direction, visibility, code_revision]).decode()
    st.caption("고정축 밀링의 기하 검토 · 위치와 공구 조건을 비교합니다.")
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
        st.plotly_chart(machining_figure(model, direction=direction), width="stretch")
        st.caption("새 형상·조건에는 이전 검토 결과를 표시하지 않습니다.")
        return
    attention = [f for f in report["findings"] if f["status"] == "attention"]
    unknown = [f for f in report["findings"] if f["status"] == "unknown"]
    if attention:
        st.warning(f"먼저 확인할 항목 {len(attention)}개가 있습니다. 아래에서 항목을 선택하면 위치와 수정 방향을 볼 수 있습니다.")
    elif unknown:
        st.info("아래 항목의 측정 결과를 확인하세요. 공구 조건 또는 실행하지 않은 검토가 남아 있어 가공 가능 여부는 확정하지 않습니다.")
    else:
        st.info("검사한 범위에서 선택 조건과의 충돌 후보를 찾지 못했습니다. 아래 검토 범위와 별도 확인 항목을 확인하세요.")
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
    rows = feature_rows(finding)
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        if selected != "cnc_visibility":
            st.caption("‘아니오’는 해당 치수 비교에서 초과하지 않았다는 뜻입니다. 입구·전체 진입 깊이·공구 경로는 별도 확인이 필요합니다.")
    if selected == "cnc_visibility" and report.get("visibility"):
        measures = report["visibility"]["measurements"]
        omitted = measures.get("omitted_face_count")
        st.caption(f"미표본 면: {omitted:,}개. 표시한 점에서만 검사했습니다. 면 전체의 접근성이나 성공률이 아닙니다."
                   if omitted is not None else "표본 범위를 확정하지 못했습니다. 가림이 없는 것으로 해석하지 않습니다.")
        state = st.selectbox("표시할 표본", ["all", *VISIBILITY], format_func=lambda key: "모든 표본" if key == "all" else VISIBILITY[key][0], key="cnc_sample_state")
        st.plotly_chart(visibility_figure(model, report, direction, state), width="stretch")
    else:
        st.plotly_chart(machining_figure(model, report, selected, direction=direction), width="stretch")
        st.caption("주황 면은 선택 항목의 확인 위치입니다. 나머지 회색 면의 가공 가능성을 보증하지 않습니다.")
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
        for source in report["sources"]:
            st.markdown(f"[{source['title']}]({source['url']})")
        st.caption("형상·공구 검토의 근거입니다. 제조사 서비스의 권장값을 보편적인 한계로 사용하지 않습니다.")
        with st.container(horizontal=True):
            st.download_button("절삭 검토 JSON", json_bytes(report), "machining_review.json", "application/json")
            st.download_button("절삭 검토 HTML", machining_html(report), "machining_review.html", "text/html")
            st.download_button("입력 형상 원본", data, filename, "application/octet-stream")
    st.caption("가공 경로·고정·절삭 물리 검증은 포함하지 않습니다. 계산 완료는 실제 가공 성공 판정이 아닙니다.")
