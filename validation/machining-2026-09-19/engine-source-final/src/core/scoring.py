"""평가 결과 관리 및 빌드 방향 탐색 (v2)

v1 대비 주요 변경
-----------------
1. 방향 후보가 3개(X, Y, Z)가 아니라 6개(±X, ±Y, ±Z)이다.
   +Z와 -Z는 부품을 뒤집는 것이라 오버행 분포가 완전히 달라진다.
   v1은 축 정렬 방향의 절반만 보고 있었다.
2. find_optimal_orientation 이 evaluate_all_orientations 를 다시 호출하지 않는다.
   v1은 두 함수를 연달아 호출해 같은 평가를 6회(3방향 x 2) 중복 수행했다.
3. 인쇄 불가(하드 게이트 위반) 방향은 후보에서 제외한다.
4. 임의 방향 리스트를 주입할 수 있어 향후 GA 도입 시 그대로 재사용된다.
"""

from typing import Dict, List, Optional

import numpy as np
import trimesh

from src.processes.additive import AMRuleEngine, EvaluationResult

AXIS_ORIENTATIONS = {
    '+Z (기본)': (0, 0, 1),
    '-Z (뒤집기)': (0, 0, -1),
    '+X': (1, 0, 0),
    '-X': (-1, 0, 0),
    '+Y': (0, 1, 0),
    '-Y': (0, -1, 0),
}


def evaluate_orientations(mesh: trimesh.Trimesh, process_type='FDM',
                          printer_dims=(250, 250, 250),
                          orientations: Optional[Dict] = None,
                          min_feature_enabled=False, thickness_gradient_enabled=False,
                          layer_settings=None) -> Dict[str, EvaluationResult]:
    """주어진 방향들에 대해 한 번씩만 평가한다."""
    engine = AMRuleEngine()
    orientations = orientations or AXIS_ORIENTATIONS
    return {label: engine.evaluate(mesh, process_type, d, printer_dims,
                                   min_feature_enabled=min_feature_enabled,
                                   thickness_gradient_enabled=thickness_gradient_enabled,
                                   layer_settings=layer_settings)
            for label, d in orientations.items()}


def pick_best(results: Dict[str, EvaluationResult]) -> dict:
    """이미 계산된 결과에서 최적 방향을 고른다 (재평가하지 않는다)."""
    feasible = {k: v for k, v in results.items() if v.feasible and v.total_score is not None}
    if not feasible:
        states = {v.evaluation_status for v in results.values()}
        if not results:
            note = '비교할 방향 평가 결과가 없습니다.'
        elif states == {'blocked'}:
            note = '검사한 모든 방향에서 현재 프로필 조건을 충족하지 못했습니다.'
        else:
            note = '추천 가능한 방향이 없습니다. 입력 오류·판정 보류와 프로필 미충족을 방향별로 확인하세요.'
        return {'best_orientation': None, 'best_score': None, 'best_grade': None,
                'feasible_count': 0, 'comparable': False, 'note': note}
    sets = [{r.rule_name for r in v.rule_results if r.score is not None} for v in feasible.values()]
    if any(names != sets[0] for names in sets[1:]):
        return {'best_orientation': None, 'best_score': None, 'best_grade': None,
                'feasible_count': len(feasible), 'comparable': False,
                'note': '방향별 평가된 규칙 집합이 달라 총점으로 1위를 선정할 수 없습니다. N/A 항목을 확인하세요.'}
    best = max(feasible.items(), key=lambda kv: kv[1].total_score)
    ties = [label for label, r in feasible.items() if abs(r.total_score-best[1].total_score) < 1e-9]
    return {'best_orientation': best[0], 'best_score': best[1].total_score,
            'best_grade': best[1].grade, 'feasible_count': len(feasible),
            'tied_best': ties,
            'note': ('최고 점수 동점: ' + ', '.join(ties) + '. 표시 순서로 대표 방향을 선택했으며 유일한 최적해가 아닙니다.' if len(ties)>1 else '')}


def find_optimal_orientation(mesh, process_type='FDM', printer_dims=(250, 250, 250),
                             orientations=None, min_feature_enabled=False,
                             thickness_gradient_enabled=False) -> dict:
    results = evaluate_orientations(mesh, process_type, printer_dims,
                                    orientations, min_feature_enabled, thickness_gradient_enabled)
    out = pick_best(results)
    out['all_results'] = results
    return out


def results_to_rows(results: Dict[str, EvaluationResult]) -> List[dict]:
    """방향별 비교 표. 규칙이 행, 방향이 열."""
    labels = list(results)
    rows = []
    by_name = {label: {r.rule_name: r for r in result.rule_results}
               for label, result in results.items()}
    names = dict((r.rule_name, r.label) for result in results.values() for r in result.rule_results)
    for name, title in names.items():
        row = {'규칙': title}
        for label in labels:
            r = by_name[label].get(name)
            row[label] = 'N/A' if r is None or r.score is None else round(r.score, 1)
        rows.append(row)
    row = {'규칙': '프로필 판정'}
    for label in labels:
        r = results[label]
        row[label] = '기준 통과' if r.feasible else r.summary
    rows.append(row)

    row = {'규칙': '종합 점수'}
    for lb in labels:
        r = results[lb]
        row[lb] = '-' if r.total_score is None else f"{r.total_score} ({r.grade})"
    rows.append(row)
    return rows


def sensitivity_analysis(mesh, process_type='FDM', build_direction=(0, 0, 1),
                         printer_dims=(250, 250, 250), delta=0.5, seed=0,
                         n_trials=200, min_feature_enabled=False,
                         thickness_gradient_enabled=False) -> dict:
    """가중치 민감도 분석.

    각 가중치를 +-delta 비율로 무작위 교란한 뒤 등급이 얼마나 바뀌는지 본다.
    가중치를 evaluate 인자로 주입하므로 전역 상태를 수정하지 않는다.

    주의: 등급 변동률은 부품이 등급 경계에서 얼마나 떨어져 있는지에 크게
    좌우된다. 경계에서 먼 부품은 변동률이 0에 가깝게 나오므로, 이 수치만으로
    '가중치가 강건하다'고 결론지으면 안 된다. boundary_distance 를 함께 본다.
    """
    from src.processes.additive import BASE_WEIGHTS

    if not np.isfinite(delta) or not 0 <= delta < 1 or n_trials < 1:
        raise ValueError('delta는 0 이상 1 미만, 시행 수는 1 이상이어야 합니다.')
    engine = AMRuleEngine()
    base = engine.evaluate(mesh, process_type, build_direction, printer_dims,
                           min_feature_enabled=min_feature_enabled,
                           thickness_gradient_enabled=thickness_gradient_enabled,
                           layer_review_enabled=False)
    if base.total_score is None:
        return {'base': base, 'note': '종합 점수가 없어 민감도 분석을 보류합니다. ' + base.summary}

    rng = np.random.default_rng(seed)
    original = dict(BASE_WEIGHTS)
    scores, grades = [], []
    for _ in range(n_trials):
        w = {k: v * (1.0 + rng.uniform(-delta, delta)) for k, v in original.items()}
        tot = sum(w.values())
        w = {k: v / tot for k, v in w.items()}
        # Geometry and per-rule scores are independent of weights.
        active = [r for r in base.rule_results if r.score is not None]
        mass = sum(w[r.rule_name] for r in active)
        total = round(sum(r.score * w[r.rule_name] for r in active) / mass, 1)
        scores.append(total)
        grades.append(engine._grade(total))

    scores = np.array(scores, dtype=float)
    boundaries = (60.0, 70.0, 80.0, 90.0)
    dist = min(abs(base.total_score - b) for b in boundaries)
    return {
        'base_score': base.total_score, 'base_grade': base.grade,
        'score_min': float(scores.min()), 'score_max': float(scores.max()),
        'score_std': float(scores.std()),
        'grade_changed_ratio': float(np.mean([g != base.grade for g in grades])),
        'boundary_distance': float(dist),
        'delta': delta, 'n_trials': len(scores),
    }


def pareto_front(results: Dict[str, EvaluationResult]) -> dict:
    """가중치 없이 방향을 고를 수 있는지 본다.

    방향 A가 방향 B를 모든 규칙에서 같거나 낫고 최소 하나에서 더 나으면
    A가 B를 지배한다. 지배 관계가 성립하면 어떤 양수 가중치를 써도 순위가
    바뀌지 않으므로, 그 선택에는 가중치가 필요하지 않다.
    """
    feas = {k: v for k, v in results.items()
            if v.feasible and v.total_score is not None}
    if len(feas) < 2:
        return {'front': list(feas), 'weight_free': False, 'best_by_weights': next(iter(feas), None),
                'note': '비교 대상이 부족합니다.'}

    sets = [{r.rule_name for r in v.rule_results if r.score is not None} for v in feas.values()]
    if any(names != sets[0] for names in sets[1:]):
        return {'front': [], 'weight_free': False, 'best_by_weights': None,
                'comparable': False, 'note': '방향별 측정 가능한 규칙 집합이 달라 파레토 비교를 보류합니다.'}
    names = sorted(sets[0])
    V = {k: np.array([next(x.score for x in v.rule_results if x.rule_name == n)
                      for n in names], dtype=float) for k, v in feas.items()}

    def dominates(a, b):
        return bool(np.all(a >= b - 1e-9) and np.any(a > b + 1e-9))

    labels = list(feas)
    front = [a for a in labels
             if not any(dominates(V[b], V[a]) for b in labels if b != a)]
    best_w = max(labels, key=lambda l: feas[l].total_score)
    weight_free = all(
        dominates(V[best_w], V[b]) or np.allclose(V[best_w], V[b], rtol=0, atol=1e-9)
        for b in labels if b != best_w)
    return {
        'front': front, 'best_by_weights': best_w, 'weight_free': weight_free,
        'rules': names,
        'note': ('가중합 1위가 나머지를 지배하거나 모든 규칙 점수가 같으므로 이 선택에는 가중치가 '
                 '필요하지 않습니다.' if weight_free else
                 f'트레이드오프가 있어 파레토 최적 {len(front)}개 중 선택하려면 '
                 f'선호 정보(가중치 등)가 필요합니다.'),
    }
