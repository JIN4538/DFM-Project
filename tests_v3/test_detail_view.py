"""Novice-facing wall and layer views show evidence, location and next action."""
import json

from streamlit.testing.v1 import AppTest


def layers():
    return dict(status="complete", expected_layers=3, examined_layers=3, complete_layers=3,
        layers=[dict(index=i, z_mm=.1+i*.2, complete=True,
            thin_candidate_area_mm2=0., unsupported_candidate_area_mm2=0., single_layer_candidate_area_mm2=0.,
            thin_full_scope=True, unsupported_full_scope=True, single_layer_full_scope=True)
                for i in range(3)])


def wall():
    return dict(status="measured", measurements=dict(minimum_mm=4., minimum_wall_mm=None,
        area_weighted_p05_mm=4., requested_samples=1, valid_samples=1, missing_samples=0,
        thinnest_face_indices=[0], below_limit_face_indices=[],
        samples=[dict(source_face=0, normal_chord_mm=4., point_mm=[0., 0., 0.])]))


def render(detail, mode="layers", criterion=None, transform=None):
    transform = transform or [[1.,0.,0.,0.], [0.,1.,0.,0.], [0.,0.,1.,0.], [0.,0.,0.,1.]]
    report = dict(profile=dict(minimum_wall_mm=criterion, threshold_basis="장비 자료에서 가져온 사용자 입력"),
                  details={mode: detail}, findings=[dict(id="wall", title="벽 표본", face_indices=[0])],
                  current_orientation=dict(transform=transform), model_fingerprint="test-geometry")
    script = ("import streamlit as st\nimport trimesh\n"
              "from amdfm.models import Model\n"
              "from amdfm.detail_view import render_wall_result, render_layer_result\n"
              "model=Model(trimesh.creation.box(extents=[4.,4.,4.]), {})\n"
              f"report={report!r}\n"
              f"{'render_wall_result' if mode=='wall' else 'render_layer_result'}(model, report)\n"
              "st.session_state['original_report']=report\n")
    return AppTest.from_string(script, default_timeout=30).run()


def text(app):
    return "\n".join(element.value for element in app.markdown)


def test_zero_layers_show_a_clear_scoped_result_and_hide_blank_graph():
    detail = layers()
    app = render(detail)
    assert not app.exception
    assert any("3개 층" in message.value and "발견되지" in message.value for message in app.success)
    assert not app.get("plotly_chart")
    assert not app.get("vega_lite_chart")
    assert not app.selectbox
    assert "다음에 할 일" in text(app)
    assert "슬라이서" in text(app)
    assert len(app.expander) == 1
    assert app.expander[0].label == "전체 층 측정값·계산 범위"
    assert not app.expander[0].proto.expanded
    assert app.dataframe[0].value["층"].tolist() == [1, 2, 3]
    assert app.session_state["original_report"]["details"]["layers"] == detail


def test_affected_rows_precede_full_table_and_coordinates_are_recorded_build_frame():
    detail = layers()
    detail["layers"][1].update(thin_candidate_area_mm2=1e-12,
        thin_details=[dict(bounds_mm=[1., 2., 3., 4.], area_mm2=1e-12)])
    translation = [[1.,0.,0.,10.], [0.,1.,0.,20.], [0.,0.,1.,30.], [0.,0.,0.,1.]]
    app = render(detail, transform=translation)
    assert not app.exception
    assert app.dataframe[0].value["층"].tolist() == [2]
    assert app.dataframe[1].value["층"].tolist() == [1, 2, 3]
    assert "2층" in app.selectbox(key="layer_location").options[0]
    assert float(app.dataframe[0].value.iloc[0]["선폭보다 좁을 수 있는 영역 (mm²)"]) == 1e-12
    plot = json.loads(app.get("plotly_chart")[0].proto.spec)
    marker = next(trace for trace in plot["data"] if trace.get("name")=="선폭 후보 위치")
    assert marker["x"] == [1., 3., 3., 1., 1.]
    assert marker["y"] == [2., 2., 4., 4., 2.]
    assert marker["z"] == [detail["layers"][1]["z_mm"]]*5
    assert any("경계 상자" in caption.value for caption in app.caption)
    assert app.session_state["original_report"]["details"]["layers"] == detail


def test_candidate_without_recorded_location_does_not_invent_a_3d_marker():
    detail = layers()
    detail["layers"][0]["single_layer_candidate_area_mm2"] = 1.
    app = render(detail)
    assert not app.exception
    assert not app.get("plotly_chart")
    assert any("위치 경계가 없습니다" in message.value for message in app.info)
    assert "슬라이서" in text(app)


def test_all_missing_metrics_are_labeled_unknown_instead_of_none_count_or_zero():
    detail = layers()
    detail["status"] = "partial"
    for row in detail["layers"]:
        row.update(thin_candidate_area_mm2=None, unsupported_candidate_area_mm2=None,
                   single_layer_candidate_area_mm2=None)
    app = render(detail)
    assert not app.exception
    assert not app.success
    assert "None개" not in text(app)
    assert "미확인" in text(app)
    assert not app.get("plotly_chart")
    for column in app.dataframe[0].value.columns[3:]:
        assert (app.dataframe[0].value[column] == "미확정").all()


def test_partial_comparison_zero_is_labeled_as_a_partial_scope_in_the_table():
    detail = layers()
    detail["status"] = "partial"
    detail["layers"][1]["unsupported_full_scope"] = False
    app = render(detail)
    assert not app.exception and not app.success
    value = app.dataframe[0].value.iloc[1]["아래층 지지가 부족할 수 있는 영역 (mm²)"]
    assert "일부 범위" in value


def test_wall_measurement_without_criterion_explains_what_color_and_distance_mean():
    app = render(wall(), mode="wall")
    assert not app.exception
    assert not app.success
    assert any("비교 기준이 없습니다" in message.value for message in app.info)
    assert [metric.value for metric in app.metric] == ["4 mm", "미입력"]
    assert "색 자체가 기준 미달을 뜻하지 않습니다" in text(app)
    assert "다음에 할 일" in text(app)
    assert any("전체 최소 벽두께" in caption.value for caption in app.caption)
    assert "장비 자료에서 가져온 사용자 입력" in text(app)
    assert not app.expander[0].proto.expanded


def test_partial_wall_is_not_a_green_success_with_above_limit_minimum():
    detail = wall()
    detail.update(status="partial")
    detail["measurements"].update(requested_samples=2, missing_samples=1)
    app = render(detail, mode="wall", criterion=1.)
    assert not app.exception
    assert app.warning and not app.success
    assert any("확인하지 못했습니다" in message.value for message in app.warning)
    assert "미확인" in text(app)


def test_failed_wall_shows_reason_without_a_stale_measurement_or_plot():
    app = render(dict(status="unknown", reason="유효한 솔리드가 필요합니다."), mode="wall")
    assert not app.exception
    assert app.warning and not app.metric and not app.get("plotly_chart")
    assert "유효한 솔리드" in text(app)
