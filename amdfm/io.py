"""Immutable inputs. STEP runs in a separate, bounded CAD process."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np
import trimesh

from .models import Model
from .processes import run_bounded

MAX_BYTES = 80 * 1024 * 1024
MAX_FACES = 600_000
UNITS = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "inch": 25.4}


def exact_weld(vertices, faces):
    """Share identical coordinate triples only. No repair or tolerance merge."""
    vertices, inverse = np.unique(np.asarray(vertices, dtype=float), axis=0, return_inverse=True)
    return trimesh.Trimesh(vertices=vertices, faces=inverse[np.asarray(faces)], process=False)


def load_model(data: bytes, filename: str, *, unit="mm", dimensions_confirmed=False,
               target_longest_mm=None, deflection_mm=0.05, timeout_s=75) -> Model:
    if not data or len(data) > MAX_BYTES:
        raise ValueError("파일이 비어 있거나 80 MiB 입력 한도를 초과했습니다.")
    suffix = Path(filename).suffix.lower()
    meta = dict(filename=Path(filename).name, source_sha256=hashlib.sha256(data).hexdigest(),
                source_bytes=len(data), source_format=suffix.lstrip("."), coordinate_unit="mm")
    if suffix in (".step", ".stp"):
        if not np.isfinite(deflection_mm) or not .001 <= deflection_mm <= 1:
            raise ValueError("CAD 메시 변환의 목표 편차는 0.001–1 mm 범위여야 합니다.")
        with tempfile.TemporaryDirectory(prefix="amdfm-step-") as tmp:
            source = Path(tmp) / "input.step"
            source.write_bytes(data)
            dest = Path(tmp) / "result"
            try:
                run = run_bounded([sys.executable, "-m", "amdfm.cad_worker", str(source),
                    str(dest), str(deflection_mm)], timeout=timeout_s,
                    cwd=Path(__file__).resolve().parents[1])
            except subprocess.TimeoutExpired as exc:
                raise ValueError(f"STEP 처리가 {timeout_s:g}초 한도를 초과했습니다. 단일 부품으로 분리하거나 모델을 단순화하세요.") from exc
            except OSError as exc:
                raise ValueError(f"STEP 계산 프로세스를 시작하거나 격리하지 못했습니다: {exc}") from exc
            info_path = dest.with_suffix(".json")
            if not info_path.exists():
                raise ValueError("CAD 변환 프로세스가 완료되지 않았습니다. 설치 상태와 STEP 파일을 확인하세요.")
            info = json.loads(info_path.read_text(encoding="utf-8"))
            if run.returncode or "error" in info:
                raise ValueError(f"STEP 입력 검토: {info.get('error', 'CAD 변환 실패')}")
            info["cad_translation_messages"]=(run.stdout+run.stderr).decode("utf-8",errors="replace")[-8192:]
            with np.load(dest.with_suffix(".npz"), allow_pickle=False) as values:
                mesh = exact_weld(values["vertices"], values["faces"])
                face_ids, body_ids = values["face_ids"].copy(), values["body_ids"].copy()
            # OCCT can emit exactly collapsed triangles at analytic surface poles.
            # Removing zero-area tessellation cells changes no CAD material or
            # nonzero triangle; keep source-face mapping synchronized. STL input
            # is deliberately not cleaned by this CAD-only operation.
            keep = np.asarray(mesh.area_faces) > 0
            removed = int((~keep).sum())
            if removed:
                mesh.update_faces(keep)
                mesh.remove_unreferenced_vertices()
                face_ids, body_ids = face_ids[keep], body_ids[keep]
            info["tessellation"]["exact_zero_area_cells_removed"] = removed
            info["tessellation"]["analysis_triangle_count"] = len(mesh.faces)
            features = info.pop("features")
            meta.update(info, unit_status="declared_in_step", dimensions_confirmed=True,
                        unit_note="STEP 선언 단위를 OCCT가 mm로 변환. 설계 공차·PMI는 해석하지 않음.", scale_factor=1.)
            model = Model(mesh, meta, features, face_ids, body_ids)
    elif suffix == ".3mf":
        from .three_mf import read_3mf
        raw,info=read_3mf(data,max_faces=MAX_FACES)
        mesh=exact_weld(raw.vertices,raw.faces)
        meta.update(info,surface_component_count=int(mesh.body_count),
                    coordinate_welding="exact coordinate triples; no repair")
        model=Model(mesh,meta)
    elif suffix == ".stl":
        if unit not in UNITS:
            raise ValueError("STL 단위를 mm, cm, m, inch 중에서 지정하세요.")
        # Binary STL facet count can be rejected before allocating large arrays.
        if len(data) >= 84 and 84 + int.from_bytes(data[80:84], "little") * 50 == len(data):
            if int.from_bytes(data[80:84], "little") > MAX_FACES:
                raise ValueError("삼각형 600,000개 입력 한도를 초과했습니다.")
        try:
            raw = trimesh.load(io.BytesIO(data), file_type="stl", process=False)
        except Exception as exc:
            raise ValueError(f"STL을 읽을 수 없습니다: {exc}") from exc
        if not isinstance(raw, trimesh.Trimesh) or not len(raw.faces):
            raise ValueError("삼각형 메시가 없는 STL입니다.")
        if len(raw.faces) > MAX_FACES:
            raise ValueError("삼각형 600,000개 입력 한도를 초과했습니다.")
        if not np.isfinite(raw.vertices).all():
            raise ValueError("NaN/무한대 좌표가 있어 분석할 수 없습니다.")
        scale = UNITS[unit]
        if target_longest_mm is not None:
            if not np.isfinite(target_longest_mm) or target_longest_mm <= 0 or max(raw.extents) <= 0:
                raise ValueError("기준 길이는 유한한 양수여야 합니다.")
            scale = target_longest_mm / max(raw.extents)
        mesh = exact_weld(raw.vertices * scale, raw.faces)
        meta.update(unit_status="user_confirmed" if dimensions_confirmed else "assumed",
                    dimensions_confirmed=bool(dimensions_confirmed), selected_unit=unit,
                    scale_factor=float(scale), target_longest_mm=target_longest_mm,
                    unit_note="STL에는 단위가 없습니다. 표시 치수는 선택 단위·배율에 따른 값입니다.",
                    coordinate_welding="exact coordinate triples; no repair", solid_count=None,
                    surface_component_count=int(mesh.body_count),
                    exact_volume_mm3=None, exact_area_mm2=None)
        model = Model(mesh, meta)
    else:
        raise ValueError("STEP(.step/.stp), STL(.stl) 또는 3MF(.3mf) 파일을 선택하세요.")
    if len(model.mesh.faces) > MAX_FACES or not np.isfinite(model.mesh.vertices).all():
        raise ValueError("유효한 좌표 및 삼각형 수 한도를 만족하지 않습니다.")
    if max(model.mesh.extents) > 1e7 or max(model.mesh.extents) <= 0:
        raise ValueError("모델 치수가 분석 범위를 벗어났습니다. 단위와 축척을 확인하세요.")
    return model
