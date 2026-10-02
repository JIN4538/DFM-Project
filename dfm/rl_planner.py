"""Sequential CNC dimension proposals from a masked, action-conditioned DQN.

The network proposes a sequence. Every transition and the final proposal are
re-evaluated with the same dimensional comparison as the CNC geometry engine.
No CAD is edited here. The state contains measured analytic feature dimensions,
not meshes, toolpaths or invented measurements. Training lives in scripts/.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

import numpy as np

SCHEMA = "cnc-sequential-ddqn-v1"
MODEL_PATH = Path(__file__).resolve().parents[1] / "data/models/rl_planner_v1.json"
MAX_FEATURES = 64
MAX_STEPS = 24
ACTION_KINDS = ("stop", "tool", "flute", "reach", "hole_diameter", "hole_depth", "corner_radius", "pocket_width", "pocket_depth", "pocket_radius")
STATE_FEATURES = 25
FEATURE_COUNT = STATE_FEATURES * 2 + len(ACTION_KINDS) + 4
GEOMETRY_KINDS = set(ACTION_KINDS[4:])


def _positive(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError("유한한 양의 치수가 필요합니다")
    return float(value)


def make_problem(report, preferences=None):
    """Read only CNC inputs already supported by the analytic feature checker."""
    from .plan_learning import _cnc_inputs, _cnc_pocket_rows, _preferences
    process = report.get("process", (report.get("profile") or {}).get("process"))
    if process not in ("CNC", "MILLING_3AXIS"):
        raise ValueError("절삭 치수 검토 결과가 필요합니다")
    p, holes, corners, pockets, unresolved, unresolved_ids = _cnc_inputs(report)
    if not holes and not corners and not pockets:
        raise ValueError("공구와 비교할 원통·포켓 치수가 없습니다")
    if len(holes) + len(corners) + len(pockets) > MAX_FEATURES:
        raise ValueError(f"순차 개선안은 측정 특징 {MAX_FEATURES}개까지 검토합니다")
    state = dict(tool=_positive(p["tool_diameter_mm"]), flute=_positive(p["flute_length_mm"]), reach=_positive(p["reach_mm"]),
                 holes=[dict(diameter=d, depth=h, index=i, cad_face_id=f) for d, h, i, f in holes],
                 corners=[dict(radius=r, index=i, cad_face_id=f) for r, i, f in corners],
                 pockets=[dict(width=w, depth=h, radius=0., index=i, cad_face_id=f,
                     finding_id=_cnc_pocket_rows(report)[i]['finding_id'],
                     width_label=_cnc_pocket_rows(report)[i]['planning_width_label']) for w, h, i, f in pockets])
    limit = p.get("hole_depth_ratio_limit")
    if limit is not None:
        limit = _positive(limit)
    dimensions = [state[k] for k in ("tool", "flute", "reach")]
    dimensions += [r[k] for r in state["holes"] for k in ("diameter", "depth")]
    dimensions += [r["radius"] for r in state["corners"]]
    dimensions += [r[k] for r in state["pockets"] for k in ("width", "depth")]
    if limit is not None:
        dimensions.append(limit)
    if not math.isfinite(max(dimensions) / min(dimensions)):
        raise ValueError("치수 비율이 유한한 계산 범위를 벗어났습니다")
    prefs = _preferences(report, preferences)
    return dict(initial=state, preferences=prefs, ratio_limit=limit, unresolved=unresolved, unresolved_ids=unresolved_ids,
                total_checks=len(holes) * (2 + int(limit is not None)) + len(corners) + 4 * len(pockets))


def conflicts(problem, state):
    """Exact dimensional checks; stable IDs prevent same-text deduplication loss."""
    from .machining import _length_comparison
    rows = []
    def add(bad, finding, code, label, row):
        if bad:
            rows.append(dict(finding_id=finding, code=code, label=label, index=row["index"], cad_face_id=row["cad_face_id"]))
    tool, flute, reach = (state[k] for k in ("tool", "flute", "reach"))
    for row in state["holes"]:
        add(_length_comparison(tool, row["diameter"])[0], "cnc_holes", "hole_tool", "구멍보다 큰 공구", row)
        add(_length_comparison(row["depth"], reach)[0], "cnc_holes", "hole_reach", "원통 구간과 돌출 길이", row)
        limit = problem["ratio_limit"]
        add(limit is not None and row["depth"] / row["diameter"] > limit * (1 + 1e-10), "cnc_holes", "hole_ratio", "구멍 길이/지름 기준", row)
    for row in state["corners"]:
        add(_length_comparison(tool, 2 * row["radius"])[0], "cnc_curved_corners", "corner_tool", "내부 반경보다 큰 공구", row)
    for row in state["pockets"]:
        finding = row.get('finding_id', 'cnc_rectangular_pockets')
        add(_length_comparison(tool, row["width"])[0], finding, "pocket_tool", "공구보다 좁은 포켓", row)
        add(_length_comparison(row["depth"], flute)[0], finding, "pocket_flute", "포켓 벽 높이와 날 길이", row)
        add(_length_comparison(row["depth"], reach)[0], finding, "pocket_reach", "포켓 벽 높이와 돌출 길이", row)
        add(_length_comparison(tool / 2, row["radius"])[0], finding, "pocket_corner", "포켓 내부 직각" if row["radius"] == 0 else "포켓 반경보다 큰 공구", row)
    return rows


def edits(problem, state):
    rows = []
    def emit(field, label, before, after, cad_face_id=None):
        if not math.isclose(before, after, rel_tol=1e-10, abs_tol=1e-9):
            row = dict(field=field, label=label, before=before, after=after, unit="mm")
            if cad_face_id is not None:
                row["cad_face_id"] = cad_face_id
            rows.append(row)
    original = problem["initial"]
    for key, field, label in (("tool", "tool_diameter_mm", "공구 지름"), ("flute", "flute_length_mm", "날 길이"), ("reach", "reach_mm", "돌출 길이")):
        emit(field, label, original[key], state[key])
    groups = (("holes", "hole", (("diameter", "diameter", "구멍 지름"), ("depth", "segment", "원통 구간"))),
              ("corners", "corner", (("radius", "radius", "내부 반경"),)),
              ("pockets", "pocket", (("width", "width", "포켓 폭"), ("depth", "wall", "포켓 벽 높이"), ("radius", "corner_radius", "포켓 내부 반경"))))
    for group, prefix, fields in groups:
        for before, after in zip(original[group], state[group]):
            for key, field, label in fields:
                if prefix == 'pocket' and field == 'width':
                    label = before.get('width_label', label)
                emit(f"{prefix}.{before['index']}.{field}", label, before[key], after[key], before["cad_face_id"])
    return rows


def metrics(problem, state):
    change = edits(problem, state)
    g, t = 0., 0.
    for row in change:
        if ".corner_radius" in row["field"]:
            index = int(row["field"].split(".")[1])
            width = next(r["width"] for r in problem["initial"]["pockets"] if r["index"] == index)
            g += row["after"] / width
        elif "." in row["field"]:
            g += abs(row["after"] - row["before"]) / row["before"]
        else:
            t += abs(row["after"] - row["before"]) / row["before"]
    slender = state["reach"] / state["tool"]
    if not all(math.isfinite(value) for value in (g, t, slender)):
        raise ValueError("변경 치수의 비율이 유한한 계산 범위를 벗어났습니다")
    return dict(geometry_change=g / (1 + g), tool_change=t / (1 + t), slenderness=slender / (1 + slender),
                regrets=[0., 0., 0.], edit_count=len(change), raw_geometry_change=g, raw_tool_change=t)


def plan_cost(problem, state):
    """Disclosed project edit policy, matching the prior CNC plan objective."""
    m = metrics(problem, state)
    priority = problem["preferences"]["priority"]
    weights = (4., 1., 1.5) if priority == "accuracy" else (1., 1., 3.) if priority == "tool_access" else (2., 1., 2.)
    g, t, slender = (m[k] for k in ("geometry_change", "tool_change", "slenderness"))
    a, b, c = (x * w for x, w in zip((g, t, slender), weights))
    return .5 * max(a, b, c) / max(weights) + .35 * (a + b + c) / sum(weights) + .1 * g * slender + .05 * min(1., m["edit_count"] / 8)


def quality(problem, state):
    return len(conflicts(problem, state)), round(plan_cost(problem, state), 12)


def action_space(problem, state):
    """Variable actions, masked by locks and positive/flute<=reach contracts."""
    actions = [dict(kind="stop", index=-1, value=0.)]
    prefs = problem["preferences"]
    def add(kind, index, value, current):
        if math.isfinite(value) and value > 0 and not math.isclose(value, current, rel_tol=1e-10, abs_tol=1e-9):
            actions.append(dict(kind=kind, index=index, value=float(value)))
    if prefs["allow_tool_change"]:
        openings = [r["diameter"] for r in state["holes"]] + [2 * r["radius"] for r in state["corners"]] + [r["width"] for r in state["pockets"]]
        for value in sorted(set(v for v in openings if v < state["tool"])):
            add("tool", -1, value, state["tool"])
        for value in sorted(set(r["depth"] for r in state["holes"] + state["pockets"] if r["depth"] > state["reach"])):
            add("reach", -1, value, state["reach"])
        for value in sorted(set(r["depth"] for r in state["pockets"] if state["flute"] < r["depth"] <= state["reach"])):
            add("flute", -1, value, state["flute"])
    if not prefs["preserve_geometry"]:
        for i, row in enumerate(state["holes"]):
            targets = [state["tool"]]
            if problem["ratio_limit"]:
                targets.append(row["depth"] / problem["ratio_limit"])
            for value in sorted(set(v for v in targets if v > row["diameter"])):
                add("hole_diameter", i, value, row["diameter"])
            target = min(state["reach"], problem["ratio_limit"] * row["diameter"] if problem["ratio_limit"] else row["depth"])
            if target < row["depth"]:
                add("hole_depth", i, target, row["depth"])
        for i, row in enumerate(state["corners"]):
            if state["tool"] / 2 > row["radius"]:
                add("corner_radius", i, state["tool"] / 2, row["radius"])
        for i, row in enumerate(state["pockets"]):
            if state["tool"] > row["width"]:
                add("pocket_width", i, state["tool"], row["width"])
            if min(state["flute"], state["reach"]) < row["depth"]:
                add("pocket_depth", i, min(state["flute"], state["reach"]), row["depth"])
            if state["tool"] / 2 > row["radius"]:
                # A circular corner radius cannot exceed half this local pocket width.
                if state["tool"] <= row["width"]:
                    add("pocket_radius", i, state["tool"] / 2, row["radius"])
    return actions


def transition(problem, state, action):
    if action not in action_space(problem, state):
        raise ValueError("현재 조건에서 허용되지 않는 수정 단계입니다")
    result = deepcopy(state)
    kind = action["kind"]
    if kind in ("tool", "flute", "reach"):
        result[kind] = action["value"]
    elif kind != "stop":
        group, field = dict(hole_diameter=("holes", "diameter"), hole_depth=("holes", "depth"), corner_radius=("corners", "radius"),
                           pocket_width=("pockets", "width"), pocket_depth=("pockets", "depth"), pocket_radius=("pockets", "radius"))[kind]
        result[group][action["index"]][field] = action["value"]
    if result["flute"] > result["reach"]:
        raise ValueError("날 길이가 돌출 길이를 초과합니다")
    reward = 2. * (len(conflicts(problem, state)) - len(conflicts(problem, result))) - (plan_cost(problem, result) - plan_cost(problem, state))
    return result, float(reward), kind == "stop"


def state_vector(problem, state, remaining_steps):
    counts = conflicts(problem, state)
    codes = ("hole_tool", "hole_reach", "hole_ratio", "corner_tool", "pocket_tool", "pocket_flute", "pocket_reach", "pocket_corner")
    n = max(1, len(state["holes"]) + len(state["corners"]) + len(state["pockets"]))
    m = metrics(problem, state)
    def bounded(x):
        return x / (1 + x)
    vals = [len(counts) / max(1, problem["total_checks"])] + [sum(r["code"] == c for r in counts) / n for c in codes]
    vals += [m[k] for k in ("geometry_change", "tool_change", "slenderness")]
    vals += [len(state[k]) / n for k in ("holes", "corners", "pockets")]
    vals += [bounded(state["flute"] / state["tool"]), bounded(state["reach"] / state["flute"]), bounded(problem["ratio_limit"] or 0.), min(1., remaining_steps / MAX_STEPS)]
    vals += [float(problem["preferences"][k]) for k in ("preserve_geometry", "allow_tool_change")]
    vals += [float(problem["preferences"]["priority"] == p) for p in ("balanced", "accuracy", "tool_access")]
    vals += [min(n, MAX_FEATURES) / MAX_FEATURES]
    assert len(vals) == STATE_FEATURES
    return vals


def action_vectors(problem, state, actions, remaining_steps):
    before = state_vector(problem, state, remaining_steps)
    rows = []
    for action in actions:
        after, reward, _ = transition(problem, state, action)
        delta = edits(dict(problem, initial=state), after)
        relative = sum(abs(r["after"] - r["before"]) / max(state["tool"], r["before"]) for r in delta)
        rows.append(before + state_vector(problem, after, max(0, remaining_steps - 1)) + [float(action["kind"] == k) for k in ACTION_KINDS] +
                    [relative / (1 + relative), reward / max(2., 2 * problem["total_checks"]), float(action["kind"] == "stop"), plan_cost(problem, after)])
    return np.asarray(rows, dtype=np.float64)


def network_predict(model, x):
    value = np.asarray(x, dtype=np.float64)
    for i, layer in enumerate(model["layers"]):
        value = value @ np.asarray(layer["weights"], dtype=np.float64) + np.asarray(layer["bias"], dtype=np.float64)
        if i < len(model["layers"]) - 1:
            value = np.maximum(value, 0.)
    return value.reshape(-1)


def _source_hash():
    files = (Path(__file__), Path(__file__).with_name("machining.py"), Path(__file__).with_name("plan_learning.py"))
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


@lru_cache(maxsize=4)
def _load_model(path, stamp, size, manifest_stamp, manifest_size, source_sha):
    raw = Path(path).read_bytes()
    model = json.loads(raw)
    manifest = json.loads(Path(path).with_suffix(".manifest.json").read_text(encoding="utf-8"))
    raw_sha = hashlib.sha256(raw).hexdigest()
    if manifest.get("model_sha256") != raw_sha or manifest.get("source_sha256") != source_sha:
        raise ValueError("강화학습 모델의 검증 해시가 일치하지 않습니다")
    if model.get("schema") != SCHEMA or model.get("feature_count") != FEATURE_COUNT or model.get("source_sha256") != source_sha:
        raise ValueError("강화학습 모델과 현재 계획 규칙이 일치하지 않습니다")
    layers = model.get("layers", [])
    if len(layers) < 3 or len(layers) > 5:
        raise ValueError("강화학습 모델 구조가 잘못되었습니다")
    expected = FEATURE_COUNT
    for layer in layers:
        weight, bias = np.asarray(layer["weights"], dtype=float), np.asarray(layer["bias"], dtype=float)
        if weight.ndim != 2 or weight.shape[0] != expected or bias.shape != (weight.shape[1],) or not np.isfinite(weight).all() or not np.isfinite(bias).all():
            raise ValueError("강화학습 모델 가중치가 잘못되었습니다")
        expected = weight.shape[1]
    if expected != 1:
        raise ValueError("강화학습 출력이 잘못되었습니다")
    model["sha256"] = raw_sha
    return model


def load_model(path=None):
    path = Path(path or MODEL_PATH)
    manifest = path.with_suffix(".manifest.json")
    if path.stat().st_size > 5_000_000 or manifest.stat().st_size > 1_000_000:
        raise ValueError("강화학습 모델 파일이 너무 큽니다")
    return _load_model(str(path.resolve()), path.stat().st_mtime_ns, path.stat().st_size,
                       manifest.stat().st_mtime_ns, manifest.stat().st_size, _source_hash())


def rollout(problem, model=None, *, policy="dqn", max_steps=MAX_STEPS, rng=None):
    state = deepcopy(problem["initial"])
    steps = []
    best, best_steps = deepcopy(state), []
    for index in range(max_steps):
        choices = action_space(problem, state)
        if len(choices) <= 1:
            break
        if policy == "greedy":
            qualities = [quality(problem, transition(problem, state, a)[0]) for a in choices]
            chosen = min(range(len(choices)), key=lambda i: (qualities[i], i))
        elif policy == "random":
            if rng is None:
                raise ValueError("난수 생성기가 필요합니다")
            chosen = int(rng.integers(len(choices)))
        else:
            scores = network_predict(model, action_vectors(problem, state, choices, max_steps - index))
            if not np.isfinite(scores).all():
                raise ValueError("강화학습 점수가 유한하지 않습니다")
            chosen = int(np.argmax(scores))
        action = choices[chosen]
        after, reward, done = transition(problem, state, action)
        if done:
            break
        step_changes = edits(dict(problem, initial=state), after)
        steps.append(dict(number=index + 1, action=action, changes=step_changes,
                          conflicts_before=len(conflicts(problem, state)), conflicts_after=len(conflicts(problem, after)), reward=reward))
        state = after
        if quality(problem, state) < quality(problem, best):
            best, best_steps = deepcopy(state), deepcopy(steps)
    return best, best_steps


def plan_from_state(problem, state, steps):
    conflict_rows = conflicts(problem, state)
    m = metrics(problem, state)
    changes = edits(problem, state)
    covered = [key for key, group in (("cnc_holes", "holes"), ("cnc_curved_corners", "corners")) if state[group]]
    covered += list(dict.fromkeys(row.get('finding_id', 'cnc_rectangular_pockets') for row in state['pockets']))
    remaining_ids = list(dict.fromkeys([r["finding_id"] for r in conflict_rows] + problem["unresolved_ids"]))
    remaining = list(dict.fromkeys([r["label"] for r in conflict_rows] + problem["unresolved"]))
    return dict(id="cnc-rl:" + hashlib.sha256(json.dumps(changes, sort_keys=True).encode()).hexdigest()[:16], family="CNC",
                title="현재 공구·치수 유지" if not changes else "특징별 형상·공구 순차 개선안" if m["raw_tool_change"] and m["raw_geometry_change"] else "특징별 형상 개선안" if m["raw_geometry_change"] else "공구 조건 변경",
                changes=changes, steps=steps, evidence=[f"치수 조건 충돌 {len(conflicts(problem, problem['initial']))} → {len(conflict_rows)}개", f"강화학습 {len(steps)}단계 수정 제안·수치 재검산"],
                remaining=remaining, remaining_finding_ids=remaining_ids, covered_finding_ids=covered,
                outcomes=dict(remaining_numeric_conflicts=len(conflict_rows), tool_diameter_mm=state["tool"], flute_length_mm=state["flute"], reach_mm=state["reach"], tool_reach_diameter_ratio=state["reach"] / state["tool"]),
                verification_scope="수정 단계별 치수·공구 관계 재계산; 원본 CAD는 변경하지 않음", verified=True,
                availability="필요 공구 조건 제안", orientation=None, keep_current=not changes,
                _metrics=m, _dominance=[m[k] for k in ("geometry_change", "tool_change", "slenderness")],
                _baseline=m["raw_geometry_change"] + m["raw_tool_change"], planning_cost=plan_cost(problem, state),
                engine="deep_double_q_learning", conflict_details=conflict_rows)


def evaluate_changes(report, changes, *, preferences=None):
    """Independently recheck a candidate's explicit changes, including locks.

    Used by arbitration to compare old and learned plans on the same objective.
    A plan cannot smuggle in different starting dimensions, thresholds or faces.
    """
    problem = make_problem(report, preferences)
    state = deepcopy(problem["initial"])
    aliases = {"tool_diameter_mm": "tool", "flute_length_mm": "flute", "reach_mm": "reach"}
    groups = {"hole": ("holes", {"diameter": "diameter", "segment": "depth"}),
              "corner": ("corners", {"radius": "radius"}),
              "pocket": ("pockets", {"width": "width", "wall": "depth", "corner_radius": "radius"})}
    seen = set()
    for change in changes:
        field = change["field"]
        if field in seen:
            raise ValueError("동일 치수의 중복 변경입니다")
        seen.add(field)
        value = _positive(change["after"])
        if field in aliases:
            if not problem["preferences"]["allow_tool_change"]:
                raise ValueError("공구 유지 조건을 위반한 제안입니다")
            target, key = state, aliases[field]
        else:
            if problem["preferences"]["preserve_geometry"]:
                raise ValueError("형상 유지 조건을 위반한 제안입니다")
            prefix, index, name = field.split(".")
            group, names = groups[prefix]
            target = next((r for r in state[group] if r["index"] == int(index)), None)
            if target is None:
                raise ValueError("측정되지 않은 특징의 변경입니다")
            if change.get("cad_face_id") != target["cad_face_id"]:
                raise ValueError("변경안의 CAD 면이 측정값과 다릅니다")
            key = names[name]
        if not math.isclose(float(change["before"]), target[key], rel_tol=1e-10, abs_tol=1e-9):
            raise ValueError("변경 전 치수가 원래 측정값과 다릅니다")
        target[key] = value
    if state["flute"] > state["reach"]:
        raise ValueError("날 길이가 돌출 길이를 초과합니다")
    if any(r["radius"] > r["width"] / 2 + 1e-9 for r in state["pockets"]):
        raise ValueError("제안 반경이 포켓 폭의 절반보다 큽니다")
    plan = plan_from_state(problem, state, [])
    return dict(conflicts=plan["outcomes"]["remaining_numeric_conflicts"], cost=plan["planning_cost"], plan=plan)


def propose_rl_plan(report, *, preferences=None, model_path=None):
    """Return an exactly rechecked proposal. No report or CAD is mutated."""
    try:
        problem = make_problem(report, preferences)
        model = load_model(model_path)
        state, steps = rollout(problem, model)
        plan = plan_from_state(problem, state, steps)
        return dict(status="proposed" if steps else "keep", proposal=plan,
                    model={k: model.get(k) for k in ("schema", "sha256", "training", "validation")},
                    initial_conflicts=len(conflicts(problem, problem["initial"])), policy="masked_double_dqn",
                    scope="기존에 측정된 원통·반경·포켓 치수의 순차 개선 계획")
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as error:
        return dict(status="unavailable", proposal=None, reason=str(error))
