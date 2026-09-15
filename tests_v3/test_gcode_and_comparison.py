import copy
import math
from pathlib import Path

import pytest
import trimesh

from amdfm.analysis import review
from amdfm.comparison import compare_designs
from amdfm.gcode import inspect_gcode
from amdfm.io import load_model
from amdfm.profiles import Profile


def parse(text,**kwargs):
    return inspect_gcode(text.encode(),2.,**kwargs)


def test_absolute_relative_extrusion_reset_retraction_debt():
    code="""G21
G90
M82
G92 E0
G0 X0 Y0 Z0.2
;TYPE:WALL-OUTER
G1 X10 E1
G1 E0.5
G1 X20 E1.5
G92 E0
M83
G1 X30 E2
"""
    result=parse(code)
    assert result["status"]=="parsed"
    assert result["total_commanded_volume_mm3"]==pytest.approx(3.5*math.pi)
    assert result["parsed_segments"]==3
    assert result["by_type"]["WALL-OUTER"]["path_mm"]==30


def test_marlin_g91_resets_e_mode_and_inch_conversion():
    result=parse("G20\nG90\nM82\nG0 X0 Y0 Z1\nG1 X1 E1\nG91\nG1 X1 E1\n")
    assert result["total_commanded_volume_mm3"]==pytest.approx(50.8*math.pi)
    assert result["segments"][-1]["end"][0]==pytest.approx(50.8)


@pytest.mark.parametrize("command",["G2 X10 Y0 E1 I5","M200 D1.75","M221 S90","T1","G10","G54","G1.1 X10 E1","G90 M83"])
def test_unsupported_modes_cannot_publish_total(command):
    result=parse("G0 X0 Y0 Z0.2\n"+command+"\nG1 X10 E1\n")
    assert result["status"]=="partial"
    assert result["total_commanded_volume_mm3"] is None


def test_unknown_position_and_budget_stay_partial():
    assert parse("G28\nG1 X10 E1")["status"]=="partial"
    result=parse("G0 X0 Y0 Z0.2\nG1 X10 E1\nG1 X20 E2\n",max_segments=1)
    assert result["status"]=="partial" and result["total_commanded_volume_mm3"] is None


def test_no_paths_is_zero_commanded_extrusion_not_print_success():
    result=parse("G21\nG90\nG0 X10 Y0 Z1\nG0 X20\n")
    assert result["total_commanded_volume_mm3"]==0
    assert result["parsed_segments"]==0
    assert "success" not in result


def test_design_comparison_refuses_profile_and_scale_mismatch():
    data=trimesh.creation.box().export(file_type="stl")
    model=load_model(data,"part.stl",dimensions_confirmed=True)
    a=review(model,Profile())
    b=copy.deepcopy(a)
    b["geometry"]["exact_cad_volume_mm3"]=2.
    a["geometry"]["exact_cad_volume_mm3"]=1.
    c=compare_designs(a,b)
    assert c["comparable"]
    assert next(r["차이"] for r in c["metrics"] if r["항목"]=="CAD 체적 (mm³)")==1.
    b["profile"]["overhang_angle_deg"]=40
    assert not compare_designs(a,b)["comparable"]
    b=copy.deepcopy(a);b["model"]["unit_status"]="assumed"
    assert all(r["차이"] is None for r in compare_designs(a,b)["metrics"])
