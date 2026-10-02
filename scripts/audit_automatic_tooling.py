"""Reproducible missing-input integration audit on the local STEP corpus.

This checks contracts and remeasures the proposed dimensions with the existing
engine; it is not an independent feature-recognition accuracy benchmark.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from audit_neural_cad import cases
from amdfm.analysis import code_digest
from amdfm.io import load_model
from dfm.machining import MachiningProfile, review_machining
from dfm.tool_recommendation import TOOL_FIELDS, review_with_tool_recommendation
from dfm.conclusion import summarize_conclusion


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--only", action="append", help="Audit only this manifest case ID; repeatable")
    parser.add_argument("--step-timeout", type=float, default=75.)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    before = code_digest()
    started = time.perf_counter()
    rows = []
    profiles = [MachiningProfile(), MachiningProfile(tool_diameter_mm=4.),
                MachiningProfile(tool_diameter_mm=4., flute_length_mm=8., reach_mm=10.)]
    with (args.out / "records.jsonl").open("x", encoding="utf-8") as journal:
        for case in cases("cnc"):
            if args.only and case["id"] not in args.only:
                continue
            raw = case["path"].read_bytes()
            assert hashlib.sha256(raw).hexdigest() == case["sha256"]
            try:
                model = load_model(raw, case["path"].name, timeout_s=args.step_timeout)
            except Exception as exc:
                row = dict(path=case["path"].relative_to(ROOT).as_posix(), sha256=case["sha256"],
                           status="load_failed", error=f"{type(exc).__name__}: {exc}")
                rows.append(row)
                journal.write(json.dumps(row, ensure_ascii=False) + "\n")
                journal.flush()
                continue
            for axis in [(0, 0, 1), (1, 0, 0), (0, 1, 0)]:
                for requested in profiles:
                    original = deepcopy(requested.to_dict())
                    row = dict(path=case["path"].relative_to(ROOT).as_posix(), sha256=case["sha256"],
                               direction=axis, requested={key: original[key] for key in TOOL_FIELDS})
                    try:
                        report = review_with_tool_recommendation(model, requested, axis, visibility=False)
                        proposal = report["tool_recommendation"]
                        assert requested.to_dict() == original
                        assert proposal["original_profile"] == original
                        for field in TOOL_FIELDS:
                            if original[field] is not None:
                                assert report["profile"][field] == original[field], field
                        exact = review_machining(model, MachiningProfile(**report["profile"]), axis, visibility=False)
                        actual = {x["id"]: x for x in report["findings"]}
                        for item in exact["findings"]:
                            assert actual[item["id"]] == item, item["id"]
                        if actual["cnc_input"]["status"] != "observed":
                            assert not proposal["automatic_fields"]
                        summary = summarize_conclusion(report, plan_result={})
                        if proposal.get("unresolved") and proposal["automatic_fields"]:
                            assert any(x["id"] == "cnc_tool_recommendation" for x in summary["pending"] + summary["partial"] + summary["issues"])
                        row.update(status="passed", proposal_status=proposal["status"],
                                   values=proposal["values"], automatic_fields=proposal["automatic_fields"],
                                   conflicts=proposal["conflicts"], unresolved=proposal["unresolved"],
                                   conclusion=summary["title"])
                    except Exception as exc:
                        row.update(status="failed", error=f"{type(exc).__name__}: {exc}")
                    rows.append(row)
                    journal.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
                    journal.flush()
            print(f"{case['id']}: {len(rows)} conditions", flush=True)
    after = code_digest()
    summary = dict(files=len({x["path"] for x in rows}), conditions=len(rows),
                   states=dict(Counter(x["status"] for x in rows)),
                   auto_proposal_conditions=sum(bool(x.get("automatic_fields")) for x in rows),
                   automatic_field_count=sum(len(x.get("automatic_fields", [])) for x in rows),
                   proposal_states=dict(Counter(x.get("proposal_status", "error") for x in rows)),
                   source_sha256=before, source_unchanged=before == after,
                   elapsed_seconds=time.perf_counter() - started,
                   failures=[x for x in rows if x["status"] != "passed"])
    (args.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return int(bool(summary["failures"]) or not summary["source_unchanged"])


if __name__ == "__main__":
    raise SystemExit(main())
