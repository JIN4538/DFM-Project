"""Condition browsing must not silently change inputs or evidence attribution."""
from copy import deepcopy
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from dfm.conditions import ConditionLibrary
import dfm.conditions_view as view


APP = Path(__file__).resolve().parents[1] / "app.py"


def _parameter(value, *, application="automatic", unit="mm", kind="machine_specification"):
    return dict(value=value, unit=unit, application=application, kind=kind,
                source_ids=["ui-test-source"], locator="UI regression fixture", conditions=[])


@pytest.fixture
def library(monkeypatch):
    source = dict(id="ui-test-source", title="Synthetic UI fixture, not a manufacturing recommendation",
                  publisher="UI test", url="https://example.com/fixture", accessed="2026-09-28",
                  locator="Synthetic fixture", revision="1", verification="primary_source_checked", limitations=[])
    def profile(id, process, parameters, **extra):
        return dict(id=id, label=id, process=process, category="tool" if process == "CNC" else "process",
                    machine="UI test machine", material="UI test material", parameters=parameters,
                    conditions=["Synthetic UI test only"], limitations=["Not physical validation"],
                    source_ids=[source["id"]], physical_validation="not_validated_by_project", **extra)
    profiles = [
        profile("am-wall", "MEX", {"minimum_wall_mm": _parameter(5.), "build_volume_mm": _parameter([120., 130., 140.])}),
        profile("am-machine", "MEX", {"build_volume_mm": _parameter([200., 210., 220.])}),
        profile("reference-only", "MEX", {"tensile_strength": _parameter(50., unit="MPa", application="reference_only", kind="material_property")}),
        profile("vpp-wall", "VPP", {"minimum_wall_mm": _parameter(1.)}),
        profile("cnc-tool", "CNC", {"tool_diameter_mm": _parameter(16., kind="tool_specification"),
                                      "flute_length_mm": _parameter(20., kind="tool_specification")}),
        profile("cnc-small-tool", "CNC", {"tool_diameter_mm": _parameter(4., kind="tool_specification")}),
    ]
    result = ConditionLibrary([dict(schema_version=1, sources=[source], profiles=profiles)])
    monkeypatch.setattr(view, "load_library", lambda: result)
    return result


def _submit(app, label="설계 검토"):
    next(button for button in app.button if button.label == label).click().run()
    assert not app.exception
    return app.session_state["cnc_report" if label.startswith("절삭") else "report"]


def _choose(app, profile_id, process="MEX"):
    app.selectbox(key=f"condition_preview_{process}").select(profile_id).run()
    assert not app.exception
    return app


def _apply(app, profile_id, process="MEX"):
    _choose(app, profile_id, process)
    app.button(key=f"apply_condition_{process}").click().run()
    assert not app.exception
    return app


def test_preview_is_not_application_and_reference_material_cannot_apply(library):
    app = AppTest.from_file(str(APP), default_timeout=90).run()
    _choose(app, "am-wall")
    assert app.number_input(key="wall_limit_MEX").value == 1.2
    assert _submit(app)["profile"]["condition_evidence"] == {}
    _choose(app, "reference-only")
    assert not any(button.key == "apply_condition_MEX" for button in app.button)
    assert any("참고용 자료" in x.value for x in app.info)
    assert app.number_input(key="wall_limit_MEX").value == 1.2
    assert not any(item.key == "condition_search_MEX" for item in app.text_input)
    # The native dropdown performs search and retains the complete scrollable list.
    assert len(app.selectbox(key="condition_preview_MEX").options) == 4


def test_am_apply_changes_real_review_and_tracks_override_and_disabled_build(library):
    app = AppTest.from_file(str(APP), default_timeout=90).run()
    _apply(app, "am-wall")
    assert app.number_input(key="wall_limit_MEX").value == 5.
    assert not app.checkbox(key="use_build_MEX").value
    assert [app.session_state[f"build_{axis}_MEX"] for axis in "XYZ"] == [120., 130., 140.]
    assert not any((w.key or '').startswith('build_') for w in app.number_input)
    report = _submit(app)
    evidence = report["profile"]["condition_evidence"]
    assert evidence["profile_id"] == "am-wall"
    assert evidence["fields"]["build_volume_mm"]["status"] == "disabled"
    assert evidence["fields"]["minimum_wall_mm"]["status"] == "source_value"
    wall = report["details"]["wall"]["measurements"]
    assert wall["minimum_mm"] == pytest.approx(4.)
    assert wall["minimum_wall_mm"] == 5.
    assert wall["below_limit_face_indices"]
    app.number_input(key="wall_limit_MEX").set_value(3.)
    report = _submit(app)
    field = report["profile"]["condition_evidence"]["fields"]["minimum_wall_mm"]
    assert field == dict(expected=5., effective=3., overridden=True, status="user_override")
    assert not report["details"]["wall"]["measurements"]["below_limit_face_indices"]
    _apply(app, "am-machine")
    assert app.number_input(key="wall_limit_MEX").value == 1.2
    assert app.number_input(key="hole_limit_MEX").value is None
    assert not app.checkbox(key="use_build_MEX").value
    app.number_input(key="wall_limit_MEX").set_value(1.)
    report = _submit(app)
    evidence = report["profile"]["condition_evidence"]
    assert "minimum_wall_mm" not in evidence["fields"]
    assert evidence["user_inputs"]["minimum_wall_mm"]["effective"] == 1.
    assert evidence["user_inputs"]["minimum_wall_mm"]["status"] == "user_input_or_exploration_default"
    # Provenance stays available in the evidence tab; the conclusion page no
    # longer duplicates the full library explanation before the AI result.
    app.segmented_control(key='result_tab').set_value('근거·내보내기').run()
    assert not app.exception
    assert app.session_state['report']['profile']['condition_evidence'] == evidence
    assert any("자료에 없는 직접 입력" in item.value for item in app.markdown)


def test_condition_switches_are_separate_and_clear_resets_baseline(library):
    app = AppTest.from_file(str(APP), default_timeout=90).run()
    _apply(app, "am-wall")
    app.selectbox(key="process").select("VPP").run()
    assert app.number_input(key="wall_limit_VPP").value == .4
    _apply(app, "vpp-wall", "VPP")
    app.selectbox(key="process").select("MEX").run()
    assert app.number_input(key="wall_limit_MEX").value == 5.
    app.button(key="clear_condition_MEX").click().run()
    assert not app.exception
    assert app.number_input(key="wall_limit_MEX").value == 1.2
    assert app.selectbox(key="machine_MEX").value == "미확정"
    assert _submit(app)["profile"]["condition_evidence"] == {}
    app.selectbox(key="process").select("VPP").run()
    assert app.number_input(key="wall_limit_VPP").value == 1.


def test_stale_database_blocks_review_until_reapply_or_clear(library, monkeypatch):
    app = AppTest.from_file(str(APP), default_timeout=90).run()
    _apply(app, "am-wall")
    changed = deepcopy(library)
    changed.digest = "changed-database-fixture"
    monkeypatch.setattr(view, "load_library", lambda: changed)
    app.run()
    assert not app.exception
    assert next(b for b in app.button if b.label == "설계 검토").disabled
    assert app.button(key="start_from_model").disabled
    assert any("변경되어 검토를 보류" in x.value for x in app.warning)
    app.button(key="clear_condition_MEX").click().run()
    assert not app.exception
    assert not next(b for b in app.button if b.label == "설계 검토").disabled


def test_cnc_application_keeps_mount_reach_unknown_and_changes_feature_comparison(library):
    app = AppTest.from_file(str(APP), default_timeout=90).run()
    app.selectbox(key="manufacturing_family").select("절삭가공").run()
    app.selectbox(key="source").select("절삭 시연용 형상").run()
    app.number_input(key="cnc_reach").set_value(100.)
    _apply(app, "cnc-tool", "CNC")
    assert app.number_input(key="cnc_diameter").value == 16.
    assert app.number_input(key="cnc_reach").value is None
    report = _submit(app, "절삭 설계 검토")
    pocket = next(f for f in report["findings"] if f["id"] == "cnc_rectangular_pockets")["measurements"]["pockets"][0]
    assert pocket["width_too_small"] is True
    assert report["profile"]["condition_evidence"]["profile_id"] == "cnc-tool"
    from dfm.machining_view import machining_html
    assert "적용한 조건 DB" in machining_html(report)
    _apply(app, "cnc-small-tool", "CNC")
    assert app.number_input(key="cnc_flute").value is None
    assert app.number_input(key="cnc_reach").value is None
    report = _submit(app, "절삭 설계 검토")
    pocket = next(f for f in report["findings"] if f["id"] == "cnc_rectangular_pockets")["measurements"]["pockets"][0]
    assert pocket["width_too_small"] is False


def test_published_library_can_be_applied_in_all_supported_process_views():
    from dfm.conditions import load_library
    actual_library = load_library()
    app = AppTest.from_file(str(APP), default_timeout=90).run()
    for process in ("MEX", "VPP", "PBF_POLYMER", "PBF_METAL", "CNC"):
        candidates = [r for r in actual_library.profiles_for(process)
                      if any(p["application"] == "automatic" for p in r["parameters"].values())]
        # A process containing reference information only must not fabricate a
        # preset simply to make this integration test pass.
        if not candidates:
            continue
        selected = max(candidates, key=lambda r: sum(p["application"] == "automatic" for p in r["parameters"].values()))
        if process == "CNC":
            app.selectbox(key="manufacturing_family").select("절삭가공").run()
        else:
            app.selectbox(key="process").select(process).run()
        _apply(app, selected["id"], process)
        report = _submit(app, "절삭 설계 검토" if process == "CNC" else "설계 검토")
        evidence = report["profile"]["condition_evidence"]
        assert evidence["profile_id"] == selected["id"]
        assert evidence["database_sha256"] == actual_library.digest
        for key, expected in actual_library.resolve(selected["id"], process)["values"].items():
            assert report["profile"][key] == (None if key == "build_volume_mm" else expected)
        assert not app.exception
