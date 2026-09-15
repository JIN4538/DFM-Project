"""User-facing section explanation; keeps original measurements unchanged."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .section_summary import summarize_sections


def render_section_result(detail, process, mesh_volume_mm3):
    summary = summarize_sections(detail, process, mesh_volume_mm3)
    method = {'events':'형상 변화 기준','uniform':'균등 간격','auto':'자동 요청 · 계산 방법 미확정'}.get(
        detail.get('sampling'),'계산 방법 미확정')
    with st.container(border=True):
        if summary["completion_level"] == "warning":
            st.warning(summary["completion_title"])
        else:
            st.info(summary["completion_title"])
        st.write(summary["completion_text"])
        st.caption(f"{method} 결과")
        if summary['selection_note']:
            st.info(summary['selection_note'])
        st.markdown(f"**형상에서 확인한 내용** · {summary['change_text']}")
        st.write(summary["interpretation"])
        st.markdown(f"**다음에 할 일** · {summary['next_step']}")
        if summary["reason"]:
            st.write(summary["reason"])
        partial=summary['partial_volume']
        if partial['available']:
            cols=st.columns(2)
            cols[0].metric('확인한 구간의 부피 합',f"{partial['known_mm3']:,.8g} mm³")
            cols[1].metric('빠진 높이 구간의 부피 기여 상한',
                           '미확정' if partial['omitted_envelope_mm3'] is None else f"{partial['omitted_envelope_mm3']:.6g} mm³")
            st.caption(partial['explanation'])

    rows = detail.get("rows") or []
    if rows:
        # Reset the inspected location only when a different result is attached.
        identity = (detail.get("fingerprint"), detail.get("sampling"),
                    detail.get("sample_count"), detail.get("elapsed_seconds"),
                    str(detail.get("direction")), len(rows))
        if st.session_state.get("section_view_result") != identity:
            st.session_state["section_view_result"] = identity
            st.session_state["section_index"] = summary["default_row_index"] or 0
        if st.session_state.get("section_index") not in range(len(rows)):
            st.session_state["section_index"] = summary["default_row_index"] or 0

        change = summary["change"]
        if change and st.button("변화가 가장 크게 관측된 두 단면 보기", key="show_section_change"):
            st.session_state["section_index"] = change["row_index"]

        def label(i):
            row = rows[i]
            area = f"{row['area_mm2']:,.4g} mm²" if row.get("area_mm2") is not None else "미확정"
            return f"{i + 1}번 · 높이 {row['z_mm']:.4g} mm · 재료 면적 {area}"

        chosen = st.selectbox("살펴볼 단면 · 높이와 넓이로 선택", list(range(len(rows))),
                              format_func=label, key="section_index")
        current = rows[chosen]
        previous = rows[chosen - 1] if chosen > 0 else None
        comparable = (previous is not None and current.get("complete") and previous.get("complete")
                      and current.get("symmetric_change_from_previous_mm2") is not None)
        if comparable:
            st.write(f"높이 {previous['z_mm']:.4g} mm와 {current['z_mm']:.4g} mm를 비교합니다. "
                     f"재료 면적은 {previous['area_mm2']:,.4g} → {current['area_mm2']:,.4g} mm²입니다.")
            st.caption("단면 사이에서 정확히 어느 높이에 변화가 생겼는지는 이 두 표본만으로 확정하지 않습니다.")

        if current.get("outlines") or (comparable and previous.get("outlines")):
            figure = go.Figure()
            outlines = [("현재 단면", current, "#c46b19", "solid")]
            if comparable:
                outlines.insert(0, ("이전 단면", previous, "#315f78", "dash"))
            for title, row, color, dash in outlines:
                for i, ring in enumerate(row.get("outlines", [])):
                    figure.add_trace(go.Scatter(
                        x=[p[0] for p in ring], y=[p[1] for p in ring], mode="lines",
                        name=f"{title} · {row['z_mm']:.4g} mm", legendgroup=title,
                        showlegend=i == 0, line=dict(color=color, dash=dash, width=2),
                    ))
            figure.update_layout(height=340, xaxis_title="빌드 X (mm)", yaxis_title="빌드 Y (mm)",
                                 yaxis=dict(scaleanchor="x", scaleratio=1),
                                 margin=dict(l=20, r=20, t=15, b=25),
                                 legend=dict(orientation="h", y=-.22))
            st.plotly_chart(figure, width="stretch")
            st.caption("파란 점선: 이전 단면 · 주황 실선: 현재 단면. 색은 두 단면을 구분하며 위험 등급이 아닙니다.")
        if not current.get("complete"):
            st.warning("이 높이의 재료 단면은 확정되지 않았습니다. 아래 전체 측정값에서 누락 사유를 확인하세요.")
        elif not current.get("outlines_complete"):
            st.caption("이 단면의 윤곽은 표시 점 수 한도로 생략했습니다. 계산된 면적에는 전체 윤곽을 사용했습니다.")

        st.markdown("**높이에 따른 재료 단면적**")
        st.caption("점 하나가 실제 계산한 단면 하나입니다. 점 사이의 모양을 추정하는 연결선은 표시하지 않습니다.")
        chart_rows = pd.DataFrame([
            {"높이 (mm)": row["z_mm"], "재료 단면적 (mm²)": row.get("area_mm2"),
             "단면": "선택한 단면" if i == chosen else "다른 단면"}
            for i, row in enumerate(rows) if row.get("complete") and row.get("area_mm2") is not None
        ])
        if not chart_rows.empty:
            st.scatter_chart(chart_rows, x="높이 (mm)", y="재료 단면적 (mm²)",
                             color="단면", size=90, height=260)

        with st.expander("전체 측정값 · 항목 뜻과 미확정 사유"):
            st.write("면적은 재료가 차지한 넓이입니다. 둘레에는 내부 구멍의 경계도 포함합니다. "
                     "앞 단면과 달라진 넓이는 두 모양을 겹쳤을 때 겹치지 않는 부분의 넓이이며, "
                     "면적 증가량이나 위험 점수가 아닙니다.")
            st.write("영역 수는 단면에서 떨어진 재료 덩어리 수, 내부 윤곽 수는 빈 공간의 경계 수입니다. "
                     "면적/둘레의 단위는 mm이며 벽두께·박리력이 아닙니다. 빈 값은 미확정 또는 비교 대상 없음입니다.")
            st.dataframe(pd.DataFrame([
                {"단면": i + 1, "높이 (mm)": row["z_mm"], "면적 (mm²)": row.get("area_mm2"),
                 "둘레 (mm)": row.get("perimeter_mm"), "면적/둘레 (mm)": row.get("area_per_perimeter_mm"),
                 "앞 단면과 달라진 넓이 (mm²)": row.get("symmetric_change_from_previous_mm2"),
                 "영역 수": row.get("material_regions"), "내부 윤곽 수": row.get("internal_loops"),
                 "계산 상태": "계산됨" if row.get("complete") else "미확정"}
                for i, row in enumerate(rows)
            ]), hide_index=True)
            unresolved = [{"단면": i + 1, "진단": row.get("diagnostics", {})}
                          for i, row in enumerate(rows) if not row.get("complete")]
            if unresolved:
                st.json(unresolved, expanded=False)

    with st.expander("계산 확인 · 부피 검산과 적용 범위"):
        volume = summary["volume"]
        if volume["available"]:
            display = volume["display"]
            if display.startswith("<"):
                display = display[1:] + " 미만"
            st.write(f"두 계산 방법의 부피 차이: **{display}**")
            st.write(f"단면으로 계산한 부피 {volume['section_volume_mm3']:,.6g} mm³ · "
                     f"메시로 계산한 부피 {volume['mesh_volume_mm3']:,.6g} mm³")
            st.caption(f"원본 상대차: {volume['relative_difference_percent']:.16g}%")
        st.write(volume["explanation"])
        st.write("형상 변화 기준은 형상 구간마다 계산 단면 두 개를 배치합니다. "
                 "단순한 부품은 단면 수가 적어도 전체 계산 구간을 다룰 수 있습니다. "
                 "균등 간격은 일정 간격의 표본이며 얇은 높이 구간을 놓칠 수 있습니다. "
                 "어느 방법이든 관측한 최대 면적을 부품 전체의 최대 면적이라고 보장하지 않습니다.")
