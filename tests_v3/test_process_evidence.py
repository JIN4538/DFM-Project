"""Evidence contracts prevent geometric results acquiring unsupported meaning."""
from types import SimpleNamespace

import pytest

from amdfm.evidence import SOURCES, section_guidance, sources_for, used_sources
from amdfm.profiles import PROCESS_LABELS


CHECKS = ("overhang", "wall", "cad_holes", "cavities", "sections")
FDM_ONLY = {"JIANG2018", "KUIPERS2020", "PRUSA_ARACHNE"}


@pytest.mark.parametrize("process", PROCESS_LABELS)
@pytest.mark.parametrize("check", CHECKS)
def test_selected_sources_resolve_and_respect_process_scope(check, process):
    selected = sources_for(check, process)
    assert selected and len(selected) == len(set(selected))
    assert set(selected) <= SOURCES.keys()
    assert "ISO52910" in selected
    if process != "MEX":
        assert not FDM_ONLY.intersection(selected)
    if process != "VPP":
        assert not {"PAN2017", "FORM4", "FORM_ORIENTATION"}.intersection(selected)
    if process != "PBF_POLYMER":
        assert not {"FUSE_DESIGN", "LI2020"}.intersection(selected)
    if process != "PBF_METAL":
        assert not {"MOHR2024", "HUNTER2020", "CHENG2019"}.intersection(selected)


def test_process_evidence_addresses_the_actual_non_fdm_questions():
    assert "PAN2017" in sources_for("sections", "VPP")
    assert "FORM4" in sources_for("wall", "VPP")
    assert "FUSE_DESIGN" in sources_for("overhang", "PBF_POLYMER")
    assert "LI2020" in sources_for("sections", "PBF_POLYMER")
    assert "MOHR2024" in sources_for("sections", "PBF_METAL")
    assert "HUNTER2020" in sources_for("cavities", "PBF_METAL")
    assert "CHENG2019" in sources_for("overhang", "PBF_METAL")


@pytest.mark.parametrize("source,conditions", [
    ("PAN2017", ("bottom-up", "PDMS", "LS600M", "G+", "점도")),
    ("FORM4", ("Grey Resin V5", "50 µm", "100 µm", "후경화")),
    ("FUSE_DESIGN", ("Fuse Series", "Nylon 12", "재료별")),
    ("LI2020", ("EP-P3850", "FS3300PA", "PA12", "0.10–0.19 mm", "스캔각")),
    ("MOHR2024", ("SLM280HL", "316L", "275 W", "700 mm/s", "0.05 mm", "100°C")),
    ("HUNTER2020", ("Ti-6Al-4V", "L-PBF", "EBSM", "XCT")),
])
def test_empirical_sources_preserve_machine_material_and_experimental_conditions(source, conditions):
    entry = SOURCES[source]
    assert {"title", "url", "kind", "locator", "use", "access"} <= entry.keys()
    assert entry["url"].startswith("https://")
    description = " ".join(entry.values())
    for condition in conditions:
        assert condition in description


def test_partial_access_and_publisher_content_error_are_not_hidden():
    assert "초록·서론" in SOURCES["CHENG2019"]["access"]
    assert "완료한 것으로 사용하지 않음" in SOURCES["CHENG2019"]["access"]
    assert "중복 문단" in SOURCES["FUSE_DESIGN"]["access"]


@pytest.mark.parametrize("process", PROCESS_LABELS)
def test_guidance_has_actions_and_keeps_sampling_scope(process):
    guidance = section_guidance(process)
    assert set(guidance) == {"title", "reason", "action", "limitations"}
    assert guidance["title"] and guidance["reason"] and guidance["action"]
    assert isinstance(guidance["limitations"], list)
    assert any("전역 최대가 아닙니다" in item for item in guidance["limitations"])


def test_vpp_guidance_cannot_be_read_as_a_general_force_or_cup_prediction():
    guidance = section_guidance("VPP")
    assert "Bottom-up" in guidance["reason"]
    limitations = " ".join(guidance["limitations"])
    assert "A/P의 단위는 mm" in limitations
    assert "박리력·성공률을 계산하지 않습니다" in limitations
    assert "흡착 컵 확정이 아닙니다" in limitations
    assert "Top-down" in limitations


def test_pbf_guidance_preserves_physics_and_support_uncertainty():
    polymer = " ".join(section_guidance("PBF_POLYMER")["limitations"])
    metal = " ".join(section_guidance("PBF_METAL")["limitations"])
    assert "지지 실패를 판정하지 않습니다" in polymer
    assert "FDM 선폭·브리지 규칙을 적용하지 않습니다" in polymer
    assert "예측값이 아닙니다" in polymer
    assert "작아져도 온도는 상승" in metal
    assert "환산하지 않습니다" in metal
    assert "출력 실패를 확정하지 않습니다" in metal


def test_returned_lists_cannot_corrupt_later_reports():
    selected = sources_for("sections", "VPP")
    selected.clear()
    guidance = section_guidance("VPP")
    guidance["limitations"].clear()
    guidance["title"] = "changed"
    assert "PAN2017" in sources_for("sections", "VPP")
    assert section_guidance("VPP")["limitations"]
    assert section_guidance("VPP")["title"] != "changed"


@pytest.mark.parametrize("check,process", [("missing", "MEX"), ("wall", "FDM"), ("sections", "SLA")])
def test_invalid_keys_do_not_silently_fall_back_to_another_process(check, process):
    with pytest.raises(ValueError):
        sources_for(check, process)


def test_invalid_guidance_process_does_not_default_to_melt_extrusion():
    with pytest.raises(ValueError):
        section_guidance("SLA")


def test_used_sources_remains_compatible_and_ordered():
    findings = [SimpleNamespace(evidence=sources_for("sections", "VPP")),
                SimpleNamespace(evidence=["PAN2017", "FORM4"])]
    selected = used_sources(findings)
    assert list(selected) == ["ISO52910", "MOYLAN2014", "NIST_GAUSS", "PAN2017", "FORM_ORIENTATION", "FORM4"]
    assert selected["PAN2017"] == SOURCES["PAN2017"]
    assert used_sources([]) == {}
