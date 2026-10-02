"""3D 모델 로더 (v2)

v1 대비 주요 변경
-----------------
1. STL에는 단위 정보가 없다. 단위(mm/cm/inch)를 명시적으로 받아 스케일한다.
   v1은 인치 STL을 그대로 mm로 읽어 모든 임계값이 25.4배 어긋났다.
2. 로드 직후 메시 유효성을 진단해서 경고 목록으로 돌려준다.
   is_watertight 는 '모든 엣지가 정확히 2면과 공유'만 보므로 자기교차를
   잡지 못한다. 분리 바디 수(body_count)를 함께 봐야 한다.
3. 샘플 모델을 trimesh.util.concatenate 가 아니라 boolean union 으로 만든다.
   concatenate 는 삼각형 더미를 합칠 뿐이라 내부 면이 남고 겹친 부피가
   중복 계산된다. v1의 Bad 모델은 부피가 실제의 약 2배로 잡혔다.
4. 죽은 코드(_add_simple_fillet, 미사용 boss)를 제거했다.
"""

import os
from typing import List

import numpy as np
import trimesh
from src.core.mesh_diagnostics import inspect_mesh

UNIT_SCALE = {'mm': 1.0, 'cm': 10.0, 'm': 1000.0, 'inch': 25.4}


def load_model(filepath: str, unit: str = 'mm', fix_normals: bool = True) -> dict:
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {filepath}")
    if unit not in UNIT_SCALE:
        raise ValueError(f"지원하지 않는 단위: {unit} (가능: {list(UNIT_SCALE)})")

    mesh = trimesh.load(filepath, force='mesh')
    if UNIT_SCALE[unit] != 1.0:
        mesh.apply_scale(UNIT_SCALE[unit])
    if fix_normals:
        # Multi-shell cavities need negative winding. fix_normals(multibody=True)
        # would turn every shell into positive material and erase cavities.
        trimesh.repair.fix_winding(mesh)
        if mesh.body_count == 1:
            mesh.fix_normals(multibody=False)

    if len(mesh.faces) == 0 or not np.isfinite(mesh.vertices).all():
        raise ValueError("비어 있거나 비유한 좌표를 포함한 메시입니다.")
    meta = extract_metadata(mesh)
    meta.update(filepath=filepath, filename=os.path.basename(filepath), unit=unit)
    return {'mesh': mesh, 'metadata': meta, 'warnings': diagnose(mesh)}


def extract_metadata(mesh: trimesh.Trimesh) -> dict:
    b = mesh.bounds
    return {
        'bounding_box': {'min': b[0].tolist(), 'max': b[1].tolist(),
                         'size': mesh.extents.tolist()},
        'volume': float(mesh.volume),
        'surface_area': float(mesh.area),
        'center_mass': mesh.center_mass.tolist(),
        'vertex_count': int(len(mesh.vertices)),
        'face_count': int(len(mesh.faces)),
        'is_watertight': bool(mesh.is_watertight),
        'is_winding_consistent': bool(mesh.is_winding_consistent),
        'body_count': int(getattr(mesh, 'body_count', 1)),
    }


def diagnose(mesh: trimesh.Trimesh) -> List[str]:
    report = inspect_mesh(mesh)
    w = list(report['issues'])
    if not report['geometry_available']:
        return w
    if getattr(mesh, 'body_count', 1) > 1:
        w.append(f"분리된 바디 {mesh.body_count}개. 겹쳐 있으면 부피가 중복 계산됩니다.")
    if max(mesh.extents) > 2000:
        w.append(f"부품 최대 치수가 {max(mesh.extents):.0f}mm 입니다. "
                 f"단위 설정(mm/inch)이 맞는지 확인하세요.")
    if max(mesh.extents) < 1.0:
        w.append(f"부품 최대 치수가 {max(mesh.extents):.3f}mm 입니다. 단위 설정을 확인하세요.")
    return w


def _union(parts: List[trimesh.Trimesh]) -> trimesh.Trimesh:
    """겹친 형상을 단일 솔리드로 합친다. 실패한 형상을 샘플로 반환하지 않는다."""
    try:
        m = trimesh.boolean.union(parts, engine='manifold')
        if m is None or len(m.faces) == 0 or not m.is_watertight or m.volume <= 0:
            raise ValueError('유효한 합집합 솔리드가 생성되지 않았습니다.')
        m.merge_vertices()
        m.metadata['boolean'] = True
        return m
    except Exception as exc:
        raise RuntimeError('샘플 합집합 생성 실패: manifold3d 설치와 실행 환경을 확인하세요. '
                           '겹친 메시를 정상 샘플로 대체하지 않습니다.') from exc


def generate_sample_models() -> dict:
    """검증용 샘플 3종. 전부 단일 솔리드(watertight)."""
    models = {}

    # Good: 단순 직육면체. 오버행이 물리적으로 존재할 수 없는 기준 형상
    models['good'] = {
        'mesh': trimesh.creation.box(extents=[40, 30, 20]),
        'name': 'Good (직육면체 40x30x20)',
        'description': '오버행 없음 · 두꺼운 벽 · 낮은 종횡비. 엔진의 기준점(sanity check).',
    }

    # Bad: 얇은 벽 + 큰 수평 오버행 + 높은 기둥
    thin = trimesh.creation.box(extents=[60, 40, 1])
    plate = trimesh.creation.box(extents=[80, 60, 2]); plate.apply_translation([0, 0, 6])
    post = trimesh.creation.box(extents=[6, 6, 12]);   post.apply_translation([0, 0, 0.5])
    pillar = trimesh.creation.cylinder(radius=2, height=60, sections=48)
    pillar.apply_translation([30, 20, 37])
    models['bad'] = {
        'mesh': _union([thin, plate, post, pillar]),
        'name': 'Bad (얇은 벽 + 오버행 + 높은 기둥)',
        'description': '1mm 벽 · 기둥 위에 뜬 수평 플랫폼 · 가는 기둥. 제조성 불량.',
    }

    # Moderate: L형 브래킷 + 보스
    # 수평 플랜지를 위쪽에 둔다. +Z로 세우면 플랜지 아랫면 전체가 오버행이고,
    # -Z로 뒤집으면 플랜지가 플레이트에 닿아 오버행이 사라진다.
    # v1은 방향 후보에 -Z가 없어서 이 개선을 찾을 수 없었다.
    vert = trimesh.creation.box(extents=[60, 5, 40])
    horiz = trimesh.creation.box(extents=[60, 40, 5]); horiz.apply_translation([0, 17.5, 17.5])
    boss = trimesh.creation.cylinder(radius=8, height=12, sections=48)
    boss.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    boss.apply_translation([0, 0, -8])
    models['moderate'] = {
        'mesh': _union([vert, horiz, boss]),
        'name': 'Moderate (L-브래킷 + 보스)',
        'description': '벽두께 양호 · 위쪽 수평 플랜지에 오버행 존재. 방향 최적화 효과 확인용.',
    }
    return models


def save_sample_stl(output_dir: str = "data") -> List[str]:
    os.makedirs(output_dir, exist_ok=True)
    paths = []
    for key, data in generate_sample_models().items():
        p = os.path.join(output_dir, f"sample_{key}.stl")
        data['mesh'].export(p)
        paths.append(p)
    return paths


if __name__ == "__main__":
    for key, d in generate_sample_models().items():
        m = d['mesh']
        print(f"{key:9s} watertight={str(m.is_watertight):5s} bodies={m.body_count} "
              f"faces={len(m.faces):5d} volume={m.volume:9.1f} area={m.area:9.1f}")
        for w in diagnose(m):
            print(f"           경고: {w}")
