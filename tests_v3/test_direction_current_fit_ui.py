"""An arbitrary current angle can fit when every fixed search candidate fails."""

import pytest
from streamlit.testing.v1 import AppTest


@pytest.mark.parametrize("compact", [False, True])
def test_current_only_fit_direction_view_preserves_result_without_apply_button(compact):
    app = AppTest.from_string(
        '''
from copy import deepcopy
import streamlit as st
from dfm.plan_learning import orientation_recommendation
from amdfm.decision_view import render_recommendation

current = dict(name="현재 사용자 방향", direction=[0.6, 0.0, 0.8],
               height_mm=37.125, overhang_projected_area_sum_mm2=14.625,
               contact_triangle_area_mm2=2.875, build_fit=True,
               candidate_role="current_only")
fixed = [dict(name="+Z", direction=[0, 0, 1], height_mm=121.25,
              overhang_projected_area_sum_mm2=10.5,
              contact_triangle_area_mm2=7.25, build_fit=False,
              candidate_role="search")]
report = dict(profile={"process": "MEX", "build_volume_mm": [100., 100., 100.]},
              model={"unit_status": "declared"}, findings=[],
              summary={"review_status": "geometry_review"},
              current_orientation=current, orientations=fixed,
              review_context={"priority": "balanced"})
before_report = deepcopy(report)
recommendation = orientation_recommendation(report)
before_recommendation = deepcopy(recommendation)
def apply_direction(*args):
    raise AssertionError("A current-only fitting direction must not offer application of a failing candidate")
render_recommendation(recommendation, on_apply=apply_direction, presets={},
                      key_prefix="current_only", compact=COMPACT)
st.session_state["report_unchanged"] = report == before_report
st.session_state["recommendation_unchanged"] = recommendation == before_recommendation
st.session_state["result"] = recommendation
st.session_state["current"] = report["current_orientation"]
'''.replace("COMPACT", repr(compact)),
        default_timeout=15,
    ).run()

    # A collapsed expander still executes its body: this catches the former
    # None['name'] crash as well as an incorrect alternate-direction CTA.
    for _ in range(2):
        assert not app.exception
        result = app.session_state["result"]
        assert result["status"] == "current_only_fit"
        assert result["keep_current"] is True
        assert result["action"] == "keep"
        assert result["recommended"] is None
        assert result["eligible_count"] == 0
        assert result["excluded_count"] == 1
        assert result["current_comparison"]["differences"] == []
        assert app.session_state["report_unchanged"]
        assert app.session_state["recommendation_unchanged"]
        current = app.session_state["current"]
        assert current["direction"] == [0.6, 0.0, 0.8]
        assert (current["height_mm"], current["overhang_projected_area_sum_mm2"],
                current["contact_triangle_area_mm2"]) == (37.125, 14.625, 2.875)
        assert current["build_fit"] is True
        assert any("현재 방향을 유지" in item.value for item in app.info)
        assert any("입력한 공간에 맞는 현재 방향" in item.value for item in app.caption)
        assert not app.button
        app.run()
