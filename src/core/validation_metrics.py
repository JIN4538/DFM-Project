"""Cura comparison statistics, independent of STL loading and the rule engine.

R² uses the centered target sum of squares, also for models without an intercept.
An undefined R² (constant target, empty data, one observation) is returned as None.
The fixed two-term model is cross-validated by refitting coefficients only.
"""
import numpy as np
from scipy.stats import spearmanr


def metrics(measured, predicted):
    y = np.asarray(measured, dtype=float)
    p = np.asarray(predicted, dtype=float)
    if y.ndim != 1 or p.shape != y.shape or not np.isfinite(y).all() or not np.isfinite(p).all():
        raise ValueError('측정값과 예측값은 길이가 같은 유한한 1차원 배열이어야 합니다.')
    if not len(y):
        return dict(n=0, r2=None, mae=None, rmse=None, bias=None, max_absolute_error=None,
                    pearson=None, spearman=None, mape_nonzero=None)
    error = p - y
    ss = float(np.sum((y - y.mean()) ** 2))
    varied = len(y) > 1 and np.ptp(y) > 0 and np.ptp(p) > 0
    nonzero = y > 0
    return dict(
        n=len(y), r2=1 - float(error @ error) / ss if len(y) > 1 and ss > 0 else None,
        mae=float(np.abs(error).mean()), rmse=float(np.sqrt(np.mean(error ** 2))),
        bias=float(error.mean()), max_absolute_error=float(np.abs(error).max()),
        pearson=float(np.corrcoef(y, p)[0, 1]) if varied else None,
        spearman=float(spearmanr(y, p).statistic) if varied else None,
        mape_nonzero=float(np.mean(np.abs(error[nonzero]) / y[nonzero])) if nonzero.any() else None,
    )


def prediction_summary(rows):
    """Rows missing a stored prediction are kept elsewhere for model fitting."""
    paired = [r for r in rows if r['pred'] is not None]
    y = np.array([r['meas'] for r in paired])
    p = np.array([r['pred'] for r in paired])
    raw = metrics(y, p)
    nonzero = (y != 0) | (p != 0)
    denominator = float(p @ p)
    slope = float(p @ y) / denominator if denominator > 0 else None
    scaled = metrics(y, slope * p) if slope is not None else None
    groups = []
    def row_cohort(row):
        return row.get('prediction_cohort', row.get('cohort', ''))

    for group, cohort in sorted({(r['group'], row_cohort(r)) for r in paired}):
        sample = [r for r in paired if r['group'] == group and row_cohort(r) == cohort]
        gy = np.array([r['meas'] for r in sample]); gp = np.array([r['pred'] for r in sample])
        best_y = [r['orientation'] for r, v in zip(sample, gy) if np.isclose(v, gy.min(), rtol=0, atol=1e-8)]
        best_p = [r['orientation'] for r, v in zip(sample, gp) if np.isclose(v, gp.min(), rtol=0, atol=1e-8)]
        groups.append(dict(group=group, cohort=cohort, label=sample[0]['part_name'], metrics=metrics(gy, gp),
                           minimum_cura_directions=best_y, minimum_predicted_directions=best_p,
                           informative=len(sample) > 1 and np.ptp(gy) > 0,
                           minimum_direction_overlap=bool(set(best_y) & set(best_p))))
    residuals = [dict(file=r['file'], orientation=r['orientation'], measured_mm3=r['meas'],
                      predicted_mm3=r['pred'], error_mm3=r['pred'] - r['meas'],
                      relative_error=(r['pred'] - r['meas']) / r['meas'] if r['meas'] > 0 else None)
                 for r in paired]
    residuals.sort(key=lambda r: -abs(r['error_mm3']))
    return dict(raw=raw, nonzero=metrics(y[nonzero], p[nonzero]),
                both_zero_n=int((~nonzero).sum()), fitted_scale=slope, scaled_fit=scaled,
                by_part=groups, residuals=residuals)


def fit_model(x, y, names):
    x = np.asarray(x, dtype=float); y = np.asarray(y, dtype=float)
    rank = int(np.linalg.matrix_rank(x))
    if rank < x.shape[1]:
        return dict(status='unavailable', reason='형상 항이 선형 종속이어서 계수를 구분할 수 없습니다.',
                    rank=rank, n=len(y), coefficient_names=names)
    beta = np.linalg.lstsq(x, y, rcond=None)[0]
    out = dict(status='ok', n=len(y), rank=rank, intercept=False,
               coefficients=dict(zip(names, map(float, beta))), metrics=metrics(y, x @ beta))
    out['negative_coefficients'] = [name for name, b in zip(names, beta) if b < 0]
    return out


def cross_validate(x, y, groups, labels):
    """Do not publish an overall Q² when any required fold could not be fitted."""
    x = np.asarray(x, dtype=float); y = np.asarray(y, dtype=float)
    groups = np.asarray(groups)

    def run(folds):
        predictions = np.full(len(y), np.nan)
        records = []
        for group, test in folds:
            train = ~test
            record = dict(group=str(group), train_n=int(train.sum()), test_n=int(test.sum()))
            if train.sum() < x.shape[1] or np.linalg.matrix_rank(x[train]) < x.shape[1]:
                record.update(status='unavailable', reason='남은 학습 자료에서 두 계수를 구분할 수 없습니다.')
            else:
                beta = np.linalg.lstsq(x[train], y[train], rcond=None)[0]
                predictions[test] = x[test] @ beta
                record.update(status='ok', coefficients=beta.tolist(),
                              metrics=metrics(y[test], predictions[test]),
                              predictions=predictions[test].tolist(), measured=y[test].tolist())
            records.append(record)
        complete = bool(np.isfinite(predictions).all())
        summary = metrics(y, predictions) if complete else None
        return dict(status='ok' if complete else 'incomplete', folds=records,
                    evaluated_n=int(np.isfinite(predictions).sum()), total_n=len(y),
                    q2=summary['r2'] if summary else None, metrics=summary)

    by_row = run([(i, np.arange(len(y)) == i) for i in range(len(y))])
    unique = sorted(set(groups))
    by_part = (run([(g, groups == g) for g in unique]) if len(unique) >= 2 else
               dict(status='unavailable', reason='서로 다른 부품이 2종 이상 필요합니다.', q2=None))
    for fold in by_part.get('folds', []):
        fold['label'] = labels.get(fold['group'], fold['group'])
    return dict(leave_one_row_out=by_row, leave_one_part_out=by_part,
                scope='고정된 2항 공식의 계수만 재적합합니다. 공식 선택까지 독립된 외부 시험은 아닙니다.')


def model_comparison(rows):
    complete = [r for r in rows if r.get('terms') is not None]
    if len(complete) < 6:
        return dict(status='unavailable', n=len(complete), reason='동일 조건의 형상 항과 측정값이 6행 이상 필요합니다.')
    x = np.array([[r['terms'][k] for k in ('vol_term', 'perim_term', 'area_term')] for r in complete])
    y = np.array([r['meas'] for r in complete])
    if not np.isfinite(x).all() or np.any(x < 0):
        raise ValueError('형상 항은 유한한 음이 아닌 값이어야 합니다.')
    models = {}
    for name, cols, names in [('volume', [0], ['a']), ('volume_perimeter', [0, 1], ['a', 'b']),
                              ('volume_area', [0, 2], ['a', 'c']),
                              ('volume_perimeter_area', [0, 1, 2], ['a', 'b', 'c'])]:
        models[name] = fit_model(x[:, cols], y, names)
    groups = [r['group'] for r in complete]
    labels = {r['group']: r['part_name'] for r in complete}
    return dict(status='ok', n=len(y), part_count=len(set(groups)),
                r2_definition='1 - sum((y - prediction)^2) / sum((y - mean(y))^2); 절편 없음',
                models=models, validation=cross_validate(x[:, :2], y, groups, labels))
