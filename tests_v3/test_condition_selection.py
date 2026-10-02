"""Editable starting criteria and a single searchable equipment/material input."""
import pytest
from streamlit.testing.v1 import AppTest

from amdfm.profiles import Profile
from dfm.advisor_view import _name_options
from dfm.conditions import load_library
from dfm.defaults import wall_default, wall_default_value, wall_default_basis, wall_default_context
import dfm.advisor_view as advisor_view


@pytest.mark.parametrize("process,value", [("MEX", 1.2), ("VPP", .4), ("PBF_POLYMER", .6), ("PBF_METAL", .4)])
def test_defaults_have_traceable_basis_and_do_not_fill_backend_unknowns(process, value):
    record = wall_default(process)
    assert record["value_mm"] == wall_default_value(process) == value
    assert record["kind"] == "application_review_default"
    assert record["url"].startswith("https://")
    assert record["source_condition"] and record["selection_reason"] and record["locator"]
    assert record["url"] in wall_default_basis(process)
    assert wall_default_context(process, value)["status"] == "default_value"
    assert wall_default_context(process, value + 1)["status"] == "user_override"
    assert wall_default_context(process, None)["status"] == "disabled"
    assert Profile(process=process).minimum_wall_mm is None
    record["value_mm"] = 999
    assert wall_default_value(process) == value


def test_dropdown_names_stay_in_process_and_retain_unregistered_input():
    lib = load_library()
    mex = _name_options(lib, "MEX", "machine", "My custom printer")
    assert mex[0] == "미확정"
    assert "My custom printer" in mex
    assert "Formlabs Form 4" not in mex
    assert len(mex) == len(set(mex))
    assert _name_options(None, "CNC", "material", "Custom stock") == ["미확정", "Custom stock"]


def test_search_select_and_free_text_share_one_widget(monkeypatch):
    monkeypatch.setattr(advisor_view, "_key", lambda: "")
    app = AppTest.from_string('''
import streamlit as st
from dfm.conditions import load_library
from dfm.advisor_view import render_advisor
st.session_state["test_context"] = render_advisor("MEX", load_library())
''').run()
    assert not app.exception
    for key in ("machine_MEX", "material_MEX"):
        widget = app.selectbox(key=key)
        assert widget.proto.accept_new_options
        assert not any(item.key == key for item in app.text_input)
    # Streamlit 1.63 AppTest requires the frontend-created choice in its local
    # options list before it can send the new string through widget deserialization.
    for key, value in (("machine_MEX", "My custom printer"), ("material_MEX", "My custom material")):
        app.selectbox(key=key).options.append(value)
        app.selectbox(key=key).set_value(value).run()
    assert not app.exception
    assert app.session_state["test_context"]["equipment"] == "My custom printer"
    assert app.session_state["test_context"]["material"] == "My custom material"
    app.run()
    assert app.selectbox(key="machine_MEX").value == "My custom printer"
    assert app.selectbox(key="material_MEX").value == "My custom material"
    app.selectbox(key="machine_MEX").select("Original Prusa MK4S").run()
    assert not app.exception
    assert app.session_state["test_context"]["equipment"] == "Original Prusa MK4S"
    assert not any("중점이 추천에 반영되는 방법" == item.label for item in app.expander)
