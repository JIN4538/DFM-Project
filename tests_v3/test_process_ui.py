"""Regression checks for process-specific inputs and MEX-only toolpaths."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


APP = Path(__file__).resolve().parents[1] / "app.py"
SETTINGS = {
    "MEX": dict(machine="Prusa MK4", material="PLA", wall=.9, hole=2., layer=.15, angle=41.),
    "VPP": dict(machine="Form 4", material="Grey Resin V5", wall=.4, hole=1., layer=.035, angle=38.),
    "PBF_POLYMER": dict(machine="Fuse 1+ 30W", material="Nylon 12", wall=.6, hole=3., layer=.12, angle=45.),
    "PBF_METAL": dict(machine="SLM280HL", material="316L", wall=.8, hole=4., layer=.025, angle=33.),
}


def _submit(app):
    next(button for button in app.button if button.label == "설계 검토").click().run()
    assert not app.exception


def _assert_profile(app, process, index):
    profile = app.session_state["report"]["profile"]
    values = SETTINGS[process]
    assert profile["process"] == process
    assert profile["machine"] == values["machine"]
    assert profile["material"] == values["material"]
    assert profile["slicer"] == f"{process} slicer test"
    assert profile["minimum_wall_mm"] == values["wall"]
    assert profile["minimum_hole_mm"] == values["hole"]
    assert profile["threshold_basis"] == f"{process} test coupon only"
    assert profile["process_notes"] == f"{process} process notes"
    assert profile["layer_height_mm"] == values["layer"]
    assert profile["overhang_angle_deg"] == values["angle"]
    assert profile["build_volume_mm"] == [110. + index, 120. + index, 130. + index]
    assert profile["clearance_mm"] == .5 + index


def test_process_calibrations_are_independent_and_survive_round_trips():
    app = AppTest.from_file(str(APP), default_timeout=90).run()
    assert not app.exception
    for index, (process, values) in enumerate(SETTINGS.items()):
        if app.selectbox(key="process").value != process:
            app.selectbox(key="process").select(process).run()
        assert not app.exception
        # Opening a new process must not inherit the previous process's calibration.
        assert app.text_input(key=f"machine_{process}").value == "미확정"
        assert app.text_input(key=f"material_{process}").value == "미확정"
        assert app.text_input(key=f"slicer_{process}").value == "미확정"
        assert app.number_input(key=f"wall_limit_{process}").value is None
        assert app.number_input(key=f"hole_limit_{process}").value is None
        assert app.text_input(key=f"basis_{process}").value == "사용자 탐색 조건; 실물 시편으로 보정하지 않음"
        assert not app.checkbox(key=f"use_build_{process}").value
        assert app.number_input(key=f"clearance_{process}").value == 0.
        app.text_input(key=f"machine_{process}").set_value(values["machine"])
        app.text_input(key=f"material_{process}").set_value(values["material"])
        app.text_input(key=f"slicer_{process}").set_value(f"{process} slicer test")
        app.number_input(key=f"wall_limit_{process}").set_value(values["wall"])
        app.number_input(key=f"hole_limit_{process}").set_value(values["hole"])
        app.text_input(key=f"basis_{process}").set_value(f"{process} test coupon only")
        app.text_area(key=f"notes_{process}").set_value(f"{process} process notes")
        app.number_input(key=f"layer_{process}").set_value(values["layer"])
        if process != "PBF_POLYMER":
            app.number_input(key=f"angle_{process}").set_value(values["angle"])
        app.checkbox(key=f"use_build_{process}").check()
        for axis, dimension in zip("XYZ", (110., 120., 130.)):
            app.number_input(key=f"build_{axis}_{process}").set_value(dimension + index)
        app.number_input(key=f"clearance_{process}").set_value(.5 + index)
        _submit(app)
        _assert_profile(app, process, index)

    # Return to hidden widgets: each process must restore its own full profile.
    for index in reversed(range(len(SETTINGS))):
        process = list(SETTINGS)[index]
        app.selectbox(key="process").select(process).run()
        _submit(app)
        _assert_profile(app, process, index)


@pytest.mark.parametrize("process", ["VPP", "PBF_POLYMER", "PBF_METAL"])
def test_non_mex_review_does_not_offer_filament_gcode_analysis(process):
    app = AppTest.from_file(str(APP), default_timeout=90).run()
    _submit(app)
    app.segmented_control(key="result_tab").set_value("정밀 검토").run()
    # Positive control: the existing MEX workflow remains available.
    assert app.checkbox(key='show_gcode_practice').value is False
    assert app.number_input(key="filament_diameter").value == 1.75
    app.selectbox(key="process").select(process).run()
    _submit(app)
    app.segmented_control(key="result_tab").set_value("정밀 검토").run()
    assert not app.exception
    app.segmented_control(key='detail_focus').set_value('층간').run()
    assert app.button(key="run_layers").disabled
    assert not any(item.key in ("gcode_source", "gcode_example") for item in app.selectbox)
    assert not any(item.key=='show_gcode_practice' for item in app.checkbox)
    assert not any(item.key == "filament_diameter" for item in app.number_input)
    assert not any(item.key == "gcode_upload" for item in app.get("file_uploader"))
    assert not any("G-code" in item.label for item in app.expander)
