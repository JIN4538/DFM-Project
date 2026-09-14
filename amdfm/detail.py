from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np

from .models import json_bytes
from .orientation import measure_orientation, unit_direction
from .processes import run_bounded


def run_detail(model, profile, direction=(0,0,1), *, mode="wall", timeout_s=60, sample_count=64,
               sampling="uniform", max_event_samples=8192):
    if mode not in ("wall", "layers", "sections"):
        raise ValueError("알 수 없는 상세 검토입니다.")
    profile.validate()
    direction = unit_direction(direction).tolist()
    orientation = measure_orientation(model.mesh, direction, profile)
    context = dict(mode=mode, fingerprint=model.fingerprint, profile=profile.to_dict(),
        direction=orientation["direction"], placement_transform=orientation["transform"],
        coordinate_frame="model_mm" if mode == "wall" else "build_mm")
    if mode=="sections":
        if sampling not in ("uniform", "events"):
            raise ValueError("단면 배치 방법은 uniform 또는 events여야 합니다.")
        if isinstance(sample_count,bool) or not np.isfinite(sample_count) or int(sample_count)!=sample_count or not 2<=sample_count<=1024:
            raise ValueError("단면 표본 수는 2~1,024의 정수여야 합니다.")
        if sampling=="events":
            if isinstance(max_event_samples,bool) or not np.isfinite(max_event_samples) or int(max_event_samples)!=max_event_samples or not 2<=max_event_samples<=8192:
                raise ValueError("형상 변화 단면 한도는 2~8,192의 정수여야 합니다.")
            context.update(sampling=sampling,max_event_samples=int(max_event_samples))
        else:
            context["sample_count"]=int(sample_count)
    if mode == "layers" and profile.process != "MEX":
        return {**context, "status":"not_applicable",
                "reason":"MEX 층간 검토를 다른 공정에 적용하지 않습니다."}
    if model.metadata.get("cad_geometry_kind")=="surface":
        return {**context,"status":"unknown",
                "reason":"곡면 전용 STEP은 재료 내부가 정의되지 않습니다. 두께·재료 단면·층간 판정에는 유효한 솔리드가 필요합니다."}
    with tempfile.TemporaryDirectory(prefix="amdfm-detail-") as tmp:
        base = Path(tmp)
        np.savez_compressed(base/"mesh.npz", vertices=model.mesh.vertices, faces=model.mesh.faces)
        (base/"request.json").write_bytes(json_bytes(dict(**context,
            assembly=(model.metadata.get("solid_count") or 1)>1,
            ambiguous_stl_shells=model.metadata.get("source_format") in ("stl","3mf") and (
                model.metadata.get("surface_component_count",1)>1 or len(model.metadata.get("mesh_instances",[]))>1))))
        try:
            proc = run_bounded([sys.executable, "-m", "amdfm.detail_worker", str(base)],
                cwd=Path(__file__).resolve().parents[1], timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return {**context, "status":"unknown",
                    "reason":f"상세 계산이 {timeout_s:g}초 한도를 초과했습니다. 빠른 검토 결과는 유지됩니다."}
        except OSError as exc:
            return {**context,"status":"unknown",
                    "reason":f"상세 계산 프로세스를 시작하거나 격리하지 못했습니다: {exc}"}
        if not (base/"result.json").exists() or proc.returncode:
            return {**context, "status":"unknown",
                    "reason":"상세 계산 프로세스가 완료되지 않았습니다. 단순화한 형상 또는 단일 솔리드로 재검토하세요."}
        return json.loads((base/"result.json").read_text(encoding="utf-8"))


def attach_detail(report, detail):
    if detail.get("fingerprint") != report["model_fingerprint"]:
        raise ValueError("상세 결과의 입력 모델이 현재 결과와 다릅니다.")
    # Protect against mixing a result after profile/orientation changes.
    if "profile" in detail and detail["profile"] != report["profile"]:
        raise ValueError("상세 검토 프로필이 현재 결과와 다릅니다.")
    if "direction" in detail and not np.allclose(unit_direction(detail["direction"]),
            unit_direction(report["current_orientation"]["direction"]), rtol=0, atol=1e-12):
        raise ValueError("상세 검토 방향이 현재 결과와 다릅니다.")
    if "placement_transform" in detail:
        actual = np.asarray(detail["placement_transform"], dtype=float)
        expected = np.asarray(report["current_orientation"]["transform"], dtype=float)
        if actual.shape != (4,4) or not np.isfinite(actual).all() or not np.allclose(
                actual, expected, rtol=1e-12, atol=1e-10):
            raise ValueError("상세 검토 배치가 현재 결과와 다릅니다.")
    result = copy.deepcopy(report)
    mode = detail.get("mode")
    result.setdefault("details", {})[mode] = detail
    if mode == "wall":
        wall = next(f for f in result["findings"] if f["id"] == "wall")
        if detail["status"] in ("measured", "partial"):
            m = detail["measurements"]
            limit = result["profile"]["minimum_wall_mm"]
            suspected = m["below_limit_face_indices"]
            wall.update(status="attention" if suspected else "observed",
                reason=f"법선 방향 거리 표본 {m['valid_samples']}개에서 최소 {m['minimum_mm']:.4g} mm를 관측했습니다.",
                method="deterministic area/detection face samples; inward first-hit normal chords",
                measurements=m, face_indices=suspected if suspected else m["thinnest_face_indices"],
                action=(f"표시된 구간을 {limit:g} mm 검토 기준과 대조하고, 벽 보강·형상 수정·다른 공정 조건을 비교하세요." if limit else
                        "표시된 얇은 구간을 확인하고 장비별 검토 기준을 입력하세요."+
                        (" MEX에서는 가변 선폭 경로와 비교하세요." if result["profile"]["process"]=="MEX" else "")),
                limitations=["관측 최소는 모델 전체의 최소 두께가 아닙니다. 비평행면에서는 법선 관통거리입니다.",
                    "면적 대표 백분위는 유효 표본에 한정됩니다. 작은 특징·자기교차·표본 밖 구간을 놓칠 수 있습니다."])
        else:
            wall.update(status="unknown", reason=detail.get("reason","두께를 측정하지 못했습니다."),
                        measurements={}, face_indices=[], cad_face_ids=[])
    elif mode == "sections":
        finding = next(f for f in result["findings"] if f["id"] == "sections")
        known = detail.get("complete_samples", 0)
        finding.update(status="observed" if detail["status"]=="complete" else "unknown",
            reason=(f"요청 {detail.get('requested_samples', detail.get('sample_count', '—'))}개 중 {known}개 단면의 면적·둘레를 측정했습니다. "
                    +detail.get("reason", "표본 사이의 극값과 실제 공정의 힘·온도는 계산하지 않습니다.")),
            measurements={k:v for k,v in detail.items() if k not in (
                "rows","profile","direction","placement_transform","fingerprint")},
            method=detail.get("method","uniform_midpoint_sections/1"))
    result["summary"]["attention_items"] = sum(f["status"]=="attention" for f in result["findings"])
    return result
