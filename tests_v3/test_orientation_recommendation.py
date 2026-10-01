"""Counterexamples for a stable policy; these do not validate physical printing."""
from copy import deepcopy

import pytest
import trimesh

from amdfm.orientation import compare_orientations, measure_orientation
from amdfm.profiles import Profile
from amdfm.recommendation import recommend_orientation


def _row(name, height, overhang, contact, *, fit=None, role="search"):
    return dict(name=name, height_mm=height, overhang_projected_area_sum_mm2=overhang,
                contact_triangle_area_mm2=contact, build_fit=fit, candidate_role=role)


def _report(rows, process="MEX", *, current=None, build_volume=None):
    return dict(profile=dict(process=process, build_volume_mm=build_volume), orientations=rows,
                current_orientation=deepcopy(current or rows[0]) if rows else {},
                summary=dict(review_status="geometry_review"))


def _tradeoff_rows():
    # Height-only chooses +Z, overhang/contact-only +Y, combined compromise +X.
    return [_row("+Z", 10., 100., 20.), _row("+X", 15., 40., 80.), _row("+Y", 30., 0., 100.)]


def test_tradeoff_recommends_one_compromise_with_readable_current_differences():
    result = recommend_orientation(_report(_tradeoff_rows()))
    assert result["recommended"]["name"] == "+X"
    assert result["action"] == "apply"
    changes = {r["field"]: r["change"] for r in result["current_comparison"]["differences"]}
    assert changes == {"height_mm": "tradeoff", "overhang_projected_area_sum_mm2": "improvement",
                       "contact_triangle_area_mm2": "improvement"}
    assert {r["weight"] for r in result["criteria"]} == {1/3}
    assert "개발자가 정한" in result["policy"]["basis"]


def test_reapplying_any_compared_direction_cannot_move_the_recommendation():
    rows = _tradeoff_rows()
    results = [recommend_orientation(_report(rows, current=current)) for current in rows]
    assert {r["recommended"]["name"] for r in results} == {"+X"}
    assert results[1]["action"] == "keep"
    assert results[1]["current_is_equivalent"]
    assert all(r["ranking"] == results[0]["ranking"] for r in results)


def test_current_only_extreme_does_not_change_winner_or_normalization():
    rows = _tradeoff_rows()
    before = recommend_orientation(_report(rows))
    custom = _row("현재 지정 방향", 1e6, 1e12, 1e14, role="current_only")
    after = recommend_orientation(_report(rows + [custom], current=custom))
    assert after["recommended"] == before["recommended"]
    assert after["criteria"] == before["criteria"]
    assert after["candidate_count"] == 3


def test_better_custom_current_is_kept_without_changing_fixed_candidate_winner():
    current = _row("현재 지정 방향", 5., 0., 110., role="current_only")
    result = recommend_orientation(_report(_tradeoff_rows() + [current], current=current))
    assert result["recommended"]["name"] == "+X"
    assert result["keep_current"] and result["current_is_better"]
    assert result["action"] == "keep"
    assert result["title"] == "현재 방향을 유지하세요"


def test_all_tied_candidates_use_stable_representative_and_do_not_force_switch():
    rows = [_row("+Y", 10., 0., 100.), _row("-Z", 10., 0., 100.), _row("+Z", 10., 0., 100.)]
    result = recommend_orientation(_report(rows))
    assert result["all_tied"]
    assert result["recommended"]["name"] == "+Z"
    assert result["keep_current"]
    assert [r["name"] for r in result["alternatives"]] == ["-Z", "+Y"]
    assert recommend_orientation(_report(list(reversed(rows))))["recommended"] == result["recommended"]


def test_equal_policy_tradeoffs_do_not_force_direction_change():
    rows = [_row("+Z", 10., 20., 10.), _row("+X", 20., 10., 10.)]
    result = recommend_orientation(_report(rows, current=rows[1]))
    assert result["recommended"]["name"] == "+Z"
    assert result["current_is_equivalent"]
    assert result["action"] == "keep"


def test_last_bit_roundoff_of_equal_area_is_not_amplified_into_a_full_preference():
    rows = [_row("+Z", 10., 20., 100.), _row("+X", 20., 10., 100.+1e-14)]
    result = recommend_orientation(_report(rows, current=rows[1]))
    assert result["recommended"]["name"] == "+Z"
    assert result["current_is_equivalent"]
    assert result["criteria"][-1]["constant"]


def test_custom_worse_in_constant_criterion_is_not_invented_as_equal():
    rows = [_row("+Z", 10., 0., 100.), _row("-Z", 10., 0., 100.)]
    custom = _row("현재 지정 방향", 10., 20., 100., role="current_only")
    result = recommend_orientation(_report(rows + [custom], current=custom))
    assert not result["keep_current"]
    assert not result["current_is_equivalent"]


@pytest.mark.parametrize("invalid", [None, float("nan"), float("inf"), -1., True])
def test_missing_or_invalid_metric_never_becomes_zero_or_an_advantage(invalid):
    rows = _tradeoff_rows()
    rows[1]["overhang_projected_area_sum_mm2"] = invalid
    result = recommend_orientation(_report(rows))
    assert result["status"] == "unavailable"
    assert result["recommended"] is None
    assert result["ranking"] == []
    assert result["missing_criteria"] == ["overhang_projected_area_sum_mm2"]


def test_unreliable_normals_cannot_reduce_mex_recommendation_to_height_only():
    mesh = trimesh.creation.box(extents=[2., 3., 7.])
    rows = compare_orientations(mesh, Profile(), reliable_normals=False)
    result = recommend_orientation(_report(rows))
    assert result["status"] == "unavailable"
    assert set(result["missing_criteria"]) == {"overhang_projected_area_sum_mm2", "contact_triangle_area_mm2"}


def test_unreliable_geometry_blocks_even_polymer_height_recommendation():
    report = _report([_row("+Z", 10., None, None)], process="PBF_POLYMER")
    report["summary"]["review_status"] = "partial_geometry"
    assert recommend_orientation(report)["recommended"] is None


@pytest.mark.parametrize("finding_id", ["assembly", "shells", "surface_input"])
def test_uncertain_material_union_cannot_be_ranked_as_one_valid_part(finding_id):
    report = _report(_tradeoff_rows())
    report["findings"] = [{"id": finding_id, "status": "attention"}]
    result = recommend_orientation(report)
    assert result["status"] == "unavailable"
    assert result["recommended"] is None
    assert "단일 솔리드" in result["next_action"]


def test_space_failure_excluded_before_policy_and_normalization():
    rows = _tradeoff_rows()
    rows[1]["build_fit"] = False
    rows[0]["build_fit"] = rows[2]["build_fit"] = True
    result = recommend_orientation(_report(rows, build_volume=[30., 30., 30.]))
    assert result["recommended"]["name"] == "+Y"
    assert result["excluded_count"] == 1
    assert result["eligible_count"] == 2
    assert "+X" not in [r["name"] for r in result["ranking"]]


def test_no_fitting_candidate_produces_no_recommendation():
    rows = _tradeoff_rows()
    for row in rows:
        row["build_fit"] = False
    result = recommend_orientation(_report(rows, build_volume=[1., 1., 1.]))
    assert result["status"] == "no_fit"
    assert result["recommended"] is None
    assert result["action"] == "review"


def test_fitting_custom_current_is_kept_when_every_fixed_candidate_exceeds_space():
    rows = _tradeoff_rows()
    for row in rows:
        row["build_fit"] = False
    custom = _row("현재 지정 방향", 8., 2., 1., fit=True, role="current_only")
    result = recommend_orientation(_report(rows+[custom], current=custom, build_volume=[10., 10., 10.]))
    assert result["status"] == "current_only_fit"
    assert result["recommended"] is None
    assert result["ranking"] == []
    assert result["candidate_count"] == result["excluded_count"] == 3
    assert result["action"] == "keep" and result["keep_current"]
    assert "현재 방향을 유지" in result["title"]
    assert "분할" not in result["next_action"]


def test_unknown_fit_is_not_pass_when_space_constraint_is_enabled():
    result = recommend_orientation(_report(_tradeoff_rows(), build_volume=[30., 30., 30.]))
    assert result["status"] == "unavailable"
    assert result["missing_criteria"] == ["build_fit"]


@pytest.mark.parametrize("process", ["VPP", "PBF_METAL"])
def test_resin_and_metal_do_not_use_mex_contact_preference(process):
    rows = [_row("+Z", 10., 0., 0.), _row("+X", 20., 5., 1e9)]
    result = recommend_orientation(_report(rows, process=process))
    assert result["recommended"]["name"] == "+Z"
    assert {r["field"] for r in result["criteria"]} == {"height_mm", "overhang_projected_area_sum_mm2"}


def test_polymer_support_metric_is_inapplicable_and_height_scope_is_explicit():
    rows = [_row("+Z", 10., None, None), _row("+X", 20., None, None)]
    result = recommend_orientation(_report(rows, process="PBF_POLYMER"))
    assert result["recommended"]["name"] == "+Z"
    assert result["status"] == "limited"
    assert [r["field"] for r in result["criteria"]] == ["height_mm"]
    assert "높이만" in result["observation"]


@pytest.mark.parametrize("process", ["MEX", "VPP", "PBF_POLYMER", "PBF_METAL"])
def test_independent_rectangular_box_oracle_and_current_invariance(process):
    # A 2×3×7 box on ±X has height2, contact21, no non-bottom downward face.
    mesh = trimesh.creation.box(extents=[2., 3., 7.])
    profile = Profile(process=process)
    outcomes = []
    for direction in ([0., 0., 1.], [1., 0., 0.], [-1., 0., 0.], [1., 2., 3.]):
        rows = compare_orientations(mesh, profile, dense=True, current_direction=direction)
        report = _report(rows, process=process, current=measure_orientation(mesh, direction, profile))
        outcomes.append(recommend_orientation(report))
    assert {r["recommended"]["name"] for r in outcomes} == {"+X"}
    assert outcomes[0]["recommended"]["height_mm"] == pytest.approx(2.)
    assert outcomes[0]["recommended"]["contact_triangle_area_mm2"] == pytest.approx(21.)
    assert outcomes[1]["keep_current"]
    assert outcomes[2]["keep_current"]
    assert all(r["criteria"] == outcomes[0]["criteria"] for r in outcomes)


def test_dimension_scaling_preserves_policy_order():
    original = _tradeoff_rows()
    scaled = deepcopy(original)
    for row in scaled:
        row["height_mm"] *= 1000.
        row["contact_triangle_area_mm2"] *= 1e6
        row["overhang_projected_area_sum_mm2"] *= 1e6
    a, b = (recommend_orientation(_report(rows)) for rows in (original, scaled))
    assert [r["name"] for r in a["ranking"]] == [r["name"] for r in b["ranking"]]
    assert [r["policy_score"] for r in a["ranking"]] == pytest.approx([r["policy_score"] for r in b["ranking"]])


def test_input_measurements_and_existing_pareto_flags_are_not_mutated():
    rows = compare_orientations(trimesh.creation.box(), Profile(), dense=True, current_direction=[1., 2., 3.])
    report = _report(rows)
    before = deepcopy(report)
    recommend_orientation(report)
    assert report == before
    assert len([r for r in rows if r["candidate_role"] == "current_only"]) == 1


def test_old_report_current_name_is_not_promoted_into_fixed_candidates():
    rows = _tradeoff_rows() + [_row("현재 지정 방향", 1., 0., 1e6)]
    for row in rows:
        row.pop("candidate_role")
    result = recommend_orientation(_report(rows, current=rows[-1]))
    assert result["recommended"]["name"] == "+X"
    assert result["keep_current"]


def test_no_search_results_is_explicitly_unavailable():
    result = recommend_orientation(_report([]))
    assert result["recommended"] is None
    assert result["status"] == "unavailable"


def test_unconfirmed_stl_size_allows_only_explicitly_conditional_recommendation():
    report = _report(_tradeoff_rows())
    report["model"] = {"unit_status": "assumed", "dimensions_confirmed": False}
    result = recommend_orientation(report)
    assert result["recommended"]["name"] == "+X"
    assert result["status"] == "limited"
    assert result["assumed_scale"]
    assert "가정한 결과" in result["observation"]
    assert "실제 치수는 미확정" in result["limitations"][0]


def test_explicit_balanced_priority_preserves_default_recommendation_exactly():
    report = _report(_tradeoff_rows())
    default = recommend_orientation(report)
    report["review_context"] = {"priority": "balanced"}
    assert recommend_orientation(report) == default


@pytest.mark.parametrize("priority,field,expected", [
    ("support", "overhang_projected_area_sum_mm2", "+Y"),
    ("contact", "contact_triangle_area_mm2", "+Y"),
    ("height", "height_mm", "+Z"),
])
def test_user_priority_can_change_the_winner_without_claiming_physical_optimality(priority, field, expected):
    rows = _tradeoff_rows()
    if priority == "height":
        # Balanced: +X has a modest combined advantage. Emphasizing height
        # makes the taller compromise less attractive than shortest +Z.
        rows[1]["height_mm"] = 22.
        rows[1]["overhang_projected_area_sum_mm2"] = 10.
    report = _report(rows)
    assert recommend_orientation(report)["recommended"]["name"] == "+X"
    report["review_context"] = {"priority": priority}
    result = recommend_orientation(report)
    assert result["recommended"]["name"] == expected
    weights = {c["field"]: c["weight"] for c in result["criteria"]}
    assert weights[field] == pytest.approx(.6)
    assert all(weight == pytest.approx(.2) for key, weight in weights.items() if key != field)
    assert sum(weights.values()) == pytest.approx(1.)
    assert result["policy"]["effective_priority"] == priority
    assert result["policy"]["priority_supported"]
    assert result["policy"]["priority_multiplier"] == 3.
    assert "3배" in result["observation"]
    assert "개발자가 정한" in result["policy"]["priority_note"]
    assert "물리적 최적이나 성공 확률이 아닙니다" in result["policy"]["priority_note"]


@pytest.mark.parametrize("priority", ["support", "height", "contact"])
def test_prioritized_ranking_remains_stable_across_current_directions_and_custom_outliers(priority):
    rows = _tradeoff_rows()
    results = []
    for current in rows + [_row("현재 지정 방향", 1e7, 1e12, 1e15, role="current_only")]:
        report = _report(rows + ([current] if current["candidate_role"] == "current_only" else []), current=current)
        report["review_context"] = {"priority": priority}
        results.append(recommend_orientation(report))
    assert all(r["recommended"] == results[0]["recommended"] for r in results)
    assert all(r["criteria"] == results[0]["criteria"] for r in results)
    report = _report(rows, current=results[0]["recommended"])
    report["review_context"] = {"priority": priority}
    applied = recommend_orientation(report)
    assert applied["keep_current"] and applied["action"] == "keep"


@pytest.mark.parametrize("priority", ["strength", "surface", "accuracy", "cost", "tool_access"])
@pytest.mark.parametrize("process", ["MEX", "VPP", "PBF_METAL", "PBF_POLYMER"])
def test_unimplemented_physical_priorities_explicitly_fall_back_without_inventing_proxies(priority, process):
    report = _report(_tradeoff_rows(), process=process)
    balanced = recommend_orientation(report)
    report["review_context"] = {"priority": priority}
    result = recommend_orientation(report)
    assert result["ranking"] == balanced["ranking"]
    assert result["criteria"] == balanced["criteria"]
    assert result["policy"]["requested_priority"] == priority
    assert result["policy"]["effective_priority"] == "balanced"
    assert not result["policy"]["priority_supported"]
    assert "판단할 수 없어" in result["policy"]["priority_note"]
    assert result["policy"]["priority_note"] in result["limitations"]
    assert result["policy"]["priority_note"] in result["observation"]


@pytest.mark.parametrize("process,priority", [
    ("VPP", "contact"), ("PBF_METAL", "contact"),
    ("PBF_POLYMER", "support"), ("PBF_POLYMER", "contact"),
])
def test_process_inapplicable_priority_does_not_activate_an_inappropriate_metric(process, priority):
    report = _report(_tradeoff_rows(), process=process)
    baseline = recommend_orientation(report)
    report["review_context"] = {"priority": priority}
    result = recommend_orientation(report)
    assert result["criteria"] == baseline["criteria"]
    assert result["ranking"] == baseline["ranking"]
    assert not result["policy"]["priority_supported"]
    assert result["policy"]["effective_priority"] == "balanced"


@pytest.mark.parametrize("priority", [None, True, 0, [], {}, "unknown_priority"])
def test_invalid_priority_is_disclosed_without_changing_the_balanced_result(priority):
    report = _report(_tradeoff_rows())
    baseline = recommend_orientation(report)
    report["review_context"] = {"priority": priority}
    result = recommend_orientation(report)
    assert result["ranking"] == baseline["ranking"]
    assert result["policy"]["effective_priority"] == "balanced"
    assert not result["policy"]["priority_supported"]
    assert "알 수 없거나 형식이 올바르지 않은" in result["policy"]["priority_note"]


@pytest.mark.parametrize("priority,field,invalid", [
    ("support", "overhang_projected_area_sum_mm2", None),
    ("height", "height_mm", float("nan")),
    ("contact", "contact_triangle_area_mm2", -1.),
    ("support", "contact_triangle_area_mm2", None),
])
def test_a_priority_never_hides_unknown_or_invalid_comparison_criteria(priority, field, invalid):
    rows = _tradeoff_rows()
    rows[1][field] = invalid
    report = _report(rows)
    report["review_context"] = {"priority": priority}
    result = recommend_orientation(report)
    assert result["recommended"] is None
    assert result["status"] == "unavailable"
    assert field in result["missing_criteria"]


def test_prioritization_cannot_recommend_a_space_exceeding_candidate():
    rows = _tradeoff_rows()
    for row in rows:
        row["build_fit"] = row["name"] != "+Y"
    report = _report(rows, build_volume=[30., 30., 30.])
    report["review_context"] = {"priority": "support"}
    result = recommend_orientation(report)
    assert result["recommended"]["name"] == "+X"
    assert result["excluded_count"] == 1
    assert "+Y" not in [row["name"] for row in result["ranking"]]


def test_polymer_height_priority_explains_why_one_metric_cannot_change_the_order():
    report = _report(_tradeoff_rows(), process="PBF_POLYMER")
    baseline = recommend_orientation(report)
    report["review_context"] = {"priority": "height"}
    result = recommend_orientation(report)
    assert result["ranking"] == baseline["ranking"]
    assert result["criteria"][0]["weight"] == 1.
    assert result["policy"]["priority_supported"]
    assert "높이 하나" in result["policy"]["priority_note"]
