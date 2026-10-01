"""Local learned ranking of verified finite improvement plans.

Detection remains geometric. Unlike rule-review imitation, the fitted score
actually selects among admissible, nondominated alternatives. The shipped prior
is trained on a disclosed project preference objective. Explicit local choices
fit a separate pairwise preference residual; they never change hard constraints.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import struct
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "data/models/plan_ranker_v1.json"
SCHEMA = "dfm-plan-ranker-1"
FEATURES = ("cnc", "regret_0", "regret_1", "regret_2", "geometry_change", "tool_change",
            "tool_slenderness", "change_count", "priority_support", "priority_height", "priority_contact",
            "priority_accuracy", "priority_cost", "priority_tool_access", "active_support", "active_height", "active_contact")
TEACHER_SOURCES = ("amdfm/orientation.py", "amdfm/recommendation.py", "dfm/machining.py", "dfm/plan_learning.py")
AM_FIELDS = {"MEX": ("overhang_projected_area_sum_mm2", "height_mm", "contact_triangle_area_mm2"),
             "VPP": ("overhang_projected_area_sum_mm2", "height_mm"),
             "PBF_METAL": ("overhang_projected_area_sum_mm2", "height_mm"), "PBF_POLYMER": ("height_mm",)}
FIELD_LABELS = {"overhang_projected_area_sum_mm2": ("하향면 투영 합", "mm²"), "height_mm": ("높이", "mm"),
                "contact_triangle_area_mm2": ("평평한 바닥", "mm²")}


def source_hashes():
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in TEACHER_SOURCES}


def _num(value, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or positive and value <= 0:
        raise ValueError("유한한 치수·조건을 확인하세요")
    return float(value)


def _process(report):
    return report.get("profile", {}).get("process", report.get("process"))


def _preferences(report, preferences=None):
    context = report.get("review_context") or {}
    values = {"priority": context.get("priority", "balanced"), "preserve_geometry": False, "allow_tool_change": True}
    values.update(preferences or {})
    if values["priority"] not in ("balanced", "support", "height", "contact", "strength", "surface", "accuracy", "cost", "tool_access"):
        raise ValueError("지원하는 검토 중점을 선택하세요")
    if type(values["preserve_geometry"]) is not bool or type(values["allow_tool_change"]) is not bool:
        raise ValueError("변경 허용 조건을 확인하세요")
    return values


def _features(plan, preferences):
    v = plan["_metrics"]
    priority = preferences["priority"]
    if priority not in (("balanced", "accuracy", "tool_access") if plan["family"] == "CNC" else ("balanced", "support", "height", "contact")):
        priority = "balanced"
    return [float(plan["family"] == "CNC"), *v["regrets"], v.get("geometry_change", 0.), v.get("tool_change", 0.),
            v.get("slenderness", 0.), min(1., len(plan.get("changes", [])) / 8) if plan["family"] == "CNC" else 0.] + [float(priority == name) for name in
            ("support", "height", "contact", "accuracy", "cost", "tool_access")] + plan.get("_active", [0., 0., 0.])


def _dominates(left, right):
    a, b = left["_dominance"], right["_dominance"]
    return all(x <= y + 1e-10 for x, y in zip(a, b)) and any(x < y - 1e-10 for x, y in zip(a, b))


def _stable(plan):
    from amdfm.orientation import DIRECTIONS
    name = (plan.get("orientation") or {}).get("name")
    return (list(DIRECTIONS).index(name) if name in DIRECTIONS else 99, plan["id"])


def selection_index(scores, stable_keys):
    """One tie policy shared by exported inference and evaluation."""
    return min(range(len(scores)), key=lambda i: (-round(float(scores[i]), 9), tuple(stable_keys[i])))


def _am_candidates(report):
    from amdfm.recommendation import recommend_orientation
    base = recommend_orientation(report)
    if base.get("recommended") is None:
        return [], base.get("title", "방향 측정을 완료하세요"), None
    fields = AM_FIELDS[_process(report)]
    criteria = base["criteria"]
    current = report.get("current_orientation") or {}
    rows = list(base["ranking"])
    fit_ok = report.get("profile", {}).get("build_volume_mm") is None or current.get("build_fit") is True
    # A custom current direction can dominate the fixed search set. Include its
    # actual measurements; never display an inferior candidate as a keep result.
    if fit_ok and all(isinstance(current.get(f), (int, float)) and not isinstance(current[f], bool) and math.isfinite(current[f]) and current[f] >= 0 for f in fields):
        values = lambda row: [(-row[f] if f == "contact_triangle_area_mm2" else row[f]) for f in fields]
        cv = values(current)
        strictly_dominates = lambda row: all(a <= b + 1e-8 for a, b in zip(cv, values(row))) and any(a < b - 1e-8 for a, b in zip(cv, values(row)))
        if any(strictly_dominates(row) for row in rows) and not any(all(math.isclose(current[f], row[f], rel_tol=1e-9, abs_tol=1e-8) for f in fields) for row in rows):
            row = deepcopy(current)
            row.setdefault("name", "현재 사용자 방향")
            row["policy_score"] = 0.
            row["_custom_current"] = True
            rows.append(row)
    result = []
    for row in rows:
        regrets = []
        for criterion in criteria:
            value = _num(row[criterion["field"]])
            lo, hi = criterion["minimum"], criterion["maximum"]
            regret = 0. if criterion["constant"] else (value - lo) / (hi - lo)
            if criterion["direction"] == "max" and not criterion["constant"]:
                regret = 1 - regret
            regrets.append(max(0., min(1., regret)))
        # Slots have consistent meaning, including polymer height-only scope.
        slots = [0., 0., 0.]
        for field, regret in zip(fields, regrets):
            slots[{"overhang_projected_area_sum_mm2": 0, "height_mm": 1, "contact_triangle_area_mm2": 2}[field]] = regret
        changes, evidence = [], []
        same = True
        for field in fields:
            new = row[field]
            old = current.get(field)
            label, unit = FIELD_LABELS[field]
            evidence.append(f"{label} {old:,.4g} → {new:,.4g} {unit}" if isinstance(old, (int, float)) else f"{label} {new:,.4g} {unit}")
            if isinstance(old, (int, float)):
                near = math.isclose(old, new, rel_tol=1e-9, abs_tol=1e-8)
                same &= near
            else:
                same = False
        keep = fit_ok and same
        if not keep:
            changes.append(dict(field="direction", label="빌드 방향", before=current.get("direction"), after=row["direction"], unit="vector"))
        remaining_ids = []
        remaining = []
        if "overhang_projected_area_sum_mm2" in fields and row["overhang_projected_area_sum_mm2"] > 1e-8:
            remaining_ids.append("overhang")
            remaining.append(f"변경 뒤 하향면 투영 합 {row['overhang_projected_area_sum_mm2']:,.4g} mm²가 남습니다")
        if "contact_triangle_area_mm2" in fields and row["contact_triangle_area_mm2"] <= 1e-8:
            remaining_ids.append("contact")
            remaining.append("평평한 바닥이 없어 바닥 형상 확인이 남습니다")
        result.append(dict(id="orientation:" + str(row["name"]), family="AM", title="현재 방향 유지" if keep else f"{row['name']} 방향으로 변경",
                           changes=changes, evidence=evidence, remaining=remaining, outcomes={f: row[f] for f in fields},
                           verification_scope="현재 형상에서 직접 계산한 방향별 기하량", verified=True, orientation=deepcopy(row), keep_current=keep,
                           covered_finding_ids=["build"] + (["overhang"] if "overhang_projected_area_sum_mm2" in fields else []) + (["contact"] if "contact_triangle_area_mm2" in fields else []),
                           remaining_finding_ids=remaining_ids,
                           _metrics={"regrets": slots}, _dominance=[-row[f] if f == "contact_triangle_area_mm2" else row[f] for f in fields], _baseline=float(row["policy_score"]),
                           _active=[float(f in fields) for f in ("overhang_projected_area_sum_mm2", "height_mm", "contact_triangle_area_mm2")]))
    return result, "", "orientation:" + str(base["recommended"]["name"])


def _cnc_pocket_rows(report):
    findings = {f['id']: f for f in report.get('findings', [])}
    rows = []
    seen = set()
    for key in ('cnc_rectangular_pockets', 'cnc_learned_pockets'):
        for row in (findings.get(key, {}).get('measurements') or {}).get('pockets') or []:
            identifier = row.get('floor_face_id')
            if identifier is not None and identifier in seen:
                continue
            if identifier is not None:
                seen.add(identifier)
            # A triangle's minimum caliper is larger than its entry disk.
            # Compare the mill against the independently measured disk, and
            # name any proposed geometric change using that same quantity.
            learned = key == 'cnc_learned_pockets'
            clearance = row.get('entry_circle_diameter_mm') if learned else row['width_mm']
            if learned and clearance is None:
                continue
            rows.append(dict(row, planning_width_mm=clearance, finding_id=key,
                planning_width_label='포켓 진입원 지름' if learned else '포켓 폭'))
    return rows


def _cnc_inputs(report):
    findings = {r.get("id"): r for r in report.get("findings", [])}
    if (findings.get("cnc_input", {}).get("measurements") or {}).get("cad_feature_dimensions_available") is not True:
        raise ValueError("단일 솔리드 STEP의 치수 검토가 필요합니다")
    profile = report.get("profile") or {}
    for name in ("tool_diameter_mm", "flute_length_mm", "reach_mm"):
        _num(profile.get(name), True)
    if profile["flute_length_mm"] > profile["reach_mm"]:
        raise ValueError("날 길이는 돌출 길이보다 클 수 없습니다")
    holes = (findings.get("cnc_holes", {}).get("measurements") or {}).get("cylindrical_faces") or []
    corners = (findings.get("cnc_curved_corners", {}).get("measurements") or {}).get("cylindrical_faces") or []
    pockets = _cnc_pocket_rows(report)
    known_holes = []
    remaining = []
    unresolved_ids = []
    for index, row in enumerate(holes):
        if not row.get("axis_aligned"):
            remaining.append("축이 다른 구멍은 접근 방향 변경이 필요합니다")
            unresolved_ids.append("cnc_holes")
            continue
        known_holes.append((_num(row["diameter_mm"], True), _num(row["cylindrical_length_mm"], True), index, row.get("face_id")))
    known_corners = [(_num(row["radius_mm"], True), index, row.get("face_id")) for index, row in enumerate(corners)]
    known_pockets = [(_num(row["planning_width_mm"], True), _num(row["wall_height_mm"], True), index, row.get("floor_face_id")) for index, row in enumerate(pockets)]
    for key in ("cnc_coverage", "cnc_holes", "cnc_curved_corners", "cnc_rectangular_pockets", "cnc_learned_pockets", "cnc_visibility"):
        f = findings.get(key, {})
        if f.get("status") == "unknown":
            remaining.append("일부 특징·접근 범위는 미확인입니다")
            unresolved_ids.append(key)
        measurements = f.get("measurements") or {}
        if any(measurements.get(name) for name in ("unresolved_cylinder_face_ids", "unresolved_floor_face_ids", "incomplete_boundary_face_ids", "unsupported_face_ids")):
            remaining.append("일부 특징·접근 범위는 미확인입니다")
            unresolved_ids.append(key)
    if findings.get("cnc_visibility", {}).get("face_indices"):
        remaining.append("가려진 표면의 접근 방향을 확인하세요")
        unresolved_ids.append("cnc_visibility")
    return profile, known_holes, known_corners, known_pockets, list(dict.fromkeys(remaining)), list(dict.fromkeys(unresolved_ids))


def _cnc_candidates(report, preferences):
    from .machining import _length_comparison
    p, holes, corners, pockets, unresolved, unresolved_ids = _cnc_inputs(report)
    pocket_rows = _cnc_pocket_rows(report)
    if not holes and not corners and not pockets:
        return [], "공구와 비교할 원통·포켓 치수가 없습니다", None
    tool, flute, reach = [float(p[k]) for k in ("tool_diameter_mm", "flute_length_mm", "reach_mm")]
    limit = p.get("hole_depth_ratio_limit")
    if limit is not None:
        _num(limit, True)
    openings = [r[0] for r in holes] + [2 * r[0] for r in corners] + [r[0] for r in pockets]
    maximum_depth = max([r[1] for r in holes] + [r[1] for r in pockets] + [reach])
    maximum_wall = max([r[1] for r in pockets] + [flute])
    covered = (["cnc_holes"] if holes else []) + (["cnc_curved_corners"] if corners else []) + list(dict.fromkeys(row['finding_id'] for row in pocket_rows))
    diameters = sorted(set([tool, min([tool] + openings)])) if preferences["allow_tool_change"] else [tool]
    lengths = [(flute, reach)]
    if preferences["allow_tool_change"]:
        lengths += [(flute, maximum_depth), (maximum_wall, max(maximum_wall, maximum_depth))]
    geometry_modes = ("none", "openings", "depth", "both") if not preferences["preserve_geometry"] else ("none",)
    result = []
    seen = set()
    for diameter, (new_flute, new_reach), mode in itertools.product(diameters, lengths, geometry_modes):
        edits = []
        geometric_changes = []
        after_holes, after_corners, after_pockets = [], [], []
        for d, height, index, face_id in holes:
            nd = max(d, diameter, height / limit if limit and mode == "openings" else d) if mode in ("openings", "both") else d
            nh = min(height, new_reach, limit * nd if limit else height) if mode in ("depth", "both") else height
            after_holes.append((nd, nh))
            for field, label, before, after in (("diameter", "구멍 지름", d, nd), ("segment", "원통 구간", height, nh)):
                if not math.isclose(before, after, rel_tol=1e-10, abs_tol=1e-9):
                    edits.append(dict(field=f"hole.{index}.{field}", label=label, before=before, after=after, unit="mm", cad_face_id=face_id))
                    geometric_changes.append(abs(after - before) / before)
        for radius, index, face_id in corners:
            nr = max(radius, diameter / 2) if mode in ("openings", "both") else radius
            after_corners.append(nr)
            if not math.isclose(radius, nr, rel_tol=1e-10, abs_tol=1e-9):
                edits.append(dict(field=f"corner.{index}.radius", label="내부 반경", before=radius, after=nr, unit="mm", cad_face_id=face_id))
                geometric_changes.append(abs(nr - radius) / radius)
        corner_relief = bool(pockets) and mode in ("openings", "both")
        for width, height, index, face_id in pockets:
            nw = max(width, diameter) if mode in ("openings", "both") else width
            nh = min(height, new_flute, new_reach) if mode in ("depth", "both") else height
            after_pockets.append((nw, nh))
            for field, label, before, after in (("width", pocket_rows[index]['planning_width_label'], width, nw), ("wall", "포켓 벽 높이", height, nh)):
                if not math.isclose(before, after, rel_tol=1e-10, abs_tol=1e-9):
                    edits.append(dict(field=f"pocket.{index}.{field}", label=label, before=before, after=after, unit="mm", cad_face_id=face_id))
                    geometric_changes.append(abs(after - before) / before)
            if corner_relief:
                edits.append(dict(field=f"pocket.{index}.corner_radius", label="포켓 내부 반경", before=0., after=diameter / 2, unit="mm", cad_face_id=face_id))
                geometric_changes.append((diameter / 2) / width)
        for field, label, before, after in (("tool_diameter_mm", "공구 지름", tool, diameter),
                                           ("flute_length_mm", "날 길이", flute, new_flute), ("reach_mm", "돌출 길이", reach, new_reach)):
            if not math.isclose(before, after, rel_tol=1e-10, abs_tol=1e-9):
                edits.append(dict(field=field, label=label, before=before, after=after, unit="mm"))
        signature = json.dumps(edits, sort_keys=True)
        if signature in seen:
            continue
        seen.add(signature)
        conflicts = []
        for d, h in after_holes:
            if _length_comparison(diameter, d)[0]: conflicts.append("구멍보다 큰 공구")
            if _length_comparison(h, new_reach)[0]: conflicts.append("원통 구간과 돌출 길이")
            if limit and h / d > limit * (1 + 1e-10): conflicts.append("구멍 길이/지름 기준")
        for radius in after_corners:
            if _length_comparison(diameter, radius * 2)[0]: conflicts.append("내부 반경보다 큰 공구")
        for width, height in after_pockets:
            if _length_comparison(diameter, width)[0]: conflicts.append("공구보다 좁은 포켓")
            if _length_comparison(height, new_flute)[0]: conflicts.append("포켓 벽 높이와 날 길이")
            if _length_comparison(height, new_reach)[0]: conflicts.append("포켓 벽 높이와 돌출 길이")
            if not corner_relief: conflicts.append("포켓 내부 직각")
        geometric = sum(geometric_changes)
        tool_change = abs(diameter - tool) / tool + abs(new_flute - flute) / flute + abs(new_reach - reach) / reach
        slender = new_reach / diameter
        metrics = dict(geometry_change=geometric / (1 + geometric), tool_change=tool_change / (1 + tool_change),
                       slenderness=slender / (1 + slender), regrets=[0., 0., 0.])
        plan_id = "cnc:" + hashlib.sha256(signature.encode()).hexdigest()[:16]
        result.append(dict(id=plan_id, family="CNC", title="현재 공구·치수 유지" if not edits else
                           "형상과 공구를 함께 조정" if geometric and tool_change else "형상 치수 조정" if geometric else "공구 조건 변경",
                           changes=edits, evidence=[f"치수 조건 충돌 {len(conflicts)}개", f"공구 돌출/지름 {reach / tool:,.3g} → {slender:,.3g}"],
                           remaining=list(dict.fromkeys(conflicts + unresolved)), outcomes=dict(remaining_numeric_conflicts=len(conflicts),
                           tool_diameter_mm=diameter, flute_length_mm=new_flute, reach_mm=new_reach, tool_reach_diameter_ratio=slender),
                           verification_scope="제안 치수·공구 조건의 수치 관계 재계산; 수정 CAD·경로는 재검토 필요", verified=True,
                           availability="필요 공구 조건 제안 · 실제 보유 공구 아님", orientation=None, keep_current=not edits,
                           covered_finding_ids=covered, remaining_finding_ids=list(dict.fromkeys((covered if conflicts else []) + unresolved_ids)),
                           _metrics=metrics, _dominance=[metrics[k] for k in ("geometry_change", "tool_change", "slenderness")],
                           _baseline=geometric + tool_change))
    # Admissible plans minimize observed conflicts before any learned preference.
    current = next((r for r in result if not r["changes"]), None)
    if current is not None and current["outcomes"]["remaining_numeric_conflicts"] == 0:
        return [current], "", current["id"]
    minimum = min(r["outcomes"]["remaining_numeric_conflicts"] for r in result)
    result = [r for r in result if r["outcomes"]["remaining_numeric_conflicts"] == minimum]
    baseline = min(result, key=lambda r: (r["_baseline"], _stable(r)))["id"]
    return result, "", baseline


def candidate_plans(report, preferences=None):
    """Public audit entry: direct measurements and explicit counterfactuals."""
    prefs = _preferences(report, preferences)
    process = _process(report)
    plans, reason, baseline = _am_candidates(report) if process in AM_FIELDS else _cnc_candidates(report, prefs) if process in ("CNC", "MILLING_3AXIS") else ([], "지원하는 공정을 선택하세요", None)
    eligible = [p for p in plans if not any(_dominates(other, p) for other in plans if other is not p)]
    if eligible and (process in ("CNC", "MILLING_3AXIS") or baseline not in {p["id"] for p in eligible}):
        baseline = min(eligible, key=lambda p: (p["_baseline"], _stable(p)))["id"]
    for plan in eligible:
        plan["_features"] = _features(plan, prefs)
    return eligible, reason, baseline


def _json(raw):
    def bad(value): raise ValueError("잘못된 JSON 숫자")
    def pairs(rows):
        result = {}
        for k, v in rows:
            if k in result: raise ValueError("중복 JSON 키")
            result[k] = v
        return result
    return json.loads(raw, parse_constant=bad, object_pairs_hook=pairs)


@lru_cache(maxsize=2)
def _read_model(path, stamp, mstamp):
    p = Path(path)
    if p.stat().st_size > 5_000_000 or p.with_suffix(".manifest.json").stat().st_size > 100_000:
        raise ValueError("모델 크기 오류")
    raw = p.read_bytes()
    model, manifest = _json(raw), _json(p.with_suffix(".manifest.json").read_bytes())
    if not isinstance(model, dict) or not isinstance(manifest, dict) or manifest.get("sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("모델 체크섬 오류")
    if model.get("schema") != SCHEMA or model.get("features") != list(FEATURES) or set(model.get("sources", {})) != set(TEACHER_SOURCES):
        raise ValueError("모델 형식 오류")
    if any(not isinstance(model.get(key), str) or not 1 <= len(model[key]) <= 2000 for key in ("id", "training_scope")):
        raise ValueError("모델 설명 형식 오류")
    trees = model.get("trees")
    if not isinstance(trees, list) or not 1 <= len(trees) <= 500:
        raise ValueError("학습 트리 수 오류")
    for key in ("intercept", "learning_rate"):
        if type(model.get(key)) not in (int, float) or not math.isfinite(model[key]) or abs(model[key]) > 1e6: raise ValueError("모델 계수 오류")
    if not 0 < model["learning_rate"] <= 1: raise ValueError("모델 학습률 오류")
    for nodes in trees:
        if not isinstance(nodes, list) or not 1 <= len(nodes) <= 1000: raise ValueError("트리 크기 오류")
        for i, row in enumerate(nodes):
            if not isinstance(row, list) or len(row) != 5: raise ValueError("트리 형식 오류")
            f, threshold, left, right, value = row
            if type(f) is not int or type(threshold) not in (int, float) or not math.isfinite(threshold) or type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e6:
                raise ValueError("트리 숫자 오류")
            if f != -2 and not (0 <= f < len(FEATURES) and type(left) is int and type(right) is int and i < left < len(nodes) and i < right < len(nodes)):
                raise ValueError("트리 순환 오류")
    model["sha256"] = manifest["sha256"]
    return model


def load_plan_model(path=None):
    p = Path(path or MODEL_PATH)
    model = _read_model(str(p.resolve()), p.stat().st_mtime_ns, p.with_suffix(".manifest.json").stat().st_mtime_ns)
    if model["sources"] != source_hashes(): raise ValueError("코드 변경 후 재학습이 필요합니다")
    return model


def predict_score(model, features):
    if len(features) != len(FEATURES) or any(not math.isfinite(v) or not 0 <= v <= 1 for v in features):
        raise ValueError("학습 입력 범위 오류")
    x = [struct.unpack("f", struct.pack("f", v))[0] for v in features]
    score = model["intercept"]
    for nodes in model["trees"]:
        index = 0
        while nodes[index][0] != -2:
            f, threshold, left, right, _ = nodes[index]
            index = left if x[f] <= threshold else right
        score += model["learning_rate"] * nodes[index][4]
    return score


def _feedback_path(path=None):
    return Path(path) if path is not None else Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "DFM" / "plan_preferences.json"


def _scope(report, preferences=None):
    p = report.get("profile") or {}
    prefs = _preferences(report, preferences)
    raw = json.dumps([_process(report), p.get("machine", ""), p.get("material", ""), prefs], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _read_feedback(path):
    if not path.exists(): return {"schema": SCHEMA, "scopes": {}}
    if path.stat().st_size > 2_000_000: raise ValueError("선호 기록 크기 오류")
    data = _json(path.read_bytes())
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("scopes"), dict): raise ValueError("선호 기록 형식 오류")
    for key, row in data["scopes"].items():
        if not isinstance(key, str) or len(key) != 64 or any(c not in "0123456789abcdef" for c in key) or not isinstance(row, dict) or type(row.get("choices")) is not int or row["choices"] < 0: raise ValueError("선호 기록 오류")
        if not isinstance(row.get("weights"), list) or len(row["weights"]) != len(FEATURES) or any(type(v) not in (float, int) or not math.isfinite(v) or abs(v) > 10 for v in row["weights"]): raise ValueError("선호 계수 오류")
        if not isinstance(row.get("pairs"), list) or len(row["pairs"]) > 300: raise ValueError("선호 표본 오류")
        for pair in row["pairs"]:
            if not isinstance(pair, list) or len(pair) != len(FEATURES) or any(type(v) not in (float, int) or not math.isfinite(v) or abs(v) > 1 for v in pair): raise ValueError("선호 표본 오류")
    return data


def _write_feedback(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as f:
        f.write(raw)
        temporary = f.name
    os.replace(temporary, path)


def recommend_plan(report, *, preferences=None, feedback_path=None, model_path=None):
    base = dict(status="unavailable", selected=None, alternatives=[], ranking=[], baseline_selected_id=None,
                selection_source="rule_fallback", selection_changed=False, model={}, learning={"choices": 0}, reason="")
    try:
        prefs = _preferences(report, preferences)
        plans, reason, baseline = candidate_plans(report, prefs)
        base.update(reason=reason, baseline_selected_id=baseline)
        if not plans: return base
        try:
            model = load_plan_model(model_path)
        except (OSError, ValueError, TypeError, KeyError, IndexError):
            model = None
        scope = _scope(report, prefs)
        try:
            feedback = _read_feedback(_feedback_path(feedback_path))["scopes"].get(scope, {})
        except (OSError, ValueError, TypeError, KeyError):
            feedback = {}
        weights = feedback.get("weights", [0.] * len(FEATURES))
        for plan in plans:
            prior = predict_score(model, plan["_features"]) if model else -plan["_baseline"]
            plan["score"] = prior + sum(w * x for w, x in zip(weights, plan["_features"]))
            plan["prior_score"] = prior
        plans.sort(key=lambda plan: (-round(float(plan["score"]), 9), _stable(plan)))
        selected = plans[0]
        if selected["family"] == "AM" and selected["keep_current"]:
            # Equivalent search directions need no physical rotation. Display
            # the resulting current orientation, while retaining the stable
            # candidate id used for ranking and explicit preference recording.
            actual = deepcopy(report.get("current_orientation") or {})
            direction = actual.get("direction") or []
            matching = next((row.get("name") for row in report.get("orientations", [])
                if len(direction) == len(row.get("direction") or []) == 3
                and all(math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-10)
                        for a, b in zip(direction, row["direction"]))), None)
            actual["name"] = matching or actual.get("name") or "현재 방향"
            selected["orientation"] = actual
        if selected["family"] == "CNC" and selected["keep_current"] and selected["outcomes"]["remaining_numeric_conflicts"] > 0:
            base["reason"] = "허용한 변경 범위에서는 충돌을 줄일 수 없습니다. 형상 또는 공구 변경을 허용하세요."
            return base
        base.update(status="keep" if selected["keep_current"] else "recommended", selected=selected,
                    alternatives=plans[1:], ranking=plans, selection_source="learned+preference" if model and feedback else "learned" if model else "rule_fallback",
                    selection_changed=selected["id"] != baseline, learning={"choices": feedback.get("choices", 0), "scope": scope},
                    model={"id": model["id"], "sha256": model["sha256"], "training_scope": model["training_scope"]} if model else {},
                    reason="" if model else "학습 모델을 사용할 수 없어 기본 비교를 사용했습니다")
        return base
    except (ValueError, TypeError, KeyError, ZeroDivisionError, OverflowError):
        base["reason"] = "추천에 필요한 형상 측정과 공구 조건을 확인하세요"
        return base


def record_plan_preference(report, chosen_id, *, preferences=None, feedback_path=None):
    """Explicit user action only; stores normalized pairs, no CAD/file content."""
    prefs = _preferences(report, preferences)
    plans, _, _ = candidate_plans(report, prefs)
    chosen = next((p for p in plans if p["id"] == chosen_id), None)
    if chosen is None: raise ValueError("현재 검증된 후보에서 선택하세요")
    differences = [[a - b for a, b in zip(chosen["_features"], other["_features"])] for other in plans if other["id"] != chosen_id]
    differences = [d for d in differences if any(abs(v) > 1e-12 for v in d)]
    if not differences: raise ValueError("동일한 후보끼리는 선호를 학습하지 않습니다")
    path = _feedback_path(feedback_path)
    data = _read_feedback(path)
    scope = _scope(report, prefs)
    old = data["scopes"].get(scope, {"choices": 0, "pairs": [], "weights": [0.] * len(FEATURES)})
    pairs = (old["pairs"] + differences)[-300:]
    weights = [0.] * len(FEATURES)
    # Regularized pairwise logistic preference fitting. Newest choices receive
    # twice the weight; bounded coefficients cannot override admissibility.
    for _ in range(100):
        for i, delta in enumerate(pairs):
            margin = sum(w * d for w, d in zip(weights, delta))
            gradient = 1 / (1 + math.exp(max(-30., min(30., margin))))
            rate = .04 * (2 if i >= len(pairs) - len(differences) else 1)
            weights = [max(-10., min(10., w + rate * (gradient * d - .01 * w))) for w, d in zip(weights, delta)]
    data["scopes"][scope] = dict(choices=old["choices"] + 1, pairs=pairs, weights=weights)
    _write_feedback(path, data)
    return {"choices": old["choices"] + 1, "scope": scope, "path": str(path)}


def reset_plan_preferences(report, *, preferences=None, feedback_path=None):
    path = _feedback_path(feedback_path)
    data = _read_feedback(path)
    removed = data["scopes"].pop(_scope(report, preferences), None)
    if removed is not None: _write_feedback(path, data)
    return {"removed_choices": (removed or {}).get("choices", 0)}


def orientation_recommendation(report, plan_result=None):
    """Existing direction-view schema, same selected plan as the conclusion."""
    from amdfm.recommendation import recommend_orientation
    base = recommend_orientation(report)
    result = plan_result or recommend_plan(report)
    plan = result.get("selected")
    if not plan or plan.get("orientation") is None: return base
    selected = deepcopy(plan["orientation"])
    selected["policy_score"] = -plan["score"]
    ranking = []
    for p in result["ranking"]:
        row = deepcopy(p["orientation"])
        row["policy_score"] = -p["score"]
        ranking.append(row)
    current = report.get("current_orientation") or {}
    differences = []
    for criterion in base.get("criteria", []):
        f = criterion["field"]
        if isinstance(current.get(f), (int, float)):
            before, after = current[f], selected[f]
            near = math.isclose(before, after, rel_tol=1e-9, abs_tol=1e-8)
            improvement = after > before if criterion["direction"] == "max" else after < before
            differences.append(dict(field=f, label=criterion["label"], unit=criterion["unit"], current=before, recommended=after,
                                    delta=after - before, change="same" if near else "improvement" if improvement else "tradeoff"))
    keep = plan["keep_current"]
    base.update(recommended=selected, ranking=ranking, alternatives=[p["orientation"] for p in result["alternatives"]],
                keep_current=keep, current_is_equivalent=keep, current_is_better=False,
                all_tied=len({round(p["score"], 9) for p in result["ranking"]}) == 1,
                action="keep" if keep else "apply", title="현재 방향을 유지하세요" if keep else f"먼저 적용할 추천 방향: {selected['name']}",
                observation="계산한 후보의 변화와 선택한 중점을 종합해 우선 적용할 방향을 선택했습니다.",
                next_action="현재 방향으로 검토를 이어가세요." if keep else f"{selected['name']} 방향을 적용하고 문제 위치를 확인하세요.",
                current_comparison=dict(status="equivalent" if keep else "candidate_improves", keep_current=keep,
                                        is_equivalent=all(d["change"] == "same" for d in differences), is_better=False, differences=differences))
    base["policy"] = dict(base.get("policy", {}), version=SCHEMA, selection_source=result["selection_source"], model_sha256=result["model"].get("sha256"),
                          score_meaning="learned plan preference, after verified constraints and Pareto filtering; not original equal-regret score")
    return base
