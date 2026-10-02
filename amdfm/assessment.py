"""Run the applicable geometric checks together without changing their meaning.

The time shares below are a UI execution policy, not manufacturing limits. Each
query still uses the existing isolated worker, geometry budgets and failure
semantics. Incomplete results remain incomplete; no coarser physical layer
height is substituted to make a large part finish.
"""
from __future__ import annotations

import copy
import math
import subprocess
import time

import numpy as np

from .analysis import code_digest
from .detail import attach_detail, run_detail
from .evidence import section_guidance
from .models import plain
from .orientation import measure_orientation, unit_direction


SCHEMA = "amdfm-automatic-assessment/1"
# Worker caps reserve time for later checks even when the first one is slow.
_MODE_CAPS = {"wall": 10.0, "layers": 20.0, "sections": 15.0}


def _context(model, profile, direction):
    orientation = measure_orientation(model.mesh, direction, profile)
    return plain(dict(fingerprint=model.fingerprint, profile=profile.to_dict(),
                direction=orientation["direction"],
                placement_transform=orientation["transform"]))


def _unrun(context, mode, code, reason):
    return dict(context, mode=mode, status="unknown", reason=reason,
                failure_code=code,
                coordinate_frame="model_mm" if mode == "wall" else "build_mm")


def run_assessment(model, profile, direction=(0, 0, 1), *, budget_s=45.0,
                   on_progress=None, cancel_requested=None, detail_runner=None):
    """Return fresh wall/layer/section results for one exact model and placement.

    MEX runs wall, physical-layer checks and process-neutral sections. The
    other supported AM processes run wall and process-neutral sections only.
    ``detail_runner`` defaults to the production isolated-worker runner; a
    caller may supply the same runner it uses for manual detail checks.

    The shared deadline includes orchestration; remaining time is checked
    before every query. Serialization and worker cleanup may add overhead to
    the worker timeout, so this is not a hard end-to-end latency guarantee.
    Cancellation is checked between queries, not during a geometry operation.
    Progress callbacks receive a small dict with mode/phase/index/total/status.
    """
    if isinstance(budget_s, bool) or not math.isfinite(budget_s) or budget_s <= 0:
        raise ValueError("자동 검토 시간 예산은 유한한 양수여야 합니다.")
    profile.validate()
    started = time.monotonic()
    revision = code_digest()
    context = _context(model, profile, unit_direction(direction))
    modes = ["wall", "layers", "sections"] if profile.process == "MEX" else ["wall", "sections"]
    runner = detail_runner if detail_runner is not None else run_detail
    results, steps = {}, []
    cancelled = False
    for index, mode in enumerate(modes):
        if cancel_requested is not None and cancel_requested():
            cancelled = True
        remaining = float(budget_s) - (time.monotonic() - started)
        remaining_caps = sum(_MODE_CAPS[m] for m in modes[index:])
        # For a shorter total budget, reserve proportional shares for all
        # remaining checks. Fast earlier queries donate unused time, up to cap.
        allocation = min(_MODE_CAPS[mode], max(0., remaining) * _MODE_CAPS[mode] / remaining_caps)
        if cancelled:
            result = _unrun(context, mode, "automatic_cancelled",
                "자동 검토가 중단되어 이 항목은 계산하지 않았습니다. 앞서 계산한 결과는 유지됩니다.")
            allocation = 0.
        elif allocation <= 0:
            result = _unrun(context, mode, "automatic_budget_exhausted",
                "자동 검토의 전체 시간 예산을 사용해 이 항목은 계산하지 않았습니다. 항목별 추가 계산으로 이어갈 수 있습니다.")
        else:
            if on_progress is not None:
                on_progress(dict(mode=mode, phase="started", index=index + 1, total=len(modes)))
            kwargs = dict(mode=mode, timeout_s=allocation)
            if mode == "sections":
                kwargs.update(sampling="auto", sample_count=64, max_event_samples=8192)
            try:
                result = runner(model, profile, context["direction"], **kwargs)
            except (OSError, subprocess.TimeoutExpired) as exc:
                # The production runner already reports worker launch/timeouts;
                # temporary-file I/O can fail before it reaches that boundary.
                # Preserve completed siblings without turning this into a pass.
                result = _unrun(context, mode, "automatic_worker_failed",
                    f"자동 검토 작업을 완료하지 못했습니다: {exc}. 앞서 계산한 결과는 유지됩니다.")
            # A custom runner must return exactly the requested query. Identity
            # and profile validation also occur when the bundle is attached.
            if result.get("mode") != mode:
                raise ValueError("자동 검토 작업자가 요청한 항목과 다른 결과를 반환했습니다.")
            result = plain(result)
        result.update(execution_trigger="automatic_assessment",
                      execution_budget_seconds=allocation)
        results[mode] = result
        steps.append(dict(mode=mode, status=result.get("status", "unknown"),
                          allocated_seconds=allocation,
                          reason=result.get("reason")))
        if on_progress is not None:
            on_progress(dict(mode=mode, phase="finished", index=index + 1,
                             total=len(modes), status=result.get("status", "unknown")))
    statuses = [result.get("status") for result in results.values()]
    completed = all(status in ("measured", "complete") for status in statuses)
    observed = any(status in ("measured", "complete", "partial") for status in statuses)
    return dict(schema=SCHEMA, **context, code_sha256=revision,
                planned_modes=modes, details=results, steps=steps,
                status="complete" if completed else "partial" if observed else "unknown",
                cancelled=cancelled, budget_seconds=float(budget_s),
                elapsed_seconds=time.monotonic() - started,
                scope="선택 방향에서 자동 실행한 기하 검토의 계산 상태입니다. 제조 성공·강도·전 영역 최소 두께의 판정이 아닙니다.")


def attach_assessment(report, assessment):
    """Attach only results made by the current code for this exact review.

    No earlier detail result is reused to conceal a failed or interrupted new
    attempt. The incoming automatic modes replace those modes in the report,
    including explicit unknown results.
    """
    if assessment.get("schema") != SCHEMA:
        raise ValueError("자동 검토 결과 형식이 현재 버전과 다릅니다.")
    if assessment.get("fingerprint") != report["model_fingerprint"]:
        raise ValueError("자동 검토 결과의 모델이 현재 결과와 다릅니다.")
    if assessment.get("profile") != report["profile"]:
        raise ValueError("자동 검토 결과의 프로필이 현재 결과와 다릅니다.")
    if not np.allclose(unit_direction(assessment["direction"]),
                       unit_direction(report["current_orientation"]["direction"]), rtol=0, atol=1e-12):
        raise ValueError("자동 검토 결과의 방향이 현재 결과와 다릅니다.")
    matrix = np.asarray(assessment["placement_transform"], dtype=float)
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all() or not np.allclose(
            matrix, report["current_orientation"]["transform"], rtol=1e-12, atol=1e-10):
        raise ValueError("자동 검토 결과의 배치가 현재 결과와 다릅니다.")
    revision = assessment.get("code_sha256")
    if revision != report.get("provenance", {}).get("code_sha256") or revision != code_digest():
        raise ValueError("계산 코드 또는 조건 DB가 변경되었습니다. 설계 검토를 다시 실행하세요.")
    expected = ["wall", "layers", "sections"] if report["profile"]["process"] == "MEX" else ["wall", "sections"]
    if assessment.get("planned_modes") != expected or set(assessment.get("details", {})) != set(expected):
        raise ValueError("자동 검토 항목이 현재 공정에 필요한 항목과 다릅니다.")
    result = copy.deepcopy(report)
    for mode in expected:
        detail = assessment["details"][mode]
        # attach_detail permits minimal legacy payloads; automatic bundles
        # deliberately require a full identity on every individual result.
        if detail.get("mode") != mode or any(key not in detail for key in
                ("fingerprint", "profile", "direction", "placement_transform")) or any(
                detail[key] != assessment[key] for key in ("fingerprint", "profile")):
            raise ValueError("자동 검토 묶음에 다른 입력의 상세 결과가 포함되어 있습니다.")
        result = attach_detail(result, detail)
    sections = result["details"]["sections"]
    if sections.get("status") == "complete":
        finding = next(item for item in result["findings"] if item["id"] == "sections")
        finding["action"] = section_guidance(result["profile"]["process"])["action"]
    result["automatic_assessment"] = {key: copy.deepcopy(value) for key, value in assessment.items()
                                      if key != "details"}
    return result
