"""가중치 도출 (Weight Elicitation)

현재 BASE_WEIGHTS 는 '실패 시 결과의 심각도' 라는 판단에 근거한 값이며
데이터 근거가 없다. 이 모듈은 그 한계를 좁히기 위한 두 가지 경로를 제공한다.

경로 1 — AHP (Analytic Hierarchy Process, 계층분석법)
    항목을 한꺼번에 저울질하는 대신 두 개씩만 비교한다. n개 항목이면
    n(n-1)/2 번의 쌍대비교로 가중치 벡터를 산출하고, 일관성 비율(CR)로
    응답이 논리적으로 모순되지 않는지 검증한다. CR < 0.1 이면 수용 가능.
    전문가 판단을 구조화된 데이터로 바꾸는 표준적 방법이다.

경로 2 — 회귀 (regress_weights)
    부품별 규칙 점수와 관측된 결과(슬라이서 실측 비용 또는 실제 출력
    성공/실패)를 짝지어 회귀하면, 계수가 곧 데이터 기반 가중치가 된다.
    정규화한 절댓값 가중치는 예측 모델 자체가 아니다. 예측에는 절편·표준화·계수 부호가 모두 필요하다.

참고: 시험 제작물을 이용한 성능 평가는 KS D ISO/ASTM 52902 가 다룬다.
"""

from typing import Dict, List, Sequence, Tuple

import numpy as np

# Saaty 척도 — 쌍대비교 시 사용하는 9단계
SAATY_SCALE = {
    1: '동등하게 중요',
    2: '동등~약간 사이',
    3: '약간 더 중요',
    4: '약간~상당히 사이',
    5: '상당히 더 중요',
    6: '상당히~매우 사이',
    7: '매우 더 중요',
    8: '매우~극히 사이',
    9: '극히 더 중요',
}

# Saaty 무작위 지수(Random Index) — 일관성 비율 계산용
RANDOM_INDEX = {1: 0.00, 2: 0.00, 3: 0.58, 4: 0.90, 5: 1.12,
                6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49}


def build_matrix(items: Sequence[str], comparisons: Dict[Tuple[str, str], float]) -> np.ndarray:
    """쌍대비교 결과로 역수 행렬을 만든다.

    comparisons[(A, B)] = v 는 'A가 B보다 v배 중요' 를 뜻한다.
    v > 1 이면 A 우세, v < 1 이면 B 우세.
    """
    n = len(items)
    if n < 2 or len(set(items)) != n:
        raise ValueError('서로 다른 항목이 2개 이상 필요합니다.')
    expected = {frozenset((items[i], items[j])) for i in range(n) for j in range(i+1,n)}
    received = [frozenset(pair) for pair in comparisons]
    if set(received) != expected or len(received) != len(expected):
        raise ValueError('모든 쌍을 중복 없이 비교해야 합니다. 누락값을 동등으로 간주하지 않습니다.')
    idx = {name: i for i, name in enumerate(items)}
    M = np.ones((n, n), dtype=float)
    for (a, b), v in comparisons.items():
        if a not in idx or b not in idx:
            raise KeyError(f"알 수 없는 항목: {a} 또는 {b}")
        v = float(v)
        if not np.isfinite(v) or v <= 0:
            raise ValueError("비교값은 양수여야 합니다.")
        M[idx[a], idx[b]] = v
        M[idx[b], idx[a]] = 1.0 / v
    return M


def ahp(items: Sequence[str], comparisons: Dict[Tuple[str, str], float]) -> dict:
    """AHP 가중치와 일관성 지표를 계산한다.

    가중치는 고유벡터법(주고유벡터)으로 구한다. 기하평균법도 널리 쓰이며
    결과가 거의 같으므로 비교용으로 함께 돌려준다.
    """
    items = list(items)
    n = len(items)
    if n < 2:
        raise ValueError("항목이 2개 이상이어야 합니다.")
    M = build_matrix(items, comparisons)

    # 주고유벡터
    vals, vecs = np.linalg.eig(M)
    k = int(np.argmax(vals.real))
    w = np.abs(vecs[:, k].real)
    w = w / w.sum()
    lam_max = float(vals[k].real)

    # 기하평균법(대조용)
    gm = np.exp(np.log(M).mean(axis=1))
    gm = gm / gm.sum()

    # 일관성
    ci = (lam_max - n) / (n - 1) if n > 2 else 0.0
    ri = RANDOM_INDEX.get(n, 1.49)
    cr = ci / ri if ri > 0 else 0.0

    return {
        'items': items,
        'weights': {it: float(w[i]) for i, it in enumerate(items)},
        'weights_geometric': {it: float(gm[i]) for i, it in enumerate(items)},
        'lambda_max': lam_max,
        'consistency_index': float(ci),
        'consistency_ratio': float(cr),
        'consistent': bool(cr < 0.10),
        'n_comparisons': n * (n - 1) // 2,
        'matrix': M,
    }


def pair_list(items: Sequence[str]) -> List[Tuple[str, str]]:
    """물어봐야 할 쌍의 목록. 설문 문항 생성용."""
    items = list(items)
    return [(items[i], items[j])
            for i in range(len(items)) for j in range(i + 1, len(items))]


def aggregate_experts(results: List[Dict[str, float]]) -> Dict[str, float]:
    """여러 응답자의 가중치를 기하평균으로 종합한다.

    AHP 에서 다수 응답을 합칠 때는 산술평균이 아니라 기하평균을 쓴다.
    비율 척도이기 때문이다.
    """
    if not results:
        return {}
    keys = list(results[0])
    out = {}
    for k in keys:
        vals = np.array([r[k] for r in results if k in r], dtype=float)
        out[k] = float(np.exp(np.log(vals).mean()))
    total = sum(out.values())
    return {k: v / total for k, v in out.items()}


def regress_weights(rule_scores: np.ndarray, observed: np.ndarray,
                    names: Sequence[str], mode: str = 'linear') -> dict:
    """관측 결과로부터 가중치를 추정한다.

    Parameters
    ----------
    rule_scores : (N, k) 배열. 부품 N개 x 규칙 k개의 0~100 점수.
    observed : (N,) 배열.
        mode='linear'   -> 관측된 제조 비용(출력 시간, 서포트 재료량 등)
        mode='logistic' -> 0/1 실패 여부
    names : 규칙 이름 k개.

    Returns
    -------
    계수를 정규화한 가중치와 적합도 지표.

    비고: 표본이 부족하면 계수가 불안정하다. 로지스틱의 경우 예측 변수당
    사건 10건이 통상적 하한이므로, 규칙 5개면 실패 사례 50건 이상이 필요하다.
    """
    X = np.asarray(rule_scores, dtype=float)
    y = np.asarray(observed, dtype=float).ravel()
    if X.ndim != 2 or X.shape[0] != y.shape[0]:
        raise ValueError("rule_scores 는 (N, k), observed 는 (N,) 이어야 합니다.")
    n, k = X.shape
    if len(names) != k or not np.isfinite(X).all() or not np.isfinite(y).all() or n < 2 or k < 1:
        raise ValueError('유효한 데이터와 변수별 이름이 필요합니다.')
    if mode == 'logistic' and (not np.isin(y,[0,1]).all() or len(np.unique(y)) != 2):
        raise ValueError('로지스틱 회귀에는 성공과 실패 두 범주의 0/1 자료가 필요합니다.')
    if n < k * 10:
        note = (f"표본 {n}건은 예측 변수 {k}개에 비해 적습니다. "
                f"권장 하한 {k*10}건 이상.")
    else:
        note = ""

    # 점수가 높을수록 좋은 지표이므로, 비용/실패와는 음의 관계가 기대된다.
    Xc = (X - X.mean(axis=0)) / (X.std(axis=0) + 1e-12)

    if mode == 'linear':
        A = np.column_stack([np.ones(n), Xc])
        beta, *_ = np.linalg.lstsq(A, y, rcond=None)
        coef = beta[1:]
        pred = A @ beta
        ss_res = float(((y - pred) ** 2).sum())
        ss_tot = float(((y - y.mean()) ** 2).sum())
        fit = {'r_squared': 1 - ss_res / ss_tot if ss_tot > 0 else float('nan')}
    elif mode == 'logistic':
        A = np.column_stack([np.ones(n), Xc])
        beta = np.zeros(A.shape[1])
        for _ in range(200):                       # 뉴턴-랩슨
            p = 1.0 / (1.0 + np.exp(-A @ beta))
            W = np.diag(p * (1 - p) + 1e-9)
            grad = A.T @ (y - p)
            H = -A.T @ W @ A
            try:
                step = np.linalg.solve(H, grad)
            except np.linalg.LinAlgError:
                break
            beta_new = beta - step
            if np.max(np.abs(beta_new - beta)) < 1e-8:
                beta = beta_new
                break
            beta = beta_new
        coef = beta[1:]
        p = 1.0 / (1.0 + np.exp(-A @ beta))
        ll = float(np.sum(y * np.log(p + 1e-12) + (1 - y) * np.log(1 - p + 1e-12)))
        pbar = y.mean()
        ll0 = float(np.sum(y * np.log(pbar + 1e-12) + (1 - y) * np.log(1 - pbar + 1e-12)))
        fit = {'pseudo_r_squared': 1 - ll / ll0 if ll0 != 0 else float('nan')}
    else:
        raise ValueError("mode 는 'linear' 또는 'logistic' 이어야 합니다.")

    mag = np.abs(coef)
    w = mag / mag.sum() if mag.sum() > 0 else np.full(k, 1.0 / k)
    return {
        'weights': {names[i]: float(w[i]) for i in range(k)},
        'coefficients': {names[i]: float(coef[i]) for i in range(k)},
        'intercept': float(beta[0]),
        'feature_mean': X.mean(axis=0).tolist(),
        'feature_scale': (X.std(axis=0) + 1e-12).tolist(),
        'weight_warning': '절댓값 정규화는 설명용 변수 중요도이며 비용 또는 실패 확률 예측식이 아닙니다.',
        'mode': mode, 'n_samples': n, 'fit': fit, 'note': note,
    }


def compare_weight_sets(sets: Dict[str, Dict[str, float]]) -> List[dict]:
    """여러 방법으로 구한 가중치를 나란히 비교하는 표를 만든다."""
    keys = sorted({k for s in sets.values() for k in s})
    rows = []
    for k in keys:
        row = {'규칙': k}
        vals = []
        for name, s in sets.items():
            v = s.get(k)
            row[name] = None if v is None else round(v, 4)
            if v is not None:
                vals.append(v)
        row['최대-최소'] = round(max(vals) - min(vals), 4) if len(vals) > 1 else 0.0
        rows.append(row)
    return rows
