"""Independent parameterized re-audit; output preserves pre-fix findings."""
import json
import math
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from amdfm.cad_worker import convert
from amdfm.io import exact_weld
from amdfm.models import Model
from dfm.machining import MachiningProfile, review_machining
from scripts.generate_cad_examples import box, cylinder, cut, export_step
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.gp import gp_Trsf, gp_Ax1, gp_Pnt, gp_Dir, gp_Vec


def model(shape, name):
    source, target = OUT / f"{name}.step", OUT / name
    export_step(shape, source)
    convert(source, target, .01)
    meta = json.loads(target.with_suffix(".json").read_text(encoding="utf-8"))
    with np.load(target.with_suffix(".npz")) as data:
        mesh = exact_weld(data["vertices"], data["faces"])
        ids, bodies = data["face_ids"].copy(), data["body_ids"].copy()
    features = meta.pop("features")
    meta.update(source_format="step", filename=source.name, coordinate_unit="mm")
    return Model(mesh, meta, features, ids, bodies)


def transform(shape, angle, translation):
    axis = np.asarray([1., 2., 3.]) / math.sqrt(14)
    skew = np.asarray([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    rot = np.eye(3)*math.cos(angle)+(1-math.cos(angle))*np.outer(axis, axis)+math.sin(angle)*skew
    t = gp_Trsf()
    t.SetRotation(gp_Ax1(gp_Pnt(), gp_Dir(*axis)), angle)
    t.SetTranslationPart(gp_Vec(*translation))
    return BRepBuilderAPI_Transform(shape, t, True).Shape(), rot @ [0, 0, 1]


if __name__ == "__main__":
    OUT = Path(sys.argv[1]); OUT.mkdir()
    shape = cut(box(40, 30, 15), box(20, 12, 10, (10, 9, 7)))
    rows = []
    for index, (angle, shift) in enumerate([(0, 0), (.713, 0), (.713, 1000), (.819, 1000000), (.819, 100000000)]):
        name = f"transformed_{index}"
        try:
            transformed, direction = transform(shape, angle, [shift, -shift, shift])
            result = review_machining(model(transformed, name), MachiningProfile(tool_diameter_mm=12, flute_length_mm=8, reach_mm=8), direction)
            rows.append(dict(name=name, angle=angle, shift_mm=shift, result=result))
        except Exception as exc:
            rows.append(dict(name=name, angle=angle, shift_mm=shift, error=repr(exc)))
    (OUT / "summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    for row in rows:
        if "result" not in row:
            print(row); continue
        finding = next(f for f in row["result"]["findings"] if f["id"] == "cnc_rectangular_pockets")
        print(row["name"], json.dumps(finding["measurements"], ensure_ascii=False))
