"""Compact conclusions from a local, rule-trained model and verified evidence."""
from __future__ import annotations

import streamlit as st

from .advisor import prioritize_actions


def ordered_items(analysis, context=None):
    """Keep input constraints and observed issues ahead of missing information."""
    rows = []
    for item in analysis.get("items", []):
        if item.get("state") not in ("confirmed", "review"):
            continue
        row = dict(item)
        row.update(id=item["finding_id"],
                   action_kind="candidate" if item["state"] == "confirmed" else "condition")
        rows.append(row)
    return prioritize_actions(rows, context or {})


def render_learned_review(report, on_select=None, key_prefix="am"):
    """Return what was exposed so callers can retain unsupported rule findings.

    Analyze afresh: attaching a new wall/layer result must not leave the previous
    prediction on screen or in the exported report. The small model is cached by
    its checked artifact identity in the inference module.
    """
    from .learned_review import analyze_report

    analysis = analyze_report(report)
    report["learned_review"] = analysis
    if analysis.get("status") == "unavailable":
        st.info("수치 기준으로 검토했습니다.")
        with st.expander("AI 상태 확인"):
            st.write(analysis.get("note") or "학습 모델과 검토 조건을 확인하세요.")
        return {"rendered": False, "displayed_ids": []}

    st.subheader("항목별 검토")
    items = ordered_items(analysis, report.get("review_context"))
    confirmed = sum(x.get("state") == "confirmed" for x in analysis.get("items", []))
    covered = {x["finding_id"] for x in analysis.get("items", [])}
    pending = sum(x.get("state") == "review" for x in analysis.get("items", []))
    pending += sum(x.get("status") in ("attention", "unknown") and x.get("id") not in covered
                   for x in report.get("findings", []))
    if confirmed:
        st.warning(f"수정 후보 {confirmed}개" + (f" · 추가 확인 {pending}개" if pending else ""))
    elif pending:
        st.info(f"추가 확인 {pending}개 · 아래 항목을 확인하세요.")
    else:
        st.success("검토한 항목에서 수정 후보가 없습니다.")

    def card(item):
        with st.container(border=True):
            suggestions = item.get("recommendations", [])
            first = suggestions[0] if suggestions else {}
            st.markdown("**" + first.get("title", item.get("title", item.get("label", item["finding_id"]))) + "**")
            evidence = item.get("evidence", [])
            if evidence:
                st.caption(" · ".join(str(x) for x in evidence[:2]))
            action = first.get("action", item.get("action", ""))
            if action:
                st.write(action)
            if len(suggestions) > 1:
                with st.expander(f"함께 바꿀 항목 {len(suggestions) - 1}개"):
                    for suggestion in suggestions[1:]:
                        st.markdown("**" + suggestion["title"] + "**")
                        st.write(suggestion["action"])
            if item.get("origin") == "rule_fallback":
                st.caption("규칙 결과로 확인")
            if on_select is not None:
                st.button("위치 보기", key=f"{key_prefix}_learned_{item['finding_id']}",
                          on_click=on_select, args=(item["finding_id"],))

    if items:
        for column, item in zip(st.columns(min(3, len(items))), items[:3]):
            with column:
                card(item)
    if len(items) > 3:
        with st.expander(f"나머지 확인 항목 {len(items) - 3}개"):
            for item in items[3:]:
                card(item)
    with st.expander("AI 학습·검증 기록"):
        st.caption("내부 학습 모델의 예측을 현재 측정값·규칙과 대조했습니다.")
        model = analysis.get("model", {})
        st.write({key: model[key] for key in ("id", "algorithm", "training_rows") if key in model})
        table = [{"항목": item.get("label", item.get("finding_id")),
                  "결과": {"confirmed": "수정 후보", "clear": "후보 없음",
                           "review": "추가 확인", "unavailable": "미검토"}.get(item.get("state"), "미검토"),
                  "확인 방식": {"learned_verified": "AI·규칙 일치", "rule_fallback": "규칙 확인",
                              "unavailable": "미검토"}.get(item.get("origin"), "미검토"),
                  "범위·사유": item.get("reason") or item.get("scope", "")}
                 for item in analysis.get("items", [])]
        if table:
            st.dataframe(table, hide_index=True)
        if model.get("validation"):
            st.json(model["validation"], expanded=False)
        st.caption("모델 식별자: " + str(model.get("sha256", "없음")))
    return {"rendered": True, "displayed_ids": [item["finding_id"] for item in items]}
