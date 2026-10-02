"""Presentation counterexamples: completion is not a manufacturing verdict."""
from copy import deepcopy
import math

import pytest

from amdfm.section_summary import summarize_sections


def row(index, height, area, change=None, *, complete=True, interval=None):
    value = dict(index=index, z_mm=height, area_mm2=area,
                 symmetric_change_from_previous_mm2=change, complete=complete)
    if interval is not None:
        value["interval_index"] = interval
    return value


def result(rows, *, status="complete", requested=None, volume=100):
    return dict(status=status, rows=rows, requested_samples=len(rows) if requested is None else requested,
                examined_samples=len(rows), complete_samples=sum(r["complete"] for r in rows),
                volume_quadrature_estimate_mm3=volume, method="vertex_event_intervals_gauss2/1")


def test_real_bracket_like_four_samples_selects_changed_pair_not_first_slice():
    detail = result([row(0, .6, 1200), row(1, 3.4, 1200, 0),
                     row(2, 11.6, 104, 1096), row(3, 32.4, 104, 0)])
    snapshot = deepcopy(detail)
    summary = summarize_sections(detail, "PBF_METAL", 100)
    assert summary["status"] == "complete"
    assert summary["completion_text"].startswith("요청한 4개 중 4개 계산 완료")
    assert summary["default_row_index"] == 2
    assert summary["change"]["previous_row_index"] == 1
    assert "1,200 → 104 mm²" in summary["change_text"]
    assert "3.4 → 11.6 mm" in summary["change_text"]
    assert "검토한 표본에서" in summary["change_text"]
    assert len(summary["change_text"].split(". ")) == 2
    assert "결정할 수 없습니다" in summary["interpretation"]
    assert detail == snapshot


def test_equal_area_translated_shape_has_positive_symmetric_change():
    # Two 10x10 squares translated by 2 mm: 20 mm2 removed and 20 added.
    detail = result([row(0, 1, 100), row(1, 2, 100, 40)])
    summary = summarize_sections(detail, "MEX", 100)
    assert summary["change"]["symmetric_change_mm2"] == 40
    assert "100 → 100 mm²" in summary["change_text"]
    assert "40 mm²" in summary["change_text"]
    assert summary["default_row_index"] == 1


def test_tiny_positive_change_is_not_suppressed_as_no_change():
    summary = summarize_sections(result([row(0, 1, 100), row(1, 2, 100, 1e-20)]), "VPP", 100)
    assert summary["change"]["symmetric_change_mm2"] == 1e-20
    assert "관측되지 않았습니다" not in summary["change_text"]


@pytest.mark.parametrize("second_volume, expected", [(100, "0%"), (100+1e-12, "<0.0001%"), (101, "1%")])
def test_volume_difference_has_human_format_but_no_acceptance_threshold(second_volume, expected):
    detail = result([row(0, 1, 10), row(1, 2, 10, 0)], volume=second_volume)
    summary = summarize_sections(detail, "MEX", 100)
    assert summary["volume"]["display"] == expected
    assert summary["volume"]["relative_difference_percent"] == abs(second_volume-100)
    assert "e-" not in summary["volume"]["display"]
    assert summary["completion_level"] == "info"
    assert "합격 기준은 아닙니다" in summary["volume"]["explanation"]
    assert "verdict" not in summary["volume"]


def test_incomplete_result_ignores_stale_total_volume_but_keeps_known_pair():
    detail = result([row(0, 1, 100), row(1, 2, 80, 20), row(2, 3, None, complete=False)],
                    status="partial", requested=4, volume=100)
    summary = summarize_sections(detail, "VPP", 100)
    assert summary["status"] == "partial"
    assert summary["completion_level"] == "warning"
    assert "4개 중 2개" in summary["completion_text"]
    assert summary["change"]["symmetric_change_mm2"] == 20
    assert summary["next_step"].startswith("미확정 이유")
    assert summary["volume"]["available"] is False
    assert summary["volume"]["relative_difference_percent"] is None
    assert summary["volume"]["section_volume_mm3"] is None


@pytest.mark.parametrize("declared_status", ["partial", "unknown", "unavailable"])
def test_noncomplete_status_has_priority_even_when_all_supplied_rows_are_complete(declared_status):
    detail = result([row(0, 1, 10), row(1, 2, 10, 0)], status=declared_status)
    summary = summarize_sections(detail, "MEX", 100)
    assert summary["status"] != "complete"
    assert summary["completion_level"] == "warning"
    assert summary["volume"]["available"] is False


def test_complete_label_with_missing_rows_or_bad_count_is_not_promoted():
    detail = result([row(0, 1, 10), row(1, 2, 10, 0)], requested=3)
    summary = summarize_sections(detail, "MEX", 100)
    assert summary["status"] == "partial"
    assert summary["volume"]["available"] is False
    assert "일치하지 않아" in summary["reason"]


def test_unknown_row_breaks_adjacency_even_when_later_change_was_supplied():
    detail = result([row(0, 1, 100), row(1, 2, None, complete=False), row(2, 3, 10, 90)], status="partial")
    summary = summarize_sections(detail, "MEX", 100)
    assert summary["change"] is None
    assert summary["change_text"] == "비교 가능한 인접 단면 쌍이 없습니다."


@pytest.mark.parametrize("before, after", [
    (row(0, 1, 100), row(2, 3, 10, 90)),
    (row(0, 1, 100, interval=0), row(1, 3, 10, 90, interval=2)),
    (row(0, 1, 100, interval=0), row(1, 3, 10, 90)),
])
def test_removed_rows_or_unrepresentable_event_interval_never_become_pair(before, after):
    summary = summarize_sections(result([before, after], status="partial"), "PBF_METAL", 100)
    assert summary["change"] is None


def test_unknown_event_interval_blocks_total_even_if_rows_and_counts_look_complete():
    detail = result([row(0, 1, 10), row(1, 2, 10, 0)])
    detail["intervals"] = [dict(complete=True), dict(complete=False, row_indices=[])]
    summary = summarize_sections(detail, "MEX", 100)
    assert summary["status"] == "partial"
    assert summary["volume"]["available"] is False


def test_no_observed_change_is_not_a_safe_manufacturing_verdict():
    summary = summarize_sections(result([row(0, 1, 10), row(1, 2, 10, 0)]), "MEX", 100)
    assert summary["change_text"] == "확인한 단면 사이에서 변화가 관측되지 않았습니다."
    assert summary["default_row_index"] == 0
    assert "결정할 수 없습니다" in summary["interpretation"]


@pytest.mark.parametrize("mesh, section", [(None, 100), (0, 100), (-1, 100),
                                         (math.nan, 100), (math.inf, 100), (True, 100),
                                         (100, None), (100, math.nan), (100, -1)])
def test_volume_missing_invalid_or_nonfinite_inputs_are_not_zero_difference(mesh, section):
    summary = summarize_sections(result([row(0, 1, 10), row(1, 2, 10, 0)], volume=section), "MEX", mesh)
    assert summary["volume"]["available"] is False
    assert summary["volume"]["display"] == "확인 불가"
    assert summary["volume"]["relative_difference_percent"] is None


def test_event_failure_does_not_fall_back_to_stale_uniform_total():
    detail = result([row(0, 1, 10), row(1, 2, 10, 0)], volume=None)
    detail["volume_midpoint_estimate_mm3"] = 100
    assert summarize_sections(detail, "MEX", 100)["volume"]["available"] is False


def test_uniform_section_total_remains_supported():
    detail = result([row(0, 1, 10), row(1, 2, 10, 0)], volume=None)
    detail.update(method="uniform_midpoint_sections/1", volume_midpoint_estimate_mm3=100)
    assert summarize_sections(detail, "MEX", 100)["volume"]["display"] == "0%"


@pytest.mark.parametrize("process, expected", [("MEX", "MEX 층간 검토"), ("VPP", "장비·수지"),
                                             ("PBF_POLYMER", "분말 배출"), ("PBF_METAL", "하향면")])
def test_action_is_process_specific_without_predicting_process_physics(process, expected):
    summary = summarize_sections(result([row(0, 1, 100), row(1, 2, 50, 50)]), process, 100)
    assert expected in summary["next_step"]
    assert "의도" in summary["next_step"]
    assert "먼저 확인" in summary["next_step"]
    assert "배치를 바꾸" not in summary["next_step"]
    if process != "MEX":
        assert "MEX 층간 검토" not in summary["next_step"]
    assert "위험" not in summary["change_text"]
    assert "출력 성공" not in summary["completion_text"]


def test_budget_preflight_without_known_sample_count_preserves_unknown():
    detail = dict(status="unknown", rows=[], requested_samples=None, complete_samples=0,
                  examined_samples=0, reason="입력 폐곡면 조건이 충족되지 않았습니다.")
    summary = summarize_sections(detail, "VPP", 100)
    assert summary["status"] == "unknown"
    assert "요청 수 미확정" in summary["completion_text"]
    assert summary["default_row_index"] is None
    assert summary["reason"] == detail["reason"]


def test_nearby_distinct_sample_heights_are_not_rendered_as_identical():
    before, after = 1.0000000000001, 1.0000000000002
    summary = summarize_sections(result([row(0, before, 100), row(1, after, 50, 50)]), "MEX", 100)
    assert str(before) in summary["change_text"]
    assert str(after) in summary["change_text"]
