"""Independent uncertainty and user-visible contracts for machining review.

Feature fixtures here deliberately test orchestration, not CAD recognition.
Analytic CAD accuracy and actual ray calculations have separate geometric tests.
"""
from copy import deepcopy
import subprocess
from unittest.mock import patch

import numpy as np
import pytest
import trimesh

from amdfm.models import Model, json_bytes
from dfm.machining import MachiningProfile, review_machining
from dfm.machining_view import feature_rows, machining_html, visibility_figure


def _cylinder(face_id, *, role="inner", full=False, diameter=4.):
    return {"face_id": face_id, "body_id": 1, "kind": "cylinder", "role": role,
            "full_circumference": full, "axis": [0., 0., 1.],
            "diameter_mm": diameter, "axial_extent_mm": 10.}


def _model(features=None):
    # Face-to-mesh correspondence is explicit solely to test preserved IDs.
    features = features or [_cylinder(7, role="outer")]
    mesh = trimesh.creation.box(extents=[2, 2, 2])
    face_ids = np.resize([f["face_id"] for f in features], len(mesh.faces))
    return Model(mesh=mesh, metadata={"source_format": "step", "cad_geometry_kind": "solid",
        "solid_count": 1, "cad_valid": True, "filename": "contract-fixture.step"},
        cad_features=features, face_ids=face_ids, body_ids=np.ones(len(mesh.faces), dtype=int))


def _finding(report, identifier):
    return next(row for row in report["findings"] if row["id"] == identifier)


@pytest.mark.parametrize("full", [False, True], ids=["partial-cylinder", "full-cylinder"])
def test_unknown_material_side_preserves_hole_and_corner_uncertainty(full):
    model = _model([_cylinder(17, role="unknown", full=full)])
    report = review_machining(model, MachiningProfile(tool_diameter_mm=2, reach_mm=20))
    for identifier in ("cnc_coverage", "cnc_holes", "cnc_curved_corners"):
        finding = _finding(report, identifier)
        assert finding["status"] == "unknown"
        assert finding["measurements"]["unresolved_cylinder_face_ids"] == [17]
    for identifier in ("cnc_holes", "cnc_curved_corners"):
        finding = _finding(report, identifier)
        assert "미확정" in finding["reason"] or "확정하지 못한" in finding["reason"]
        assert finding["measurements"]["cylindrical_faces"] == []
        assert "찾지 못했습니다" not in finding["reason"]
    assert "판단에 필요한 정보 부족" in machining_html(report)


@pytest.mark.parametrize("unknown_full", [False, True])
def test_confirmed_bad_corner_survives_other_unresolved_cylinders(unknown_full):
    model = _model([_cylinder(4, diameter=2), _cylinder(19, role="unknown", full=unknown_full)])
    report = review_machining(model, MachiningProfile(tool_diameter_mm=3, reach_mm=20))
    corner = _finding(report, "cnc_curved_corners")
    assert corner["status"] == "attention"
    assert corner["cad_face_ids"] == [4]
    assert set(model.face_ids[corner["face_indices"]]) == {4}
    assert corner["measurements"]["unresolved_cylinder_face_ids"] == [19]
    rows = corner["measurements"]["cylindrical_faces"]
    assert rows == [{"face_id": 4, "radius_mm": 1., "tool_too_large": True}]
    assert "미확정" in corner["reason"] and "1개" in corner["reason"]
    assert _finding(report, "cnc_holes")["status"] == "unknown"


def test_known_hole_conflict_is_not_erased_by_unresolved_neighbor():
    model = _model([_cylinder(4, full=True, diameter=2), _cylinder(19, role="unknown")])
    report = review_machining(model, MachiningProfile(tool_diameter_mm=3, reach_mm=20))
    hole = _finding(report, "cnc_holes")
    assert hole["status"] == "attention" and hole["cad_face_ids"] == [4]
    assert hole["measurements"]["unresolved_cylinder_face_ids"] == [19]


def test_missing_tool_diameter_does_not_report_zero_failed_corner_comparisons():
    model = _model([_cylinder(4, diameter=2), _cylinder(19, role="unknown")])
    report = review_machining(model, MachiningProfile())
    finding = _finding(report, "cnc_curved_corners")
    assert finding["status"] == "unknown"
    assert finding["measurements"]["cylindrical_faces"][0]["tool_too_large"] is None
    assert finding["measurements"]["unresolved_cylinder_face_ids"] == [19]
    assert "공구보다 작은 반경은 0개" not in finding["reason"]
    assert "공구 지름" in finding["reason"] and ("미입력" in finding["reason"] or "보류" in finding["reason"])


@pytest.mark.parametrize("error", [subprocess.TimeoutExpired("point-worker", 1), OSError("worker unavailable")],
                         ids=["timeout", "start-failure"])
def test_worker_failure_cannot_be_presented_as_zero_obstructions(error):
    model = _model()
    with patch("amdfm.processes.run_bounded", side_effect=error):
        report = review_machining(model, MachiningProfile(), visibility=True)
    finding = _finding(report, "cnc_visibility")
    assert finding["status"] == "unknown"
    assert finding["measurements"]["area_weighted_sample_fractions"] is None
    assert "확정하지 못했습니다" in finding["reason"]
    for text in (finding["reason"], machining_html(report)):
        assert "가려짐 0개" not in text and "가림 0개" not in text
        assert "가려진 표본은 0개" not in text
    assert feature_rows(finding) == []
    figure = visibility_figure(model, report, (0, 0, 1))
    assert not [trace for trace in figure.data if trace.type == "scatter3d" and trace.mode == "markers"]


def _visibility_report():
    # Unequal counts and distinct coordinates expose accidental row collapsing,
    # state substitutions and plotting triangle centroids instead of samples.
    samples = [
        {"state": "visible", "source_face": 4, "point_mm": [.15, -.25, 1.]},
        {"state": "visible", "source_face": 6, "point_mm": [-.45, .25, 1.]},
        {"state": "back_facing", "source_face": 3, "point_mm": [.15, -.25, -1.]},
        {"state": "tangent", "source_face": 0, "point_mm": [-1., .15, .35]},
        {"state": "unknown", "source_face": 1, "point_mm": [.1, -1., .3]},
        {"state": "unknown", "source_face": 5, "point_mm": [.2, -1., .5]},
        {"state": "occluded", "source_face": 6, "point_mm": [.6, .1, 1.]},
    ]
    # This is a renderer fixture, not a claim these classifications occur on
    # the underlying cube. The independent ray tests establish geometry.
    counts = {"visible": 2, "back_facing": 1, "tangent": 1, "unknown": 2, "occluded": 1}
    access = {"status": "partial", "reason": "일부 표본은 경계 접촉으로 미확정입니다.",
              "samples": samples, "occluded_face_indices": [6], "limitations": ["실제 공구·홀더 충돌은 미검토입니다."],
              "measurements": {"sample_state_counts": counts, "selected_samples": 7,
                  "evaluated_samples": 5, "omitted_face_count": 6}}
    model = _model()
    with patch("dfm.accessibility.run_point_visibility", return_value=access):
        report = review_machining(model, MachiningProfile(), visibility=True)
    return model, report


_KOREAN_LABELS = {
    "visible": "직선이 가려지지 않은 표본",
    "occluded": "앞이 가려진 표본",
    "back_facing": "공구 반대쪽을 향한 표본",
    "tangent": "공구축과 평행한 면의 표본",
    "unknown": "계산 미확정 표본",
}


def test_every_sample_state_is_summarized_in_korean_including_unknown():
    _, report = _visibility_report()
    rows = feature_rows(_finding(report, "cnc_visibility"))
    by_label = {row["표본 분류"]: row for row in rows}
    counts = report["visibility"]["measurements"]["sample_state_counts"]
    assert set(by_label) == set(_KOREAN_LABELS.values())
    for state, label in _KOREAN_LABELS.items():
        assert by_label[label]["표본 수"] == counts[state]
        assert by_label[label]["해석·다음 행동"]
    assert "미확인" in by_label[_KOREAN_LABELS["visible"]]["해석·다음 행동"]
    assert "별도 확인" in by_label[_KOREAN_LABELS["tangent"]]["해석·다음 행동"]
    html = machining_html(report)
    assert all(label in html for label in _KOREAN_LABELS.values())
    assert "기하 검토이며 실제 가공 성공 판정이 아닙니다" in html


@pytest.mark.parametrize("category", ["all", *_KOREAN_LABELS])
def test_visibility_uses_recorded_points_and_symbols_not_face_coloring(category):
    model, report = _visibility_report()
    before = json_bytes(report)
    figure = visibility_figure(model, report, (0, 0, 1), category)
    meshes = [trace for trace in figure.data if trace.type == "mesh3d"]
    assert len(meshes) == 1
    assert len(meshes[0].i) == len(model.mesh.faces)
    assert meshes[0].name == "입력 형상"
    assert meshes[0].facecolor is None and meshes[0].intensity is None
    markers = [trace for trace in figure.data if trace.type == "scatter3d" and trace.mode == "markers"]
    expected_states = list(_KOREAN_LABELS) if category == "all" else [category]
    assert {trace.name for trace in markers} == {_KOREAN_LABELS[state] for state in expected_states}
    for state in expected_states:
        trace = next(trace for trace in markers if trace.name == _KOREAN_LABELS[state])
        rows = [row for row in report["visibility"]["samples"] if row["state"] == state]
        assert np.column_stack([trace.x, trace.y, trace.z]) == pytest.approx(np.asarray([row["point_mm"] for row in rows]))
        assert list(trace.customdata) == [row["source_face"] for row in rows]
    if category == "all":
        assert sum(len(trace.x) for trace in markers) == 7
        assert len({trace.marker.symbol for trace in markers}) == 5
        assert len({trace.marker.color for trace in markers}) == 5
    assert json_bytes(report) == before


def test_cylindrical_span_comparison_label_does_not_claim_total_entry_reach():
    model = _model([_cylinder(9, full=True)])
    report = review_machining(model, MachiningProfile(tool_diameter_mm=2, reach_mm=20))
    finding = _finding(report, "cnc_holes")
    row = feature_rows(finding)[0]
    assert row["원통 구간 길이 (mm)"] == 10
    assert row["원통 구간 > 돌출 길이"] == "아니오"
    assert "도달 길이 초과" not in row and "가공 가능" not in row
    assert any("홀 전체 깊이" in text for text in finding["limitations"])


@pytest.mark.parametrize("flute_comparison,reach_comparison", [(False, False), (True, True), (None, None)])
def test_pocket_table_names_local_wall_height_and_keeps_missing_values(flute_comparison, reach_comparison):
    finding = {"id": "cnc_rectangular_pockets", "measurements": {"pockets": [{
        "floor_face_id": 12, "wall_height_mm": 2., "width_mm": 8.,
        "exceeds_flute_length": flute_comparison, "exceeds_reach": reach_comparison,
    }]}}
    before = deepcopy(finding)
    row = feature_rows(finding)[0]
    expected = {False: "아니오", True: "예", None: "미입력·미비교"}
    assert row["벽 높이 (mm)"] == 2
    assert row["벽 높이 > 날 길이"] == expected[flute_comparison]
    assert row["벽 높이 > 돌출 길이"] == expected[reach_comparison]
    assert "도달 길이 초과" not in row and "날 길이 초과" not in row
    assert finding == before


def test_complete_face_information_is_not_described_as_all_pockets_recognized():
    report = review_machining(_model(), MachiningProfile())
    finding = _finding(report, "cnc_coverage")
    assert "특징 인식 범위" in finding["title"]
    assert any("경계 추출 완료와 전체 포켓" in text for text in finding["limitations"])
    assert any("4변 외 평면 바닥" in text and "제외" in text for text in finding["limitations"])
