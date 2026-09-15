"""The novice view must expose actions without inventing a production verdict."""
import copy
import json

from streamlit.testing.v1 import AppTest


def sections():
    heights = [.8453, 3.1547, 11.396, 32.604]
    areas = [1200., 1200., 120., 120.]
    changes = [None, 0., 1080., 0.]
    rows = []
    for i, (height, area, change) in enumerate(zip(heights, areas, changes)):
        width = area / 30
        rows.append(dict(index=i, z_mm=height, area_mm2=area, complete=True,
                         interval_index=i // 2, symmetric_change_from_previous_mm2=change,
                         perimeter_mm=2*(width+30), area_per_perimeter_mm=area/(2*(width+30)),
                         material_regions=1, internal_loops=0, outlines_complete=True,
                         outlines=[[[0,0],[width,0],[width,30],[0,30],[0,0]]]))
    return dict(status="complete", sampling="events", complete_samples=4, requested_samples=4,
                examined_samples=4, rows=rows, fingerprint="fixture", elapsed_seconds=1,
                volume_quadrature_estimate_mm3=9120.000000000004)


def render(detail):
    script = (
        "import streamlit as st\n"
        "from amdfm.section_view import render_section_result\n"
        f"detail = {detail!r}\n"
        "render_section_result(detail, 'PBF_METAL', 9120.)\n"
        "st.session_state['original_detail'] = detail\n"
    )
    return AppTest.from_string(script, default_timeout=30).run()


def test_change_pair_selected_without_fake_slope_or_mutating_original_measurements():
    detail = sections()
    original = copy.deepcopy(detail)
    app = render(detail)
    assert not app.exception
    assert app.selectbox(key="section_index").value == 2
    assert "높이" in app.selectbox(key="section_index").options[0]
    assert app.session_state["original_detail"] == original
    assert not app.metric, "Tiny numerical cross-check must not be a giant primary verdict"
    text = "\n".join(element.value for element in app.markdown)
    assert "다음에 할 일" in text and "제작" in text
    assert "0.0001% 미만" in text
    plot = json.loads(app.get("plotly_chart")[0].proto.spec)
    assert len(plot["data"]) == 2
    assert {trace["line"]["dash"] for trace in plot["data"]} == {"dash", "solid"}
    chart = json.loads(app.get('plotly_chart')[1].proto.spec)
    assert all(trace['mode']=='markers' for trace in chart['data'])
    selected=next(t for t in chart['data'] if t['name']=='현재 단면')
    assert selected['marker']['symbol']=='diamond' and selected['x']==[detail['rows'][2]['z_mm']]
    app.selectbox(key="section_index").set_value(0).run()
    app.button(key="show_section_change").click().run()
    assert not app.exception and app.selectbox(key="section_index").value == 2
    assert app.session_state["original_detail"] == original


def test_partial_display_does_not_present_stale_total_volume_or_bridge_missing_section():
    detail = sections()
    detail.update(status="partial", complete_samples=3)
    detail["rows"][1].update(complete=False, area_mm2=None, outlines=[], outlines_complete=False,
                             symmetric_change_from_previous_mm2=None)
    detail["rows"][2]["symmetric_change_from_previous_mm2"] = None
    app = render(detail)
    assert not app.exception and app.warning
    text = "\n".join(element.value for element in app.markdown)
    assert "두 계산 방법의 부피 차이:" not in text
    assert not any(b.key=="show_section_change" for b in app.button)
    app.selectbox(key="section_index").set_value(1).run()
    assert not app.exception
    assert any("이 높이의 재료 단면은 확정되지" in e.value for e in app.warning)


def test_unknown_empty_result_has_reason_and_no_misleading_plot():
    app = render(dict(status="unknown", requested_samples=10000, complete_samples=0,
                      rows=[], reason="계산 한도 초과", budget_exceeded=True))
    assert not app.exception and app.warning
    assert not app.selectbox and not app.get("plotly_chart")
    assert any("계산 한도 초과" in e.value for e in app.markdown)


def test_auto_failure_does_not_claim_uniform_was_executed():
    app=render(dict(status='unknown',sampling='auto',rows=[],reason='표면 입력으로 단면 보류'))
    assert not app.exception
    assert any('계산 방법 미확정' in e.value for e in app.caption)
    assert not any('균등 간격 결과' in e.value for e in app.caption)


def test_representation_limited_volume_is_visible_without_total_verdict():
    from amdfm.event_sections import inspect_event_sections
    import trimesh
    detail=inspect_event_sections(trimesh.creation.icosphere(subdivisions=2,radius=10))
    detail['sampling']='events'
    app=render(detail)
    assert not app.exception and app.warning
    assert len(app.metric)==2
    assert '확인한 구간' in app.metric[0].label
    assert '기여 상한' in app.metric[1].label
    assert not any('두 계산 방법의 부피 차이:' in e.value for e in app.markdown)
    assert app.session_state['original_detail']['volume_quadrature_estimate_mm3'] is None
