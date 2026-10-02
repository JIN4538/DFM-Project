"""The batch runner must retain failed inputs and unrestricted process scopes."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_random_models.py"


def run_audit(source, output):
    return subprocess.run([sys.executable, str(SCRIPT), "--input", str(source), "--out", str(output),
        "--jobs", "1", "--section-samples", "8", "--detail-timeout", "15"],
        capture_output=True, cwd=ROOT, timeout=120)


def test_rejected_input_is_retained_and_existing_audit_is_not_overwritten(tmp_path):
    source = tmp_path / "inputs"
    source.mkdir()
    bad = source / "invalid.stp"
    bad.write_bytes(b"not a STEP exchange file")
    before = hashlib.sha256(bad.read_bytes()).hexdigest()
    output = tmp_path / "audit"
    result = run_audit(source, output)
    assert result.returncode == 0, result.stderr
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    record = summary["results"][0]
    assert record["status"] == "input_rejected"
    assert record["cases"] == []
    assert record["original_unchanged"] is True
    assert record["source_sha256"] == before
    assert (output / record["id"] / "record.html").is_file()
    snapshot = (output / "manifest.json").read_bytes()
    retry = run_audit(source, output)
    assert retry.returncode != 0
    assert (output / "manifest.json").read_bytes() == snapshot
    assert hashlib.sha256(bad.read_bytes()).hexdigest() == before


def test_four_processes_get_sections_without_build_space_rejection(tmp_path):
    source = tmp_path / "inputs"
    source.mkdir()
    example = next((ROOT / "examples" / "cad").glob("01*"))
    (source / "box.step").write_bytes(example.read_bytes())
    output = tmp_path / "audit"
    result = run_audit(source, output)
    assert result.returncode == 0, result.stderr
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    record = summary["results"][0]
    assert record["status"] == "reviewed"
    assert len(record["cases"]) == 4
    for case in record["cases"]:
        assert case["section_status"] == "complete"
        assert case["section_complete_samples"] == 8
        assert case["section_volume_midpoint_estimate_mm3"] == pytest.approx(6000)
        assert case["independent"]["failures"] == []
        assert case["independent"]["orientation_count"] == 26
        report = json.loads((output / record["id"] / case["report_json"]).read_text(encoding="utf-8"))
        assert report["profile"]["build_volume_mm"] is None
        assert all(row["build_fit"] is None for row in report["orientations"])
        if case["process"] != "MEX":
            assert case["layer_status"] == "not_applicable"
        assert report["details"]["sections"]["complete_samples"] == 8
