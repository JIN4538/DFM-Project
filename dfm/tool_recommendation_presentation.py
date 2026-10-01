"""Shared, compact presentation of geometry-derived tool inputs."""
from __future__ import annotations

import html


TOOL_LABELS = {"tool_diameter_mm": "엔드밀 지름", "flute_length_mm": "날 길이", "reach_mm": "돌출 길이"}


def tool_summary(report):
    recommendation = report.get("tool_recommendation") or {}
    automatic = set(recommendation.get("automatic_fields", []))
    if not automatic:
        return None
    rows = []
    for key, label in TOOL_LABELS.items():
        value = report.get("profile", {}).get(key)
        origin = "자동" if key in automatic else "입력" if value is not None else "미정"
        rows.append(dict(field=key, label=label, origin=origin,
                         value="미정" if value is None else f"{value:,.6g} mm"))
    return dict(title="검토에 적용한 공구", rows=rows)


def tool_summary_html(report):
    summary = tool_summary(report)
    if not summary:
        return ""
    esc = lambda text: html.escape(str(text), quote=True)
    rows = " · ".join(f"{esc(row['label'])} <b>{esc(row['value'])}</b> ({esc(row['origin'])})" for row in summary["rows"])
    return f"<p><b>{esc(summary['title'])}</b><br>{rows}</p>"


def render_tool_summary(report):
    import streamlit as st

    summary = tool_summary(report)
    if not summary:
        return
    st.markdown("**" + summary["title"] + "**")
    for column, row in zip(st.columns(3), summary["rows"]):
        column.metric(row["label"] + " · " + row["origin"], row["value"])


def render_tool_evidence(report):
    import streamlit as st
    import pandas as pd

    recommendation = report.get("tool_recommendation")
    if not recommendation:
        return
    with st.expander("공구 자동 제안 근거"):
        assumptions = recommendation.get("assumptions", {})
        fraction = assumptions.get("diameter_fraction")
        allowance = assumptions.get("length_allowance_mm")
        if fraction is not None and allowance is not None:
            st.write(f"지름: 측정 상한의 {fraction * 100:g}% · 길이: 아래 비교값에 {allowance:g} mm 여유")
            st.caption("추가 기준·출처에서 변경할 수 있는 앱 설정입니다.")
            st.caption("확인한 구멍은 입구부터 끝까지의 깊이, 나머지는 특징 구간·형상 상단 거리를 사용합니다.")
        constraints = recommendation.get("constraints", [])
        if constraints:
            st.dataframe(pd.DataFrame([{
                "CAD 면": row.get("cad_face_id"),
                "지름 상한 (mm)": row.get("diameter_max_mm"),
                "날 길이 비교값 (mm)": row.get("flute_min_mm"),
                "구간 길이 (mm)": row.get("reach_min_mm"),
                "상단~특징 거리 (mm)": row.get("reach_reference", {}).get("measured_envelope_distance_mm"),
                "길이 기준": '구멍 입구~끝' if row.get('length_basis')=='verified_hole_depth' else '원통 구간·벽 높이',
            } for row in constraints]), hide_index=True, width="stretch")
        reasons = list(dict.fromkeys(row.get("reason", "") for row in recommendation.get("unresolved", [])))
        for reason in reasons:
            if reason:
                st.write(reason)
        st.json(recommendation, expanded=False)
