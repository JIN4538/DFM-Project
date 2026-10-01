"""Portable, escaped summary of learned review provenance and conclusions."""
from __future__ import annotations

import html
import json


def learned_html(analysis):
    if not analysis:
        return ""
    esc = lambda value: html.escape(str(value), quote=True)
    states = {"confirmed": "수정 후보", "clear": "후보 없음",
              "review": "추가 확인", "unavailable": "미검토"}
    parts = ["<h2>항목별 검토</h2>"]
    if analysis.get("status") == "unavailable":
        parts.append("<p>학습 검토 사용 불가 · 아래 항목별 확인 상태를 참고하세요.</p>"
                     if analysis.get("items") else "<p>검토 결과가 없습니다.</p>")
    for item in analysis.get("items", []):
        if item.get("state") not in ("confirmed", "review"):
            continue
        parts.append("<section class='decision'><h3>" + esc(item.get("title", item.get("label", "검토 항목")))
                     + "</h3><p>" + esc(" · ".join(map(str, item.get("evidence", []))))
                     + "</p><p>" + esc(item.get("action", "")) + "</p></section>")
    rows = "".join("<tr><td>" + esc(item.get("label", item.get("finding_id", "")))
                   + "</td><td>" + esc(states.get(item.get("state"), "미검토"))
                   + "</td><td>" + esc(item.get("origin", "unavailable")) + "</td></tr>"
                   for item in analysis.get("items", []))
    parts.append("<details><summary>AI 학습·검증 기록</summary><table>"
                 "<tr><th>항목</th><th>결과</th><th>확인 방식</th></tr>" + rows + "</table><pre>"
                 + esc(json.dumps(analysis, ensure_ascii=False, indent=2, allow_nan=False)) + "</pre></details>")
    return "".join(parts)
