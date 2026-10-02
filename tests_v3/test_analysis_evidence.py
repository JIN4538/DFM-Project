"""Report evidence and material semantics must follow the actual input/process."""
import copy

import numpy as np
import pytest
import trimesh

from amdfm.analysis import review
from amdfm.evidence import section_guidance, sources_for
from amdfm.models import Model
from amdfm.profiles import PROCESS_LABELS, Profile


def box_model(source_format="stl", **metadata):
    mesh = trimesh.creation.box(extents=[10, 5, 4])
    meta = dict(source_format=source_format, unit_status="user_confirmed",
                surface_component_count=1, solid_count=1 if source_format in ("step", "stp") else None)
    meta.update(metadata)
    face_ids = np.arange(len(mesh.faces)) if source_format in ("step", "stp") else None
    return Model(mesh, meta, face_ids=face_ids)


def findings(report):
    return {item["id"]: item for item in report["findings"]}


@pytest.mark.parametrize("process", PROCESS_LABELS)
def test_report_integrates_process_evidence_and_unrun_sections(process):
    result = review(box_model(), Profile(process=process), compare=False)
    checks = findings(result)
    for check in ("wall", "overhang", "cad_holes", "cavities", "sections"):
        assert checks[check]["evidence"] == sources_for(check, process)
        assert set(checks[check]["evidence"]) <= result["sources"].keys()
    assert checks["sections"]["status"] == "unknown"
    assert checks["sections"]["measurements"] == {}
    assert checks["sections"]["title"] == section_guidance(process)["title"]
    assert section_guidance(process)["reason"] in checks["sections"]["reason"]
    assert checks["sections"]["limitations"] == section_guidance(process)["limitations"]
    assert ("nominal_line_width_mm" in checks["wall"]["measurements"]) == (process == "MEX")
    if process != "MEX":
        assert not {"JIANG2018", "KUIPERS2020", "PRUSA_ARACHNE"}.intersection(result["sources"])
        assert "선폭" not in checks["wall"]["action"]
    assert result["geometry"]["extents_mm"] == pytest.approx([10, 5, 4])
    assert result["geometry"]["mesh_signed_volume_mm3"] == pytest.approx(200)
    assert result["current_orientation"]["build_fit"] is None


@pytest.mark.parametrize("source_format,expected", [
    ("step", ["ISO52910", "OCCT"]),
    ("stp", ["ISO52910", "OCCT"]),
    ("stl", ["ISO52910", "STL_FORMAT"]),
    ("3mf", ["ISO52910", "3MF_CORE", "3MF_PRODUCTION"]),
])
def test_input_citation_describes_the_actual_file_format(source_format, expected):
    report = review(box_model(source_format), Profile(), compare=False)
    assert findings(report)["input"]["evidence"] == expected


def test_stl_scale_assumption_has_stl_evidence():
    model = box_model(unit_status="assumed", scale_factor=25.4)
    result = review(model, Profile(), compare=False)
    assert findings(result)["scale"]["evidence"] == ["ISO52910", "STL_FORMAT"]
    assert findings(result)["scale"]["measurements"]["scale_factor"] == 25.4


@pytest.mark.parametrize("process", PROCESS_LABELS)
@pytest.mark.parametrize("source_format", ["step", "stp"])
def test_cad_surface_cannot_acquire_material_semantics_from_mesh_or_stale_fields(process, source_format):
    # A geometrically closed tessellation still is not an OCCT solid when its
    # CAD source is only a shell. Older cached semantic fields must not win.
    model = box_model(source_format, cad_geometry_kind="surface", solid_count=0,
                      cavity_shell_count=1, exact_volume_mm3=200., exact_area_mm2=220.)
    model.cad_features = [dict(kind="cylinder", role="inner", face_id=0,
                              diameter_mm=2., axis=[1, 0, 0])]
    original_features = copy.deepcopy(model.cad_features)
    result = review(model, Profile(process=process, minimum_hole_mm=3), compare=True)
    checks = findings(result)
    assert result["summary"]["review_status"] == "partial_geometry"
    assert result["geometry"]["mesh_signed_volume_mm3"] is None
    assert result["geometry"]["exact_cad_volume_mm3"] is None
    assert result["geometry"]["exact_cad_area_mm2"] == 220.
    assert result["geometry"]["mesh_triangle_area_mm2"] == pytest.approx(220)
    assert result["geometry"]["extents_mm"] == pytest.approx([10, 5, 4])
    for check in ("wall", "overhang", "cad_holes", "cavities", "sections"):
        assert checks[check]["status"] == ("not_applicable" if check=="overhang" and process=="PBF_POLYMER" else "unknown")
        assert checks[check]["face_indices"] == []
        assert checks[check]["cad_face_ids"] == []
    holes = checks["cad_holes"]["measurements"]
    assert holes["inner_face_count"] is None
    assert holes["transverse_inner_face_count"] is None
    assert holes["cylindrical_faces"][0]["diameter_mm"] == 2.
    assert holes["cylindrical_faces"][0]["axis"] == [1, 0, 0]
    assert holes["cylindrical_faces"][0]["role"] == "unknown"
    assert checks["cavities"]["measurements"]["internal_shell_count"] is None
    assert result["current_orientation"]["contact_triangle_area_mm2"] is None
    assert all(row["overhang_projected_area_sum_mm2"] is None for row in result["orientations"])
    assert model.cad_features == original_features


@pytest.mark.parametrize("source_format", ["stl", "3mf"])
def test_cad_surface_flag_is_only_interpreted_for_cad_input(source_format):
    result = review(box_model(source_format, cad_geometry_kind="surface"), Profile(), compare=False)
    assert "surface_input" not in findings(result)
    assert result["geometry"]["mesh_signed_volume_mm3"] == pytest.approx(200)


@pytest.mark.parametrize("source_format,metadata,finding_id", [
    ("step", dict(solid_count=2, exact_volume_mm3=400.), "assembly"),
    ("stl", dict(surface_component_count=2), "shells"),
    ("3mf", dict(surface_component_count=1, mesh_instances=[{}, {}]), "shells"),
])
def test_multiple_bodies_keep_volume_and_material_sections_unconfirmed(source_format, metadata, finding_id):
    result = review(box_model(source_format, **metadata), Profile(), compare=False)
    checks = findings(result)
    assert checks[finding_id]["status"] == "attention"
    assert result["geometry"]["mesh_signed_volume_mm3"] is None
    assert result["geometry"]["exact_cad_volume_mm3"] is None
    assert checks["sections"]["status"] == "unknown"
    assert "합집합" in checks["sections"]["reason"]


def test_mesh_cannot_report_a_cad_cavity_count_from_foreign_metadata():
    result = review(box_model("3mf", cavity_shell_count=0), Profile(), compare=False)
    assert findings(result)["cavities"]["status"] == "unknown"
    assert findings(result)["cavities"]["measurements"]["internal_shell_count"] is None
    assert "STL" not in findings(result)["cad_holes"]["reason"]
    assert "STL" not in findings(result)["cavities"]["reason"]
