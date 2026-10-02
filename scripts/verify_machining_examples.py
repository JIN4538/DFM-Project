"""Save reproducible machining observations for the independently defined CAD set.

Does not label physical machining success. Never overwrites a prior result folder.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from amdfm.analysis import code_digest
from amdfm.io import load_model
from amdfm.models import json_bytes
from dfm.machining import MachiningProfile, review_machining


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    cases = json.loads((ROOT / "examples/machining/manifest.json").read_text(encoding="utf-8"))
    profile = MachiningProfile(tool_diameter_mm=4., flute_length_mm=10., reach_mm=15.,
        basis="Hypothetical test tool dimensions; not a manufacturer limit or validated machining condition")
    results = []
    revision = code_digest()
    for case in cases:
        data = (ROOT / "examples/machining" / case["file"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != case["sha256"]:
            raise ValueError("Fixture hash changed: " + case["file"])
        model = load_model(data, case["file"])
        report = review_machining(model, profile, case["expected"]["direction"])
        report["code_revision"] = revision
        (args.out / (case["id"] + ".json")).write_bytes(json_bytes(report))
        by_id = {f["id"]: f for f in report["findings"]}
        results.append(dict(id=case["id"], sha256=case["sha256"], expected=case["expected"],
            actual_cad_volume_mm3=model.metadata.get("exact_volume_mm3"),
            observed_rectangular_pockets=by_id["cnc_rectangular_pockets"]["measurements"]["count"],
            observed_internal_cylinder_faces=by_id["cnc_holes"]["measurements"]["face_count"],
            finding_statuses={key: f["status"] for key, f in by_id.items()}))
    summary = dict(scope="Geometric observations only; independent assertions are in tests_v3/test_machining_review.py",
        profile=profile.to_dict(), code_revision=revision, cases=results,
        visibility="not_run_in_this_record; separately tested with independent geometry and UI",
        physical_machining_validation=False)
    (args.out / "summary.json").write_bytes(json_bytes(summary))
    print(f"Saved {len(results)} geometry observations to {args.out}")


if __name__ == "__main__":
    main()
