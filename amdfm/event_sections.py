"""Vertex-event quadrature of placed mesh sections; no process-physics model.

Between successive distinct vertex heights, polyhedral section-edge endpoints
are affine functions of height. The oriented polygon area is quadratic, so two
Gauss-Legendre nodes integrate it exactly in exact arithmetic for a valid,
non-self-intersecting material boundary. Actual section reconstruction, floating
point representation, topology and budgets are checked separately.
"""
from __future__ import annotations

import math
from fractions import Fraction

import numpy as np
import shapely as sh

from src.core.mesh_diagnostics import inspect_mesh
from src.core.section_index import FaceZIndex
from src.core.sections import section_mesh


def _positive_integer(value, name):
    if isinstance(value, bool) or not np.isfinite(value) or value < 1 or int(value) != value:
        raise ValueError(f"{name}는 양의 정수여야 합니다.")
    return int(value)


def _rounded_up_nonnegative(value):
    """Smallest float at least an exact nonnegative rational; None on overflow.

    This only makes envelope arithmetic conservative for the input float
    coordinates. It cannot bound section reconstruction or quadrature errors.
    """
    try:
        rounded = float(value)
    except OverflowError:
        return None
    if not math.isfinite(rounded):
        return None
    if Fraction(rounded) < value:
        rounded = math.nextafter(rounded, math.inf)
    return rounded if math.isfinite(rounded) else None


def _omission_envelope(vertices, unresolved_ranges):
    """AABB-XY times omitted Z width, with outward rounding, for this mesh.

    Exact rationals avoid downward rounding of tiny height differences or their
    sum/product. This bounds only material inside the omitted height ranges;
    the computed integral over the other ranges remains a numerical estimate.
    """
    missing = sum((Fraction(hi)-Fraction(lo) for lo, hi in unresolved_ranges), Fraction())
    bounds = np.array([vertices[:, :2].min(axis=0), vertices[:, :2].max(axis=0)])
    area = (Fraction(float(bounds[1, 0]))-Fraction(float(bounds[0, 0]))) * (
        Fraction(float(bounds[1, 1]))-Fraction(float(bounds[0, 1])))
    return _rounded_up_nonnegative(missing), _rounded_up_nonnegative(missing*area)


def _row(index, z, section, previous, interval_index, weight):
    diag = section.diagnostics
    complete = bool(diag["complete"])
    current = section.material if complete else None
    row = dict(index=index, z_mm=z, complete=complete, area_mm2=None, perimeter_mm=None,
        area_per_perimeter_mm=None, material_regions=None, internal_loops=None,
        area_change_from_previous_mm2=None, symmetric_change_from_previous_mm2=None,
        added_area_from_previous_mm2=None, removed_area_from_previous_mm2=None,
        outlines=[], outlines_complete=False, diagnostics=diag,
        interval_index=interval_index, quadrature_weight_mm=weight)
    if complete:
        area, perimeter = float(current.area), float(current.length)
        polygons = [p for p in sh.get_parts(current) if p.geom_type == "Polygon"]
        row.update(area_mm2=area, perimeter_mm=perimeter,
            area_per_perimeter_mm=area/perimeter if perimeter > 0 else None,
            material_regions=len(polygons), internal_loops=sum(len(p.interiors) for p in polygons))
        rings = [np.asarray(r.coords).tolist() for p in polygons for r in (p.exterior, *p.interiors)]
        if sum(len(r) for r in rings) <= 4096:
            row.update(outlines=rings, outlines_complete=True)
        if previous is not None:
            row.update(area_change_from_previous_mm2=area-float(previous.area),
                symmetric_change_from_previous_mm2=float(current.symmetric_difference(previous).area),
                added_area_from_previous_mm2=float(current.difference(previous).area),
                removed_area_from_previous_mm2=float(previous.difference(current).area))
    return row, current


def inspect_event_sections(mesh, max_samples=8192, *, max_total_segments=1_500_000):
    max_samples = _positive_integer(max_samples, "단면 표본 예산")
    max_total_segments = _positive_integer(max_total_segments, "교차 선분 예산")
    result = dict(status="unknown", method="vertex_event_intervals_gauss2/1",
        sampling_method="vertex_events_gauss2", rows=[], intervals=[], requested_samples=None,
        examined_samples=0, complete_samples=0, sample_spacing_mm=None,
        sampled_max_area_mm2=None, sampled_max_perimeter_mm=None,
        sampled_max_area_per_perimeter_mm=None, sampled_max_symmetric_change_mm2=None,
        volume_quadrature_estimate_mm3=None, volume_midpoint_estimate_mm3=None,
        known_interval_volume_mm3=None, unresolved_height_mm=None,
        omitted_interval_volume_envelope_mm3=None, total_segments=0,
        known_plus_omitted_envelope_mm3=None,
        omitted_interval_volume_envelope_relative_to_known=None,
        representation_limit_only=False, complete_event_intervals=0,
        unexamined_event_intervals=None, unresolved_interval_counts={},
        budget_exceeded=False, budget_reasons=[], failure_code=None,
        max_samples=max_samples, max_total_segments=max_total_segments,
        scope="Two Gauss nodes per exact vertex-height interval of a placed mesh; sampled maxima are not global extrema. No manufacturing-layer, peel-force, thermal or self-intersection certification.",
        integration_assumption="Piecewise quadratic section area for a valid oriented non-self-intersecting polyhedral material boundary; numerical section errors are not eliminated by quadrature.",
        envelope_scope="AABB XY area times unresolved height bounds only the omitted-height contribution; it is not a bound on total error, section reconstruction error or manufacturing uncertainty. Envelope arithmetic is rounded upward from exact rational values of the input float coordinates. The known sum and known-plus-envelope are estimates, not certified total-volume lower and upper bounds.")
    diag = inspect_mesh(mesh)
    result["input_diagnostics"] = diag
    if not diag["topology_ready"]:
        result["reason"] = "입력 폐곡면·면 방향 조건이 충족되지 않아 높이 사건 단면 검산을 보류했습니다."
        result["failure_code"] = "input_topology"
        return result
    # Use referenced vertices only; an unused vertex is not a material event.
    referenced = np.unique(mesh.faces)
    heights, inverse = np.unique(mesh.vertices[referenced, 2], return_inverse=True)
    if len(heights) < 2 or not np.isfinite(heights).all():
        result["reason"] = "양의 유한한 빌드 높이가 필요합니다."
        result["failure_code"] = "invalid_build_height"
        return result
    ranks = np.empty(len(mesh.vertices), dtype=np.int64)
    ranks[referenced] = inverse
    face_ranks = ranks[mesh.faces]
    planned_segments = int(2*np.sum(face_ranks.max(axis=1)-face_ranks.min(axis=1), dtype=np.int64))
    count = 2*(len(heights)-1)
    widths = np.diff(heights)
    result.update(requested_samples=count, event_count=len(heights), event_interval_count=len(heights)-1,
        planned_triangle_intersections=planned_segments,
        covered_height_mm=[float(heights[0]), float(heights[-1])],
        minimum_event_interval_mm=float(widths.min()),
        sample_policy="Exact unique referenced vertex heights; no tolerance merging; two Gauss-Legendre interior nodes per interval, independent of physical layer height.")
    if count > max_samples or planned_segments > max_total_segments:
        result.update(reason="높이 사건 단면 수 또는 예상 교차 선분이 계산 예산을 초과했습니다. 표본을 자동으로 줄이지 않았습니다.",
            budget_exceeded=True, failure_code="event_budget_exceeded",
            budget_reasons=(["sample_budget"] if count > max_samples else []) +
                (["intersection_budget"] if planned_segments > max_total_segments else []),
            unexamined_event_intervals=len(heights)-1)
        return result
    index = FaceZIndex(mesh)
    previous = None
    pieces, unresolved_ranges = [], []
    total_segments = 0
    for i, (lo, hi) in enumerate(zip(heights[:-1], heights[1:])):
        width = float(hi-lo)
        middle = float(lo+width/2)
        nodes = (float(middle-width/(2*math.sqrt(3))), float(middle+width/(2*math.sqrt(3))))
        interval = dict(index=i, lower_mm=float(lo), upper_mm=float(hi), width_mm=width,
            complete=False, row_indices=[], volume_estimate_mm3=None, unresolved_cause=None)
        if not (lo < nodes[0] < nodes[1] < hi):
            interval["reason"] = "서로 다른 두 Gauss 내점을 부동소수 높이로 표현할 수 없습니다. 사건 높이를 임의 병합하지 않았습니다."
            interval["unresolved_cause"] = "representation_limit"
            unresolved_ranges.append((float(lo), float(hi)))
            result["intervals"].append(interval)
            previous = None
            continue
        runtime_budget = False
        for z in nodes:
            section = section_mesh(mesh, [0.,0.,z], [0.,0.,1.], axes=np.eye(3)[:2],
                local_faces=index.sweep(z), vertex_projection=index.projection, mesh_scale_mm=index.scale_mm)
            total_segments += section.diagnostics["segment_count"]
            if total_segments > max_total_segments:
                runtime_budget = True
                interval["unresolved_cause"] = "runtime_budget"
                interval["reason"] = "실제 교차 선분 예산에 도달하여 남은 구간을 검토하지 않았습니다."
                previous = None
                break
            row, previous = _row(len(result["rows"]), z, section, previous, i, width/2)
            interval["row_indices"].append(row["index"])
            result["rows"].append(row)
        rows = [result["rows"][k] for k in interval["row_indices"]]
        if len(rows) == 2 and all(r["complete"] for r in rows):
            interval.update(complete=True, volume_estimate_mm3=width*math.fsum(r["area_mm2"] for r in rows)/2)
            pieces.append(interval["volume_estimate_mm3"])
        else:
            unresolved_ranges.append((float(lo), float(hi)))
            if not runtime_budget:
                interval["unresolved_cause"] = "section_failure"
                interval["reason"] = "두 내부 표본에서 모두 닫힌 재료 단면을 확보하지 못했습니다."
        result["intervals"].append(interval)
        if runtime_budget:
            if hi < heights[-1]:
                unresolved_ranges.append((float(hi), float(heights[-1])))
            result["reason"] = interval["reason"]
            result.update(failure_code="event_runtime_budget_exceeded", budget_exceeded=True,
                budget_reasons=["runtime_intersection_budget"])
            break
    rows = result["rows"]
    complete = [r for r in rows if r["complete"]]
    all_complete = len(result["intervals"]) == len(heights)-1 and all(i["complete"] for i in result["intervals"])
    known = math.fsum(pieces)
    missing, envelope = _omission_envelope(mesh.vertices[referenced], unresolved_ranges)
    causes = {key: sum(interval["unresolved_cause"] == key for interval in result["intervals"])
              for key in ("representation_limit", "section_failure", "runtime_budget")}
    unexamined = len(heights)-1-len(result["intervals"])
    representation_only = (not all_complete and unexamined == 0 and causes["representation_limit"] > 0
                           and causes["section_failure"] == causes["runtime_budget"] == 0)
    result.update(status="complete" if all_complete else "partial" if complete else "unknown",
        examined_samples=len(rows), complete_samples=len(complete), total_segments=total_segments,
        known_interval_volume_mm3=known, unresolved_height_mm=missing,
        omitted_interval_volume_envelope_mm3=envelope, unresolved_interval_counts=causes,
        representation_limit_only=representation_only, complete_event_intervals=len(pieces),
        unexamined_event_intervals=unexamined)
    if envelope is not None and math.isfinite(known):
        result["known_plus_omitted_envelope_mm3"] = _rounded_up_nonnegative(Fraction(known)+Fraction(envelope))
        if known > 0:
            result["omitted_interval_volume_envelope_relative_to_known"] = _rounded_up_nonnegative(Fraction(envelope)/Fraction(known))
    if all_complete:
        result["volume_quadrature_estimate_mm3"] = known
    elif "reason" not in result:
        result["reason"] = "표현 가능한 내점 또는 닫힌 단면을 확보하지 못한 높이 구간이 있어 전체 체적 검산은 미확정입니다."
    for target, key in (("sampled_max_area_mm2", "area_mm2"), ("sampled_max_perimeter_mm", "perimeter_mm"),
            ("sampled_max_area_per_perimeter_mm", "area_per_perimeter_mm"),
            ("sampled_max_symmetric_change_mm2", "symmetric_change_from_previous_mm2")):
        values = [r[key] for r in rows if r[key] is not None]
        result[target] = max(values) if values else None
    return result
