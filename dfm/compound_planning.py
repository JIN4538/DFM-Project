"""Learned tool-combination proposals with exact feature-specific completion.

The model estimates which measured tool thresholds deserve an exact search.
For each proposed tool combination, dynamic programming retains nondominated
geometry-change/edit-count choices. The unchanged CNC checker verifies the
result. Targets are dimensional design suggestions; CAD is not regenerated.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import hashlib
import itertools
import json
import math
from pathlib import Path
import time

import numpy as np

from . import rl_planner as env

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT/'data/models/compound_planner_v1.json'
SCHEMA = 'cnc-compound-tool-proposal-v1'
MAX_CONFIGURATIONS = 4096
EXACT_THRESHOLD = 64  # Selected using run-01 validation timing, before test access.
FEATURES = ('tool_ratio', 'flute_ratio', 'reach_ratio', 'tool_change', 'slenderness',
    'hole_count', 'corner_count', 'pocket_count', 'ratio_limit', 'geometry_locked',
    'priority_accuracy', 'priority_access', 'hole_tool_fraction', 'hole_depth_fraction',
    'hole_ratio_fraction', 'hole_opening_mean', 'hole_opening_max', 'hole_depth_mean',
    'hole_depth_max', 'corner_change_mean', 'corner_change_max', 'pocket_width_mean',
    'pocket_width_max', 'pocket_depth_mean', 'pocket_depth_max', 'pocket_radius_mean',
    'pocket_radius_max', 'hole_opening_std', 'hole_depth_std', 'hole_mixed_advantage')


def source_hashes():
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
            ('dfm/compound_planning.py', 'dfm/rl_planner.py', 'dfm/plan_learning.py', 'dfm/machining.py')}


def _domains(problem):
    initial = problem['initial']
    original = tuple(initial[k] for k in ('tool', 'flute', 'reach'))
    if not problem['preferences']['allow_tool_change']:
        return ([original[0]], [original[1]], [original[2]])
    openings = [r['diameter'] for r in initial['holes']] + [2*r['radius'] for r in initial['corners']]
    openings += [r['width'] for r in initial['pockets']]
    diameters = sorted(set([original[0]] + [v for v in openings if 0 < v < original[0]]))
    flutes = sorted(set([original[1]] + [r['depth'] for r in initial['pockets'] if r['depth'] > original[1]]))
    reaches = sorted(set([original[2]] + [r['depth'] for r in initial['holes'] + initial['pockets']
                                        if r['depth'] > original[2]]))
    return diameters, flutes, reaches


def tool_configurations(problem):
    """Finite measured thresholds, using the existing monotone tool actions."""
    diameters, flutes, reaches = _domains(problem)
    original = tuple(problem['initial'][k] for k in ('tool', 'flute', 'reach'))
    count = len(diameters)*sum(f <= r for f in flutes for r in reaches)
    if count > MAX_CONFIGURATIONS:
        raise ValueError(f'복합 개선안의 공구 조합이 {MAX_CONFIGURATIONS}개를 초과합니다')
    return sorted(((d, f, r) for d, f, r in itertools.product(diameters, flutes, reaches) if f <= r),
                  key=lambda c: (c != original, sum(abs(v-o)/o for v, o in zip(c, original)), c))


def _options(problem, group, row, configuration):
    tool, flute, reach = configuration
    def option(**updates):
        changed = {k: v for k, v in updates.items() if not math.isclose(v, row[k], rel_tol=1e-10, abs_tol=1e-9)}
        amount = sum(abs(v-row[k])/(row['width'] if k == 'radius' and group == 'pockets' else row[k])
                     for k, v in changed.items())
        return dict(row, **changed), amount, len(changed)
    if problem['preferences']['preserve_geometry']:
        return [(dict(row), 0., 0)]
    if group == 'corners':
        radius = max(row['radius'], tool/2)
        return [option(radius=radius)]
    if group == 'pockets':
        width, depth = max(row['width'], tool), min(row['depth'], flute, reach)
        return [option(width=width, depth=depth, radius=tool/2)]
    ratio = problem['ratio_limit']
    diameters = {max(row['diameter'], tool)}
    if ratio:
        diameters.update((max(row['diameter'], tool, row['depth']/ratio),
                          max(row['diameter'], tool, min(row['depth'], reach)/ratio)))
    options = []
    for diameter in sorted(diameters):
        depth = min(row['depth'], reach, ratio*diameter if ratio else row['depth'])
        options.append(option(diameter=diameter, depth=depth))
    return options


def complete_configuration(problem, configuration):
    """Exact minimum policy cost over feature threshold options for one tool.

    Geometry change is additive before its monotone bounding transform; the
    cost also depends on the edit count capped at eight. Retaining the least
    change for each capped count therefore preserves the optimum in this
    declared discrete family. It is not a continuous CAD optimum.
    """
    original = problem['initial']
    if len(configuration) != 3 or any(type(v) not in (int,float) or not math.isfinite(v) or v <= 0 for v in configuration) or not all(v in domain for v, domain in zip(configuration, _domains(problem))) or configuration[1] > configuration[2]:
        raise ValueError('측정한 공구 치수 후보에서 선택하세요')
    initial_state = deepcopy(original)
    initial_state.update(zip(('tool', 'flute', 'reach'), configuration))
    tool_count = sum(not math.isclose(value, original[key], rel_tol=1e-10, abs_tol=1e-9)
                     for key, value in zip(('tool', 'flute', 'reach'), configuration))
    frontier = {min(8, tool_count): (0., initial_state)}
    for group in ('holes', 'corners', 'pockets'):
        for index, row in enumerate(original[group]):
            updated = {}
            for count, (amount, state) in frontier.items():
                for option, extra, changes in _options(problem, group, row, configuration):
                    new_count, new_amount = min(8, count+changes), amount+extra
                    if new_count not in updated or new_amount < updated[new_count][0]:
                        candidate = deepcopy(state)
                        candidate[group][index] = option
                        updated[new_count] = (new_amount, candidate)
            frontier = {count: value for count, value in updated.items() if not any(
                other < count and alternative[0] <= value[0] for other, alternative in updated.items())}
    return min((v[1] for v in frontier.values()), key=lambda state: env.quality(problem, state))


def configuration_features(problem, configuration):
    initial = problem['initial']
    tool, flute, reach = configuration
    bounded = lambda v: v/(1+v)
    avg = lambda vals: float(np.mean(vals)) if vals else 0.
    peak = lambda vals: max(vals, default=0.)
    hole_open, hole_depth = [], []
    hole_tool = hole_reach = hole_ratio = 0
    ratio = problem['ratio_limit']
    for row in initial['holes']:
        diameter, depth = row['diameter'], row['depth']
        hole_open.append(max(0., max(tool, depth/ratio if ratio else 0.)/diameter-1))
        hole_depth.append(max(0., 1-min(reach, ratio*max(tool, diameter) if ratio else depth)/depth))
        hole_tool += tool > diameter
        hole_reach += depth > reach
        hole_ratio += bool(ratio and depth > diameter*ratio)
    corners = [max(0., tool/(2*r['radius'])-1) for r in initial['corners']]
    pocket_width = [max(0., tool/r['width']-1) for r in initial['pockets']]
    pocket_depth = [max(0., 1-min(flute, reach)/r['depth']) for r in initial['pockets']]
    pocket_radius = [tool/(2*r['width']) for r in initial['pockets']]
    count = max(1, len(initial['holes']))
    preferences = problem['preferences']
    values = [bounded(tool/initial['tool']), bounded(flute/initial['flute']), bounded(reach/initial['reach']),
        bounded(sum(abs(v-initial[k])/initial[k] for v, k in zip(configuration, ('tool', 'flute', 'reach')))),
        bounded(reach/tool), *(bounded(len(initial[k])) for k in ('holes', 'corners', 'pockets')),
        bounded(ratio or 0.), float(preferences['preserve_geometry']),
        float(preferences['priority']=='accuracy'), float(preferences['priority']=='tool_access'),
        hole_tool/count, hole_reach/count, hole_ratio/count]
    for values_for_feature in (hole_open, hole_depth, corners, pocket_width, pocket_depth, pocket_radius):
        values += [bounded(avg(values_for_feature)), bounded(peak(values_for_feature))]
    values += [bounded(float(np.std(hole_open)) if hole_open else 0.),
               bounded(float(np.std(hole_depth)) if hole_depth else 0.),
               bounded(min(sum(hole_open), sum(hole_depth))-sum(min(a,b) for a,b in zip(hole_open,hole_depth)))]
    if len(values) != len(FEATURES) or not np.isfinite(values).all():
        raise ValueError('복합 계획의 학습 입력이 올바르지 않습니다')
    return values


def predict(model, features):
    x = np.asarray(features, dtype=np.float64)
    if x.ndim != 2 or x.shape[1] != len(FEATURES) or not np.isfinite(x).all():
        raise ValueError('복합 계획 입력 형태를 확인하세요')
    # Match scikit-learn tree routing, which casts input rows to float32.
    x = x.astype(np.float32)
    answer = np.full(len(x), model['intercept'], dtype=float)
    for tree in model['trees']:
        nodes = np.asarray(tree)
        index = np.zeros(len(x), dtype=int)
        for _ in range(40):
            active = nodes[index, 0] >= 0
            if not active.any():
                break
            row_ids = np.flatnonzero(active)
            branch = nodes[index[row_ids]]
            go_left = x[row_ids, branch[:,0].astype(int)] <= branch[:,1]
            index[row_ids] = np.where(go_left, branch[:,2], branch[:,3]).astype(int)
        else:
            raise ValueError('복합 계획 모델의 트리 깊이가 올바르지 않습니다')
        answer += model['learning_rate']*nodes[index,4]
    return answer


@lru_cache(maxsize=4)
def _load(path, stamp, manifest_stamp, sources):
    raw = Path(path).read_bytes()
    manifest = json.loads(Path(path).with_suffix('.manifest.json').read_text(encoding='utf8'))
    model = json.loads(raw)
    digest = hashlib.sha256(raw).hexdigest()
    if manifest.get('sha256') != digest or model.get('sources') != dict(sources):
        raise ValueError('복합 계획 모델의 검증 계약이 일치하지 않습니다')
    if model.get('schema') != SCHEMA or model.get('features') != list(FEATURES):
        raise ValueError('복합 계획 모델의 입력 계약이 다릅니다')
    if not 1 <= len(model.get('trees', [])) <= 400:
        raise ValueError('복합 계획 모델의 크기가 올바르지 않습니다')
    if any(type(model.get(k)) not in (int,float) or not math.isfinite(model[k]) for k in ('intercept','learning_rate')) or model['learning_rate'] <= 0:
        raise ValueError('복합 계획 모델의 계수가 올바르지 않습니다')
    for tree in model['trees']:
        nodes = np.asarray(tree, dtype=float)
        if nodes.ndim != 2 or nodes.shape[1] != 5 or len(nodes) > 32767 or not np.isfinite(nodes).all():
            raise ValueError('복합 계획 모델의 트리가 올바르지 않습니다')
        for index, (feature, threshold, left, right, value) in enumerate(nodes):
            if feature == -2:
                continue
            if feature != int(feature) or not 0 <= feature < len(FEATURES) or not all(
                child == int(child) and index < child < len(nodes) for child in (left, right)):
                raise ValueError('복합 계획 모델의 노드가 올바르지 않습니다')
    model['sha256'] = digest
    return model


def load_model(path=None):
    path = Path(path or MODEL_PATH)
    manifest = path.with_suffix('.manifest.json')
    if path.stat().st_size > 8_000_000 or manifest.stat().st_size > 1_000_000:
        raise ValueError('복합 계획 모델 파일이 너무 큽니다')
    return _load(str(path.resolve()), path.stat().st_mtime_ns, manifest.stat().st_mtime_ns,
                 tuple(sorted(source_hashes().items())))


def search(problem, *, model=None, policy='learned', budget=8, seed=0):
    configurations = tool_configurations(problem)
    requested_policy = policy
    if policy == 'hybrid':
        policy = 'all' if len(configurations) <= EXACT_THRESHOLD else 'learned'
    if policy == 'all':
        chosen = list(range(len(configurations)))
    elif policy == 'random':
        chosen = list(np.random.default_rng(seed).permutation(len(configurations)))[:budget]
    elif policy == 'greedy':
        # Same proposal budget; a cheap one-step conflict/cost score before
        # feature-specific completion. No lookahead or learned model.
        keys = []
        for config in configurations:
            state = deepcopy(problem['initial'])
            state.update(zip(('tool','flute','reach'), config))
            keys.append(env.quality(problem, state))
        chosen = sorted(range(len(configurations)), key=lambda i: (keys[i], i))[:budget]
    else:
        features = [configuration_features(problem, c) for c in configurations]
        scores = predict(model, features)
        if not np.isfinite(scores).all():
            raise ValueError('복합 계획 예측값이 유한하지 않습니다')
        chosen = sorted(range(len(configurations)), key=lambda i: (scores[i], i))[:budget]
    if not chosen:
        raise ValueError('복합 계획 탐색 예산은 양수여야 합니다')
    best, best_index = None, None
    for index in chosen:
        state = complete_configuration(problem, configurations[index])
        if best is None or env.quality(problem, state) < env.quality(problem, best):
            best, best_index = state, index
    return best, dict(policy=policy, requested_policy=requested_policy, used_learning=policy=='learned',
                      configuration_count=len(configurations), evaluated_count=len(chosen),
                      chosen_configuration=list(configurations[best_index]), candidate_indices=[int(i) for i in chosen])


def propose_compound_plan(report, *, preferences=None, model_path=None, budget=8):
    started = time.monotonic()
    try:
        if type(budget) is not int or not 1 <= budget <= 64:
            raise ValueError('복합 계획 탐색 예산은 1–64개입니다')
        problem = env.make_problem(report, preferences)
        model = load_model(model_path)
        state, audit = search(problem, model=model, policy='hybrid', budget=budget)
        checked = env.evaluate_changes(report, env.edits(problem, state), preferences=preferences)
        plan = checked['plan']
        plan['id'] = 'cnc-compound:' + plan['id'].split(':',1)[1]
        plan['engine'] = ('learned_tool_proposals_exact_feature_completion' if audit['used_learning']
                          else 'exact_compound_feature_completion')
        plan['title'] = '현재 공구·치수 유지' if plan['keep_current'] else '부위별 형상·공구 조합 개선안'
        plan['evidence'] = [f"치수 조건 충돌 {len(env.conflicts(problem, problem['initial']))} → {checked['conflicts']}개",
                            f"{'학습 제안 ' if audit['used_learning'] else ''}공구 조합 {audit['evaluated_count']}개·특징별 치수 재검산"]
        return dict(status='keep' if plan['keep_current'] else 'proposed', proposal=plan,
                    model=dict(schema=SCHEMA, sha256=model['sha256']), search=audit,
                    seconds=time.monotonic()-started, policy='learned bounded proposals; exact feature completion')
    except (OSError, ValueError, KeyError, TypeError, OverflowError, IndexError) as error:
        return dict(status='unavailable', proposal=None, reason=str(error), seconds=time.monotonic()-started)
