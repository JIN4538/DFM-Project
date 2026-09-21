"""Original STEP fixtures for bounded machining geometry verification.

Construction dimensions define the expected values independently of the review
engine. These are geometric verification examples, not machining experiments.
Run into a new directory; existing reference artifacts are never overwritten.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.generate_cad_examples import box, cylinder, cut, fuse, compound, export_step


def rounded_rectangle_cutter(width, length, height, radius, origin):
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopoDS import TopoDS
    shape = box(width, length, height, origin)
    fillet = BRepFilletAPI_MakeFillet(shape)
    explorer = TopExp_Explorer(shape, TopAbs_EDGE)
    selected = []
    while explorer.More():
        edge = TopoDS.Edge_s(explorer.Current())
        curve = BRepAdaptor_Curve(edge)
        a = np.asarray(curve.Value(curve.FirstParameter()).Coord())
        b = np.asarray(curve.Value(curve.LastParameter()).Coord())
        if np.linalg.norm(a[:2] - b[:2]) < 1e-10 and math.isclose(abs(a[2] - b[2]), height):
            if not any(edge.IsSame(previous) for previous in selected):
                fillet.Add(radius, edge)
                selected.append(edge)
        explorer.Next()
    if len(selected) != 4:
        raise RuntimeError("Rounded rectangle requires four vertical cutter edges.")
    fillet.Build()
    if not fillet.IsDone():
        raise RuntimeError("Rounded cutter fillet failed.")
    return fillet.Shape()


def _rotated_pocket(shape):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf, gp_Ax1, gp_Pnt, gp_Dir, gp_Vec
    transform = gp_Trsf()
    transform.SetRotation(gp_Ax1(gp_Pnt(), gp_Dir(0, 1, 0)), math.pi / 2)
    transform.SetTranslationPart(gp_Vec(60, -10, 5))
    return BRepBuilderAPI_Transform(shape, transform, True).Shape()


def generate(destination):
    destination = Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError("기준형상을 보존합니다. 비어 있는 새 출력 폴더를 지정하세요.")
    destination.mkdir(parents=True, exist_ok=True)
    pocket = cut(box(40, 30, 15), box(20, 12, 10, (10, 9, 7)))
    common = dict(direction=[0, 0, 1], solid_count=1, rectangular_pocket_count=0,
                  internal_full_cylinder_face_count=0, internal_partial_cylinder_face_count=0)
    rectangle = dict(rectangular_pocket_count=1, pocket_width_mm=12, pocket_length_mm=20,
                     pocket_wall_height_mm=8, pocket_floor_center_mm=[20, 15, 7],
                     pocket_floor_area_mm2=240)
    rounded_area = 20 * 12 - (4 - math.pi) * 3**2
    cases = [
        ("01_rectangular_pocket", "직사각 포켓 · 20×12 / 깊이 8 mm", pocket,
         dict(volume_mm3=18000 - 20 * 12 * 8, **rectangle)),
        ("02_narrow_deep_pocket", "좁고 깊은 포켓 · 폭 3 / 깊이 20 mm",
         cut(box(40, 30, 25), box(20, 3, 22, (10, 13.5, 5))),
         dict(volume_mm3=30000 - 20 * 3 * 20, rectangular_pocket_count=1,
              pocket_width_mm=3, pocket_length_mm=20, pocket_wall_height_mm=20,
              pocket_floor_center_mm=[20, 15, 5], pocket_floor_area_mm2=60)),
        ("03_rounded_pocket", "둥근 포켓 · 모서리 R3 / 깊이 8 mm",
         cut(box(40, 30, 15), rounded_rectangle_cutter(20, 12, 10, 3, (10, 9, 7))),
         dict(volume_mm3=18000 - rounded_area * 8, internal_partial_cylinder_face_count=4,
              internal_partial_cylinder_radius_mm=3, internal_partial_cylinder_span_rad=math.pi / 2,
              floor_area_mm2=rounded_area, floor_center_mm=[20, 15, 7],
              exclusion="Curved floor boundary is outside the rectangular-floor recognizer.")),
        ("04_vertical_hole", "수직 원통 구멍 · Ø6 / 원통면 길이 15 mm",
         cut(box(40, 30, 15), cylinder(3, 17, (20, 15, -1))),
         dict(volume_mm3=18000 - math.pi * 3**2 * 15, internal_full_cylinder_face_count=1,
              cylinder_diameter_mm=6, cylindrical_length_mm=15, cylinder_axis=[0, 0, 1])),
        ("05_side_hole", "측면 원통 구멍 · Ø4 / 원통면 길이 40 mm",
         cut(box(40, 30, 15), cylinder(2, 42, (-1, 15, 7.5), (1, 0, 0))),
         dict(volume_mm3=18000 - math.pi * 2**2 * 40, internal_full_cylinder_face_count=1,
              cylinder_diameter_mm=4, cylindrical_length_mm=40, cylinder_axis=[1, 0, 0])),
        ("06_boss", "돌출 보스 · 포켓 오인식 반례",
         fuse(box(40, 30, 5), box(20, 12, 10, (10, 9, 5))),
         dict(volume_mm3=8400, exclusion="Convex boss walls face away from the top-face center.")),
        ("07_sealed_cavity", "밀폐 공동 · 열린 포켓 오인식 반례",
         cut(box(40, 30, 15), box(20, 12, 8, (10, 9, 3))),
         dict(volume_mm3=16080, cavity_shell_count=1,
              exclusion="Enclosed cavity walls meet an inward ceiling, not an outward open rim.")),
        ("08_open_channel", "양끝 열린 채널 · 사방 벽 포켓의 범위 밖",
         cut(box(40, 30, 15), box(42, 12, 10, (-1, 9, 7))),
         dict(volume_mm3=14160, exclusion="Channel floor is not bounded by four inward walls.")),
        ("09_island_pocket", "중앙 섬이 있는 포켓 · 복수 경계 반례",
         fuse(pocket, box(4, 4, 8, (18, 13, 7))),
         dict(volume_mm3=16208, exclusion="Inner floor wire must not be discarded.")),
        ("10_plain_block", "단순 블록 · 포켓·구멍 없음", box(40, 30, 15),
         dict(volume_mm3=18000, exclusion="Exterior planes are not pockets.")),
        ("11_rotated_pocket", "+X 방향으로 열린 포켓 · 회전·이동 검증", _rotated_pocket(pocket),
         dict(volume_mm3=16080, **{**rectangle, "direction": [1, 0, 0],
                                  "pocket_floor_center_mm": [67, 5, -15]})),
        ("12_two_solids", "분리된 2개 솔리드 · 부품 선택 필요",
         compound([pocket, box(5, 6, 7, (60, 0, 0))]),
         dict(solid_count=2, constituent_volume_sum_mm3=16290,
              raw_rectangular_pocket_count=1,
              exclusion="Review must require a single selected solid before interpreting CAD machining features.")),
    ]
    manifest = []
    for identifier, title, shape, expected in cases:
        path = destination / f"{identifier}.step"
        export_step(shape, path)
        manifest.append(dict(id=identifier, label=title, title=title, file=path.name,
                             source="Original OCCT parametric construction; geometric validation only",
                             sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                             expected={**common, **expected}))
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (destination / "README.md").write_text(
        "# 절삭 기하 검토 기준형상\n\n"
        "직접 작성한 OCCT 매개변수 형상입니다. `manifest.json`의 기대값은 생성 치수와 독립 수식이며, 실제 가공 실험·품질 보증 자료가 아닙니다.\n\n"
        "재생성: `.venv/Scripts/python.exe scripts/generate_machining_examples.py <새 폴더>`\n\n"
        "기존 형상과 SHA 기록을 보존하기 위해 비어 있는 폴더에만 생성합니다. STEP 헤더의 생성 시간이 달라지므로 재생성 파일의 바이트 SHA까지 동일하다는 뜻은 아닙니다.\n\n"
        "- 직사각 포켓 바닥 검증: 01, 02, 11. 11의 검토 방향은 +X입니다.\n"
        "- 반경 비교: 03의 부분 원통면 R3. 곡선 포켓 전체를 인식했다는 뜻은 아닙니다.\n"
        "- 원통면 구간: 04, 05. 길이는 해당 원통면의 축 구간이며 전체 드릴 깊이가 아닙니다.\n"
        "- 오인식·미지원 반례: 보스, 밀폐 공동, 열린 채널, 섬이 있는 포켓, 단순 블록.\n"
        "- 다중 솔리드: 12. 부품 선택 전에는 절삭 특징 검토를 보류합니다.\n",
        encoding="utf-8")
    return manifest


if __name__ == "__main__":
    generate(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "examples/machining")
