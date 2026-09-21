"""User interpretation contracts, independent of CAD and ray measurement tests."""
from copy import deepcopy
import base64
import json
from pathlib import Path

import numpy as np
import pytest
import trimesh

from amdfm.models import Model, json_bytes
from dfm.machining_view import feature_rows, machining_html, machining_figure


@pytest.mark.parametrize("diameter,expected_radius,expected_difference,comparison", [
    (8., 4., -1., "예"), (4., 2., 1., "아니오"),
    (None, "미입력·미비교", "미입력·미비교", "미입력·미비교"),
])
def test_corner_table_compares_radius_to_radius_and_preserves_missing(diameter, expected_radius, expected_difference, comparison):
    finding = {"id": "cnc_curved_corners", "measurements": {"cylindrical_faces": [
        {"face_id": 17, "radius_mm": 3., "tool_too_large": None if diameter is None else diameter > 6.}]}}
    before = deepcopy(finding)
    row = feature_rows(finding, {"tool_diameter_mm": diameter})[0]
    assert row["CAD 면"] == 17 and row["오목면 반경 (mm)"] == 3.
    assert row["공구 반경 (mm)"] == expected_radius
    assert row["반경 차이 · 면−공구 (mm)"] == expected_difference
    assert row["공구 반경 > 오목면 반경"] == comparison
    assert "공구 지름 > 특징 지름" not in row
    assert finding == before


def test_missing_visibility_categories_do_not_become_zero_count():
    # A partial/imported record may omit categories. Absence is not zero.
    finding = {"id": "cnc_visibility", "measurements": {"sample_state_counts": {"visible": 2}}}
    by_label = {row["표본 분류"]: row["표본 수"] for row in feature_rows(finding)}
    assert by_label["직선이 가려지지 않은 표본"] == 2
    assert by_label["앞이 가려진 표본"] == "미확정"
    assert by_label["계산 미확정 표본"] == "미확정"


def test_equality_boundary_is_explicit_instead_of_an_unqualified_no():
    finding = {"id": "cnc_curved_corners", "measurements": {"cylindrical_faces": [{
        "face_id": 17, "radius_mm": 3., "tool_too_large": False,
        "numerical_boundary_comparisons": ["tool_too_large"],
    }]}}
    row = feature_rows(finding, {"tool_diameter_mm": 6.})[0]
    assert row["반경 차이 · 면−공구 (mm)"] == 0.
    assert row["공구 반경 > 오목면 반경"] == "수치 경계·별도 확인"


def test_axis_mismatch_is_not_presented_as_missing_tool_dimensions():
    finding = {"id": "cnc_holes", "measurements": {"cylindrical_faces": [{
        "face_id": 11, "diameter_mm": 6., "cylindrical_length_mm": 15.,
        "axis_aligned": False, "axis_angle_deg": 90.,
        "tool_too_large": None, "segment_exceeds_reach": None,
    }]}}
    row = feature_rows(finding, {"tool_diameter_mm": 4., "reach_mm": 20.})[0]
    assert row["입력 공구 지름 (mm)"] == 4.
    assert row["입력 돌출 길이 (mm)"] == 20.
    assert row["축 차이 (°)"] == 90.
    assert row["공구 지름 > 특징 지름"] == "축 불일치·미비교"
    assert row["원통 구간 > 돌출 길이"] == "축 불일치·미비교"


def _export_fixture():
    mesh = trimesh.creation.box(extents=[20, 10, 5])
    model = Model(mesh=mesh, metadata={"filename": "<img src=x onerror=alert(1)>.step"})
    report = {"model_fingerprint": model.fingerprint,
              "current_orientation": {"transform": np.eye(4).tolist()},
              "input": {"filename": model.metadata["filename"], "source_sha256": "fixture-sha"},
              "direction": [1., 0., 0.], "created_utc": "2026-09-20T00:00:00Z",
              "profile": {"machine": "미확정", "material": "미확정", "tool_diameter_mm": .001,
                          "flute_length_mm": None, "reach_mm": None, "hole_depth_ratio_limit": None,
                          "basis": "<script>alert(1)</script>"},
              "findings": [{"id": "cnc_curved_corners", "title": "오목 원통면",
                            "status": "observed", "reason": "반경 비교에서 초과 없음", "evidence": ["FIXTURE"],
                            "action": "입구와 실제 경로를 확인하세요.",
                            "measurements": {"cylindrical_faces": [{"face_id": 17, "radius_mm": 3., "tool_too_large": False}]},
                            "limitations": ["전체 가공 경로는 미검토"]}],
              "unassessed": ["공구·홀더·고정구의 실제 경로 충돌"],
              "sources": [{"id": "FIXTURE", "title": "안전한 출처", "url": "https://example.org/cnc"},
                          {"title": "활성 링크로 만들지 않을 출처", "url": "javascript:alert(1)"}],
              "code_revision": "code-sha"}
    return model, report


def test_html_has_portable_shape_human_conditions_and_preserves_precision():
    model, report = _export_fixture()
    before = json_bytes(report)
    output = machining_html(report, model)
    assert '<svg ' in output and '<polygon ' in output
    assert '원본 좌표의 입력 메시 참고도' in output
    assert '검토 방향으로 배치한 입력 메시 참고도' not in output
    assert '이 결과에 적용한 조건' in output
    assert '엔드밀 지름 (mm)' in output and '0.001' in output
    assert '장착 후 돌출 길이 · 공구 끝~홀더 (mm)' in output
    assert '미입력·미비교' in output
    assert '정밀 치수 도면이 아닙니다' in output
    assert '전체 가공 경로는 미검토' in output
    assert '다음 행동:' in output
    assert '이 항목의 근거:' in output
    assert 'cdn' not in output and '<script' not in output
    assert json_bytes(report) == before


def test_html_escapes_user_text_and_rejects_active_non_web_links():
    model, report = _export_fixture()
    output = machining_html(report, model)
    assert '<img src=x' not in output and '&lt;img src=x' in output
    assert '<script>' not in output and '&lt;script&gt;' in output
    assert 'href="https://example.org/cnc"' in output
    assert 'href="javascript:' not in output
    assert '활성 링크로 만들지 않을 출처' in output


def test_html_preserves_local_reference_scope_and_reading_limits_without_fake_link():
    _, report = _export_fixture()
    report["sources"].append({
        "title": "제공한 전문", "url": None, "local_path": "references/machining/원문.pdf",
        "scope": "가시성의 배경 근거이며 <유한 공구> 검증은 아닙니다.",
        "locator": "PDF 2–3쪽", "access": "스캔 전문 검토·일부 OCR 한계",
    })
    before = json_bytes(report)
    output = machining_html(report)
    assert 'href="None"' not in output
    assert '이 검토에서 사용하는 이유와 범위:' in output
    assert '가시성의 배경 근거이며 &lt;유한 공구&gt; 검증은 아닙니다.' in output
    assert '확인할 쪽·항목:</strong> PDF 2–3쪽' in output
    assert '원문 확인 범위:</strong> 스캔 전문 검토·일부 OCR 한계' in output
    assert '저장소 PDF 위치:</strong> references/machining/원문.pdf' in output
    assert json_bytes(report) == before


def test_html_rejects_different_shape_instead_of_attaching_stale_diagram():
    _, report = _export_fixture()
    other = Model(mesh=trimesh.creation.box(extents=[1, 1, 1]), metadata={})
    with pytest.raises(ValueError, match="보고서와 표시할 형상이 다릅니다"):
        machining_html(report, other)


def test_text_only_export_explicitly_identifies_missing_diagram():
    _, report = _export_fixture()
    output = machining_html(report)
    assert '<svg ' not in output
    assert '형상 참고도는 이 보고서에 포함되지 않았습니다' in output


@pytest.mark.parametrize("selection,expected_colors", [
    ([17], ["#c65102"] * 6), ([19], ["#1476b8"] * 6),
    ([17, 19], ["#c65102"] * 6 + ["#1476b8"] * 6),
])
def test_location_colors_follow_original_attention_subset_without_changing_report(selection, expected_colors):
    # Explicit face mapping is a renderer fixture, not a CAD feature assertion.
    model, report = _export_fixture()
    model.face_ids = np.array([17] * 6 + [19] * 6)
    finding = report["findings"][0]
    finding.update(status="attention", face_indices=list(range(6)), cad_face_ids=[17])
    before = json_bytes(report)
    figure = machining_figure(model, report, "cnc_curved_corners", cad_face_ids=selection)
    highlighted = [trace for trace in figure.data if trace.type == "mesh3d" and trace.name != "입력 형상"]
    assert len(highlighted) == 1
    assert list(highlighted[0].facecolor) == expected_colors
    assert len(highlighted[0].i) == len(expected_colors)
    assert json_bytes(report) == before


def _open_rounded():
    from streamlit.testing.v1 import AppTest
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(str(root / "app.py"), default_timeout=75).run()
    app.selectbox(key="manufacturing_family").select("절삭가공").run()
    app.selectbox(key="source").select("절삭 검증 형상").run()
    cases = json.loads((root / "examples/machining/manifest.json").read_text(encoding="utf-8"))
    title = next(row["title"] for row in cases if row["id"] == "03_rounded_pocket")
    app.selectbox(key="cnc_example").select(title).run()
    assert not app.exception
    return app


def _submit(app):
    next(button for button in app.button if button.label == "절삭 설계 검토").click().run()
    assert not app.exception
    return app.session_state["cnc_report"]


def _highlight_trace(app):
    spec = json.loads(app.get("plotly_chart")[0].proto.spec)
    return next(row for row in spec["data"] if row["type"] == "mesh3d" and row.get("name") != "입력 형상")


def _highlight_triangle_count(app):
    trace = _highlight_trace(app)
    indices = trace["i"]
    return len(indices) if isinstance(indices, list) else len(np.frombuffer(base64.b64decode(indices["bdata"]), dtype=indices["dtype"]))


def test_user_can_follow_resolved_corner_condition_and_locate_each_measurement():
    app = _open_rounded()
    for key, value in (("cnc_diameter", 8.), ("cnc_flute", 10.), ("cnc_reach", 15.)):
        app.number_input(key=key).set_value(value)
    report = _submit(app)
    corner = next(row for row in report["findings"] if row["id"] == "cnc_curved_corners")
    assert corner["status"] == "attention"
    assert any("공구축과 나란한 오목 원통면" in row.value for row in app.warning)
    assert {row.label: row.value for row in app.metric}["엔드밀 지름"] == "8 mm"
    table = app.dataframe[0].value
    assert list(table["공구 반경 (mm)"]) == [4.] * 4
    assert list(table["오목면 반경 (mm)"]) == [3.] * 4
    assert list(table["반경 차이 · 면−공구 (mm)"]) == [-1.] * 4
    assert set(_highlight_trace(app)["facecolor"]) == {"#c65102"}
    all_count = _highlight_triangle_count(app)
    selected_face = str(corner["measurements"]["cylindrical_faces"][0]["face_id"])
    app.selectbox(key="cnc_location").set_value(selected_face).run()
    assert not app.exception
    assert 0 < _highlight_triangle_count(app) < all_count
    assert app.selectbox(key="cnc_location").value == selected_face
    assert any("파란색" in row.value and "주황색" in row.value for row in app.caption)

    app.number_input(key="cnc_diameter").set_value(4.)
    report = _submit(app)
    corner = next(row for row in report["findings"] if row["id"] == "cnc_curved_corners")
    assert corner["status"] == "observed"
    assert "더 작은 공구" not in corner["action"] and "반경 확대" not in corner["action"]
    assert "경로" in corner["action"]
    assert app.selectbox(key="cnc_location").value == selected_face
    assert {row.label: row.value for row in app.metric}["엔드밀 지름"] == "4 mm"
    assert list(app.dataframe[0].value["공구 반경 (mm)"]) == [2.] * 4
    assert set(_highlight_trace(app)["facecolor"]) == {"#1476b8"}

    app.number_input(key="cnc_diameter").set_value(6.)
    _submit(app)
    assert list(app.dataframe[0].value["공구 반경 > 오목면 반경"]) == ["수치 경계·별도 확인"] * 4
    assert any("수치상 같은 경계값" in row.value for row in app.info)

    app.number_input(key="cnc_diameter").set_value(None)
    report = _submit(app)
    corner = next(row for row in report["findings"] if row["id"] == "cnc_curved_corners")
    assert corner["status"] == "unknown"
    assert "지름" in corner["action"] and "입력" in corner["action"]
    assert {row.label: row.value for row in app.metric}["엔드밀 지름"] == "미입력"
    assert list(app.dataframe[0].value["공구 반경 (mm)"]) == ["미입력·미비교"] * 4


def test_allowed_small_tool_value_has_nonzero_display_and_applied_condition():
    app = _open_rounded()
    widget = app.number_input(key="cnc_diameter")
    assert float(widget.proto.format % .001) == .001
    widget.set_value(.001)
    report = _submit(app)
    assert report["profile"]["tool_diameter_mm"] == .001
    assert {row.label: row.value for row in app.metric}["엔드밀 지름"] == "0.001 mm"
    assert any("실행 버튼을 누르면 결과에 적용" in row.value for row in app.caption)


def test_custom_small_angle_keeps_visible_value_and_calculation_in_agreement():
    app = _open_rounded()
    app.selectbox(key="cnc_direction").select("직접 각도 입력").run()
    widget = app.number_input(key="cnc_tilt")
    assert float(widget.proto.format % .005) == .005
    widget.set_value(.005).run()
    report = _submit(app)
    expected = np.array([np.sin(np.deg2rad(.005)), 0., np.cos(np.deg2rad(.005))])
    assert np.allclose(report["direction"], expected, rtol=0, atol=1e-12)
    assert app.number_input(key="cnc_tilt").value == .005
