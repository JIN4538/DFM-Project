"""Read-only application probes; all generated data stays in this fresh directory."""
from pathlib import Path
import hashlib
import io
import json
import subprocess
import sys
import time
import zipfile

import numpy as np
import trimesh

BASE = Path(__file__).resolve().parent
REPO = BASE.parents[2] / "DFM-Project"
sys.path.insert(0, str(REPO))
from amdfm.cross_sections import inspect_cross_sections
from amdfm.detail import attach_detail, run_detail
from amdfm.io import load_model
from amdfm.analysis import review
from amdfm.processes import run_bounded
from amdfm.profiles import Profile
from amdfm.three_mf import CORE, MODEL_REL


results = {"reviewed_files_sha256": {
    name: hashlib.sha256((REPO / "amdfm" / name).read_bytes()).hexdigest()
    for name in ("three_mf.py", "cross_sections.py", "processes.py", "detail.py")}, "probes": []}


def matrix_text(matrix):
    return " ".join(str(float(v)) for v in matrix[:3, :].T.ravel())


def transform_probe():
    mesh = trimesh.creation.box(extents=[2, 3, 4])
    # Independent fixture: nested reflections plus shear, anisotropic scale,
    # translations in inches. Expected points use explicit column algebra.
    inner = np.array([[-2, .25, 0, 5], [0, 3, .5, -7], [0, 0, 4, 11], [0, 0, 0, 1.]])
    outer = np.array([[0, -1, 0, 13], [-1, 0, 0, -17], [0, 0, 1, 19], [0, 0, 0, 1.]])
    final = np.array([[1, 0, .1, 23], [0, 1, 0, 29], [0, 0, 1, -31], [0, 0, 0, 1.]])
    vs = "".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in mesh.vertices)
    ts = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in mesh.faces)
    xml = (f'<model xmlns="{CORE}" unit="inch"><resources>'
           f'<object id="1"><mesh><vertices>{vs}</vertices><triangles>{ts}</triangles></mesh></object>'
           f'<object id="2"><components><component objectid="1" transform="{matrix_text(inner)}"/></components></object>'
           f'<object id="3"><components><component objectid="2" transform="{matrix_text(outer)}"/></components></object>'
           f'</resources><build><item objectid="3" transform="{matrix_text(final)}"/></build></model>')
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as package:
        package.writestr("_rels/.rels", f'<Relationships><Relationship Type="{MODEL_REL}" Target="/3D/model.model"/></Relationships>')
        package.writestr("3D/model.model", xml)
    (BASE / "nested_shear_inches.3mf").write_bytes(data.getvalue())
    actual = load_model(data.getvalue(), "nested_shear_inches.3mf")
    expected = []
    for vertex in mesh.vertices:
        p = np.r_[vertex, 1.]
        expected.append((final @ (outer @ (inner @ p)))[:3] * 25.4)
    expected = np.asarray(expected)
    ordered = lambda points: points[np.lexsort(points.T[::-1])]
    error = float(np.max(np.abs(ordered(actual.mesh.vertices) - ordered(expected))))
    volume_expected = 24 * 24 * 25.4**3
    return dict(name="nested_affine_and_inch_conversion", coordinate_error_mm=error,
                actual_volume_mm3=float(actual.mesh.volume), expected_volume_mm3=volume_expected,
                passed=error < 1e-9 and np.isclose(actual.mesh.volume, volume_expected, rtol=1e-11))


def section_probe():
    # Square truncated pyramid: lower side 10, upper side 2, height 8.
    vertices = np.array([[-5,-5,0],[5,-5,0],[5,5,0],[-5,5,0],
                         [-1,-1,8],[1,-1,8],[1,1,8],[-1,1,8]], dtype=float)
    mesh = trimesh.convex.convex_hull(vertices)
    section = inspect_cross_sections(mesh, 16)
    area_error = max(abs(r["area_mm2"] - (10-r["z_mm"])**2) for r in section["rows"])
    perimeter_error = max(abs(r["perimeter_mm"] - 4*(10-r["z_mm"])) for r in section["rows"])
    expected_midpoint = sum((10-(i+.5)*.5)**2*.5 for i in range(16))
    # Budget abort after two slices must retain observed maxima and null volume.
    partial = inspect_cross_sections(mesh, 16, max_total_segments=20)
    return dict(name="tapered_sections_and_partial_null", area_error_mm2=area_error,
                perimeter_error_mm=perimeter_error, full_status=section["status"],
                midpoint_error_mm3=abs(section["volume_midpoint_estimate_mm3"]-expected_midpoint),
                partial_status=partial["status"], complete_samples=partial["complete_samples"],
                partial_volume=partial["volume_midpoint_estimate_mm3"],
                passed=area_error<1e-8 and perimeter_error<1e-8 and section["status"]=="complete"
                    and partial["status"]=="partial" and partial["volume_midpoint_estimate_mm3"] is None)


def detail_probe():
    model = load_model(trimesh.creation.box(extents=[10, 5, 4]).export(file_type="stl"),
                       "detail.stl", dimensions_confirmed=True)
    profile = Profile(process="VPP")
    original = review(model, profile, compare=False)
    good = run_detail(model, profile, mode="sections", sample_count=8)
    measured = attach_detail(original, good)
    timed_out = run_detail(model, profile, mode="sections", sample_count=8, timeout_s=.001)
    reset = attach_detail(measured, timed_out)
    finding = next(f for f in reset["findings"] if f["id"]=="sections")
    return dict(name="section_timeout_clears_stale_measurement", initial_status=good["status"],
                timeout_status=timed_out["status"], finding_status=finding["status"],
                old_maximum_present="sampled_max_area_mm2" in finding["measurements"],
                passed=good["status"]=="complete" and timed_out["status"]=="unknown"
                    and finding["status"]=="unknown" and "sampled_max_area_mm2" not in finding["measurements"])


def process_probe():
    marker = BASE / "orphan-after-timeout.txt"
    child = ("import time; from pathlib import Path; time.sleep(4); "
             "Path(" + repr(str(marker)) + ").write_text('child was not stopped')")
    # Unlike the existing regression, the direct parent exits immediately.
    # Its child keeps the inherited stdout pipe and remains alive.
    worker = "import subprocess,sys; subprocess.Popen([sys.executable,'-c',"+repr(child)+"]); print('parent exited')"
    started = time.perf_counter()
    outcome = None
    try:
        run_bounded([sys.executable, "-c", worker], cwd=BASE, timeout=.75)
        outcome = "returned"
    except subprocess.TimeoutExpired:
        outcome = "TimeoutExpired"
    elapsed = time.perf_counter()-started
    return dict(name="timeout_after_direct_parent_exits", requested_timeout_s=.75,
                elapsed_s=elapsed, outcome=outcome, child_wrote_after_timeout=marker.exists(),
                passed=outcome=="TimeoutExpired" and elapsed<2.5 and not marker.exists())


for probe in (transform_probe, section_probe, detail_probe, process_probe):
    try:
        result = probe()
    except Exception as exc:
        result = dict(name=probe.__name__, error=repr(exc), passed=False)
    result = {key: value.item() if isinstance(value, np.generic) else value for key, value in result.items()}
    results["probes"].append(result)
    print(json.dumps(result, ensure_ascii=True), flush=True)
    (BASE / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
