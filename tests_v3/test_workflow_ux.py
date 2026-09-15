"""Review guidance must prioritize actual evidence and retain pending work."""
import copy

import numpy as np
import pytest
import trimesh

from amdfm.analysis import review
from amdfm.models import Model
from amdfm.profiles import Profile
from amdfm.workflow import ranked_orientations, summarize_review


def cube_report(process="MEX", **profile):
    mesh = trimesh.creation.box(extents=[4., 4., 4.])
    model = Model(mesh, dict(source_format="step", cad_geometry_kind="solid",
                           solid_count=1, cavity_shell_count=0, exact_volume_mm3=64.),
                  face_ids=np.arange(len(mesh.faces)))
    return review(model, Profile(process=process, **profile), compare=False)


def measured_wall(status="measured", minimum=4., limit=1.):
    return dict(status=status, measurements=dict(minimum_mm=minimum,
        minimum_wall_mm=limit, requested_samples=24 if status=="measured" else 25,
        valid_samples=24, missing_samples=0 if status=="measured" else 1,
        thinnest_face_indices=[0], below_limit_face_indices=[0] if limit is not None and minimum<limit else []))


def item(summary, key):
    return next(row for row in summary["checklist"] if row["id"] == key)


def test_zero_quick_candidates_retains_wall_and_layer_pending_actions():
    report = cube_report()
    assert report["summary"]["attention_items"] == 0
    result = summarize_review(report)
    assert result["level"] != "success"
    assert result["pending_count"] >= 2
    assert "추가 확인" in result["title"]
    assert item(result, "wall")["needs_action"]
    assert item(result, "layers")["needs_action"]
    assert result["next_item"]["target"] == "정밀 검토"


def test_intentional_unlimited_build_space_is_not_an_unfinished_or_failed_check():
    result = summarize_review(cube_report())
    build = item(result, "build")
    assert build["state"] == "크기 제한 미적용"
    assert not build["needs_action"]
    assert build["level"] == "info"


@pytest.mark.parametrize("process", ["VPP", "PBF_POLYMER", "PBF_METAL"])
def test_non_mex_does_not_require_a_mex_layer_check(process):
    result = summarize_review(cube_report(process))
    assert "layers" not in {row["id"] for row in result["checklist"]}
    if process == "PBF_POLYMER":
        assert item(result, "overhang")["state"] == "이 공정에 미적용"
        assert not item(result, "overhang")["needs_action"]


def test_completed_optional_sections_are_not_required_for_a_blanket_pass():
    result = summarize_review(cube_report())
    section = item(result, "sections")
    assert section["state"] == "아직 실행하지 않음 · 필요할 때 단면 확인"
    assert not section["needs_action"]
    assert "보조 검사" in section["observation"]


def test_angle_boundary_does_not_lose_its_next_action_when_strict_candidates_are_empty():
    report=cube_report()
    finding=next(f for f in report['findings'] if f['id']=='overhang')
    finding.update(status='not_detected',action='기준 각도 부근의 면을 다른 각도와 비교하세요.')
    finding['measurements']['threshold_equal_face_count']=2
    result=item(summarize_review(report),'overhang')
    assert result['needs_action'] and result['level']=='info'
    assert result['next_action']==finding['action']
    assert '기준 각도' in result['state']


def test_recorded_wall_measured_without_criterion_is_still_actionable():
    report = cube_report()
    report["details"] = {"wall": measured_wall(limit=None)}
    result = summarize_review(report)
    wall = item(result, "wall")
    assert wall["needs_action"]
    assert "비교 기준이 없습니다" in wall["state"]


def test_partial_wall_never_inherits_observed_finding_as_a_pass():
    report = cube_report(minimum_wall_mm=1.)
    report["details"] = {"wall": measured_wall(status="partial")}
    next(row for row in report["findings"] if row["id"]=="wall")["status"] = "observed"
    result = summarize_review(report)
    wall = item(result, "wall")
    assert wall["level"] == "warning"
    assert wall["needs_action"]
    assert result["next_item"]["id"] == "wall"


def test_wall_criterion_clear_is_scoped_and_still_leaves_unrun_layers():
    report = cube_report(minimum_wall_mm=1.)
    report["details"] = {"wall": measured_wall()}
    result = summarize_review(report)
    assert item(result, "wall")["level"] == "success"
    assert "검사한 표본" in item(result, "wall")["state"]
    assert not item(result, "wall")["needs_action"]
    assert item(result, "layers")["needs_action"]
    assert result["level"] != "success"


def test_enabled_build_mismatch_is_prioritized_ahead_of_unrun_details():
    result = summarize_review(cube_report(build_volume_mm=(2., 2., 2.)))
    assert item(result, "build")["level"] == "warning"
    assert result["next_item"]["id"] == "build"
    assert result["next_item"]["target"] == "방향 비교"


def test_absent_analytic_holes_does_not_demand_a_meaningless_hole_limit():
    result = summarize_review(cube_report())
    holes = item(result, "cad_holes")
    assert holes["state"] == "내측 원통면 미검출"
    assert not holes["needs_action"]
    assert "원통형이 아닌" in holes["next_action"]


def test_summary_does_not_mutate_audit_report():
    report = cube_report(minimum_wall_mm=1.)
    report["details"] = {"wall": measured_wall(status="partial")}
    original = copy.deepcopy(report)
    summarize_review(report)
    assert report == original


@pytest.mark.parametrize("goal,field,values,expected", [
    ("높이를 낮추기", "height_mm", [1., 20., 3.], ["fit-small", "fit-large", "too-large"]),
    ("하향면 후보 줄이기", "overhang_projected_area_sum_mm2", [0., 10., 2.], ["fit-small", "fit-large", "too-large"]),
    ("평평한 바닥 넓히기", "contact_triangle_area_mm2", [100., 2., 10.], ["fit-small", "fit-large", "too-large"]),
])
def test_direction_goal_ranking_respects_enabled_space_before_metric(goal, field, values, expected):
    report = dict(orientations=[dict(name=name, build_fit=fit, **{field:value})
        for name, fit, value in zip(["too-large", "fit-large", "fit-small"], [False, True, True], values)])
    before = copy.deepcopy(report)
    assert [row["name"] for row in ranked_orientations(report, goal)] == expected
    assert report == before


def test_unmeasured_direction_metric_is_not_ranked_as_zero():
    report = dict(orientations=[dict(name="unknown", build_fit=None, height_mm=None),
                              dict(name="known", build_fit=None, height_mm=10.)])
    assert [row["name"] for row in ranked_orientations(report, "높이를 낮추기")] == ["known"]
