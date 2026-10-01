"""Read-only audits for MFCAD/MFInstSeg samples and partition files.

No downloads or training. Exit 2 means a data-contract finding (including split
overlap); it is not a model accuracy result. OCP is optional via --ocp.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import pickle
import pickletools
import re
import sys


class PrimitiveUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        raise ValueError("Global objects are forbidden in label/split files")

    def persistent_load(self, pid):
        raise ValueError("Persistent objects are forbidden in label/split files")


def primitive_list(path: Path) -> list:
    """Allow only a pickle list of primitive integers or strings, never code."""
    raw = path.read_bytes()
    allowed = {
        "PROTO", "FRAME", "EMPTY_LIST", "MARK", "BINPUT", "LONG_BINPUT",
        "MEMOIZE", "BININT", "BININT1", "BININT2", "INT", "SHORT_BINUNICODE",
        "BINUNICODE", "UNICODE", "STRING", "BINSTRING", "SHORT_BINSTRING",
        "APPEND", "APPENDS", "STOP", "BINGET", "LONG_BINGET",
    }
    unexpected = {op.name for op, _, _ in pickletools.genops(raw)} - allowed
    if unexpected:
        raise ValueError(f"Unsupported pickle opcodes: {sorted(unexpected)}")
    value = PrimitiveUnpickler(io.BytesIO(raw)).load()
    if not isinstance(value, list) or not all(type(x) in (str, int) for x in value):
        raise ValueError("Expected a flat list of primitive integers or strings")
    return value


def fingerprint(path: Path) -> dict:
    raw = path.read_bytes()
    return {"path": str(path.resolve()), "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest()}


def audit_splits(paths: dict[str, Path], file_format: str) -> tuple[dict, list[str]]:
    values = {}
    for split, path in paths.items():
        rows = (primitive_list(path) if file_format == "pickle"
                else path.read_text(encoding="utf-8-sig").splitlines())
        if not rows or not all(isinstance(x, str) and x.strip() == x and x for x in rows):
            raise ValueError(f"Split {split} contains an empty/non-string/untrimmed ID")
        values[split] = rows
    counts = {s: {"rows": len(v), "unique": len(set(v)),
                  "duplicate_rows": len(v) - len(set(v))} for s, v in values.items()}
    overlaps = {f"{a}/{b}": sorted(set(values[a]) & set(values[b]))
                for a, b in (("train", "val"), ("train", "test"), ("val", "test"))}
    findings = [f"{s}: {c['duplicate_rows']} duplicate split rows"
                for s, c in counts.items() if c["duplicate_rows"]]
    findings += [f"{pair}: {len(ids)} shared IDs" for pair, ids in overlaps.items() if ids]
    return {"counts": counts, "overlap_ids": overlaps,
            "total_rows": sum(len(v) for v in values.values()),
            "unique_union": len(set().union(*(set(v) for v in values.values())))}, findings


def load_labels(path: Path, kind: str):
    if kind == "mfcad":
        labels = primitive_list(path)
        if not all(type(x) is int and 0 <= x < 16 for x in labels):
            raise ValueError("MFCAD semantic labels must be integers in 0..15")
        return labels
    pairs = json.loads(path.read_text(encoding="utf-8-sig"))
    if len(pairs) != 1 or len(pairs[0]) != 2:
        raise ValueError("Expected one [sample_id, labels] MFInstSeg record")
    labels = pairs[0][1]
    if set(labels) != {"seg", "inst", "bottom"}:
        raise ValueError("Expected MFInstSeg seg/inst/bottom fields")
    return labels


def audit_sample(step: Path, labels, kind: str) -> tuple[dict, list[str]]:
    text = step.read_text(encoding="utf-8-sig")
    faces = re.findall(r"#(\d+)\s*=\s*ADVANCED_FACE\s*\(\s*'([^']*)'", text)
    findings = []
    if not faces:
        findings.append("No ADVANCED_FACE entities found")
    if kind == "mfcad":
        ids = [int(name) for _, name in faces]
        complete = sorted(ids) == list(range(len(labels)))
        if not complete:
            findings.append("STEP face names do not form the label index permutation")
        return {"step_face_count": len(faces), "label_count": len(labels),
                "face_name_order": ids, "names_are_index_permutation": complete,
                "file_order_equals_name_order": ids == list(range(len(labels))),
                "mapping": "label[STEP representation item Name()], never raw file ordinal"}, findings
    seg, inst, bottom = labels["seg"], labels["inst"], labels["bottom"]
    n = len(seg)
    complete = set(seg) == {str(i) for i in range(n)}
    bottom_complete = set(bottom) == set(seg)
    square = len(inst) == n and all(isinstance(row, list) and len(row) == n for row in inst)
    symmetric = square and all(inst[i][j] == inst[j][i] for i in range(n) for j in range(n))
    checks = {
        "face_count_matches": len(faces) == n,
        "seg_keys_complete": complete, "bottom_keys_complete": bottom_complete,
        "semantic_range_valid": all(type(v) is int and 0 <= v < 25 for v in seg.values()),
        "bottom_binary": all(type(v) is int and v in (0, 1) for v in bottom.values()),
        "instance_square": square, "instance_symmetric": symmetric,
        "instance_binary": square and all(v in (0, 1) for row in inst for v in row),
    }
    findings += [f"MFInstSeg {key} failed" for key, passed in checks.items() if not passed]
    return {"step_face_count": len(faces), "label_count": n, "checks": checks,
            "semantic_counts": dict(Counter(seg.values())),
            "bottom_counts": dict(Counter(bottom.values())),
            "mapping": "JSON face ordinal must match the upstream B-Rep traversal; count equality alone is insufficient"}, findings


def audit_ocp(step: Path, labels, kind: str) -> tuple[dict, list[str]]:
    import OCP
    from OCP.STEPControl import STEPControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
    from OCP.TopoDS import TopoDS
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepBndLib import BRepBndLib
    from OCP.Bnd import Bnd_Box
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    reader = STEPControl_Reader()
    if reader.ReadFile(str(step)) != IFSelect_RetDone:
        raise ValueError("OCP could not read STEP")
    reader.TransferRoots()
    shape = reader.OneShape()
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    faces = []
    while exp.More():
        face = TopoDS.Face_s(exp.Current())
        if not any(face.IsSame(previous) for previous in faces):
            faces.append(face)
        exp.Next()
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, box)
    bounds = box.Get()
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    solids = 0
    while exp.More():
        solids += 1
        exp.Next()
    rows = []
    for index, face in enumerate(faces):
        item = reader.WS().TransferReader().EntityFromShapeResult(face, 1)
        name = item.Name().ToCString() if item is not None else None
        surface = BRepAdaptor_Surface(face, True)
        label = labels[int(name)] if kind == "mfcad" else labels["seg"][str(index)]
        rows.append({"index": index, "step_name": name, "label": label,
                     "surface": str(surface.GetType()).split(".")[-1]})
    valid = BRepCheck_Analyzer(shape).IsValid()
    findings = [] if valid else ["OCP BRepCheck reports an invalid shape"]
    expected_faces = len(labels) if kind == "mfcad" else len(labels["seg"])
    if len(faces) != expected_faces:
        findings.append("OCP face count differs from label count")
    if solids != 1:
        findings.append(f"Expected a single solid, found {solids}")
    return {"ocp_version": getattr(OCP, "__version__", "unknown"), "valid": valid,
            "solid_count": solids, "face_count": len(faces), "bounds_mm": bounds,
            "dimensions_mm": [bounds[i + 3] - bounds[i] for i in range(3)],
            "volume_mm3": props.Mass(), "face_rows": rows,
            "ordinal_limit": "MFInstSeg upstream pythonocc traversal was not run; geometric agreement here is a sample check"}, findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, choices=("mfcad", "mfinstseg"))
    parser.add_argument("--step", type=Path)
    parser.add_argument("--labels", type=Path)
    for split in ("train", "val", "test"):
        parser.add_argument(f"--split-{split}", type=Path)
    parser.add_argument("--split-format", choices=("text", "pickle"), default="text")
    parser.add_argument("--ocp", action="store_true")
    parser.add_argument("--output", type=Path, help="New JSON report; refuses to overwrite")
    args = parser.parse_args()
    paths = {s: getattr(args, f"split_{s}") for s in ("train", "val", "test")}
    if bool(args.step) != bool(args.labels) or (any(paths.values()) and not all(paths.values())):
        parser.error("Provide both --step/--labels and/or all three split files")
    if not args.step and not all(paths.values()):
        parser.error("A sample or complete split file set is required")
    if args.ocp and not args.step:
        parser.error("--ocp requires a sample")
    if args.output and args.output.exists():
        parser.error("Output exists; choose a new report path to preserve evidence")
    result = {"kind": args.kind, "python": sys.version,
              "scope": "Selected sample and/or ID partitions only; no training or whole-corpus certification",
              "inputs": [], "findings": []}
    try:
        inputs = [p for p in [args.step, args.labels, *paths.values()] if p]
        result["inputs"] = [fingerprint(path) for path in inputs]
        if args.step:
            labels = load_labels(args.labels, args.kind)
            result["sample"], findings = audit_sample(args.step, labels, args.kind)
            result["findings"].extend(findings)
            if args.ocp and not findings:
                result["geometry"], findings = audit_ocp(args.step, labels, args.kind)
                result["findings"].extend(findings)
        if all(paths.values()):
            result["splits"], findings = audit_splits(paths, args.split_format)
            result["findings"].extend(findings)
    except Exception as exc:
        result["findings"].append(f"Audit incomplete: {type(exc).__name__}: {exc}")
    result["status"] = "findings" if result["findings"] else "checked_inputs_passed"
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(rendered + "\n")
    print(rendered)
    return 2 if result["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
