"""Keep supplied standard editions and manufacturing scope separate in reports."""
import pytest
import trimesh

from amdfm.analysis import review
from amdfm.evidence import SOURCES
from amdfm.models import Model
from amdfm.profiles import Profile


@pytest.mark.parametrize("process", ["MEX", "VPP", "PBF_POLYMER", "PBF_METAL"])
def test_report_uses_supplied_ks_edition_and_only_applicable_process_standards(process):
    model = Model(mesh=trimesh.creation.box(extents=[10, 10, 10]),
                  metadata={"source_format": "stl"})
    report = review(model, Profile(process=process), compare=False)
    sources = report["sources"]
    assert "KS52901_2017" in sources
    assert "KS52902_2019" in sources
    # The supplied 2019-based KS capture must not promote the 2023 ISO scope
    # record to full-text status or masquerade as a new standard edition.
    assert "ISO52902" not in sources
    assert SOURCES["ISO52902"]["kind"] == "standard_scope"
    mex_standards = {"KS52903_1_2020", "KS52903_2_2020"}
    assert mex_standards.intersection(sources) == (mex_standards if process == "MEX" else set())
    # Production-context sources must not become numeric geometry rule evidence.
    assert all(not mex_standards.intersection(f["evidence"]) for f in report["findings"])
