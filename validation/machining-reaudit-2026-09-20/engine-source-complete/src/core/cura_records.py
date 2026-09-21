"""Read-only measurement analysis. Historical observations are never rewritten."""
from collections import defaultdict
from pathlib import Path
import csv
import json
import re

import numpy as np

from .reproducibility import file_sha256, runtime_record
from .validation_metrics import model_comparison, prediction_summary

TERM_KEYS = ('vol_term', 'perim_term', 'area_term')


def _reject_json_constant(value):
    raise ValueError(f'JSON 비유한 상수: {value}')


def _number(value, line, name, optional=False):
    if value is None or str(value).strip() == '':
        if optional:
            return None
        raise ValueError(f'CSV {line}행: {name} 값이 비어 있습니다.')
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f'CSV {line}행: {name} 값은 숫자여야 합니다.') from exc
    if not np.isfinite(result) or result < 0:
        raise ValueError(f'CSV {line}행: {name} 값은 유한한 음이 아닌 숫자여야 합니다.')
    return result


def _profile(raw, line):
    if not raw:
        return None
    try:
        profile = json.loads(raw, parse_constant=_reject_json_constant)
    except (ValueError, TypeError) as exc:
        raise ValueError(f'CSV {line}행: profile_json 형식이 잘못되었습니다.') from exc
    if not isinstance(profile, dict):
        raise ValueError(f'CSV {line}행: profile_json은 객체여야 합니다.')
    for key in ('critical_angle', 'bridge_limit', 'support_density', 'support_wall'):
        profile[key] = _number(profile.get(key), line, key)
    if profile['critical_angle'] > 90:
        raise ValueError(f'CSV {line}행: critical_angle은 0~90도여야 합니다.')
    return profile


def _local_stl(base, filename, line):
    # CSV paths must describe files in this experiment, also on Windows.
    if '\\' in filename or re.match(r'^[A-Za-z]:', filename):
        raise ValueError(f'CSV {line}행: STL 경로는 CSV 폴더 안의 상대 경로여야 합니다.')
    path = (base / filename).resolve()
    if Path(filename).is_absolute() or not path.is_relative_to(base.resolve()):
        raise ValueError(f'CSV {line}행: STL 경로가 실험 폴더 밖을 가리킵니다.')
    if path.suffix.lower() != '.stl':
        raise ValueError(f'CSV {line}행: STL 파일명이 필요합니다.')
    return path


def read_records(csv_path, filament_dia=None, recompute_terms=False, bridge_limit=None):
    csv_path = Path(csv_path)
    if filament_dia is not None and (not np.isfinite(filament_dia) or filament_dia <= 0):
        raise ValueError('필라멘트 지름은 유한한 양수여야 합니다.')
    if bridge_limit is not None and (not np.isfinite(bridge_limit) or bridge_limit < 0):
        raise ValueError('브리지 한계는 유한한 음이 아닌 값이어야 합니다.')
    if bridge_limit is not None and not recompute_terms:
        raise ValueError('--bridge-limit은 --recompute-terms와 함께 사용하세요.')
    current = None
    if recompute_terms:
        from . import geometry_analyzer as ga
        from .model_loader import load_model
        from src.processes.additive import PROCESS_PARAMS, ProcessType
        current = dict(PROCESS_PARAMS[ProcessType.FDM])
        if bridge_limit is not None:
            current['bridge_limit'] = float(bridge_limit)

    rows, skipped, warnings = [], [], set()
    seen = set()
    total = 0
    with csv_path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        required = {'file', 'cura_len_no_support_m', 'cura_len_with_support_m'}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('CSV에 file, cura_len_no_support_m, cura_len_with_support_m 열이 필요합니다.')
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError('CSV 헤더에 중복된 열 이름이 있습니다.')
        for line, raw in enumerate(reader, 2):
            total += 1
            if None in raw:
                raise ValueError(f'CSV {line}행: 열 수가 헤더와 다릅니다. 쉼표와 따옴표를 확인하세요.')
            off = _number(raw.get('cura_len_no_support_m'), line, '서포트 OFF 길이', optional=True)
            on = _number(raw.get('cura_len_with_support_m'), line, '서포트 ON 길이', optional=True)
            if off is None or on is None:
                skipped.append(dict(line=line, file=raw.get('file'), reason='서포트 OFF/ON 길이 미입력'))
                continue
            if on < off:
                raise ValueError(f'CSV {line}행: ON 길이가 OFF보다 작습니다. 원자료와 설정을 확인하세요.')
            filename = (raw.get('file') or '').strip()
            if not filename:
                raise ValueError(f'CSV {line}행: 파일명이 비어 있습니다.')
            path = _local_stl(csv_path.parent, filename, line)
            if (raw.get('process') or 'FDM').upper() != 'FDM':
                raise ValueError(f'CSV {line}행: Cura 필라멘트 대조는 FDM만 지원합니다.')
            suffix = re.search(r'__(pos|neg)([XYZ])$', Path(filename).stem, re.IGNORECASE)
            inferred = (suffix.group(1).lower() + suffix.group(2).upper()) if suffix else None
            direction = (raw.get('orientation') or '').strip()
            if direction in ('', '#NAME?') and inferred:
                direction = inferred
                warnings.add('누락되거나 #NAME?인 방향은 파일명에서 복원했습니다. 원본 CSV는 변경하지 않았습니다.')
            if inferred and direction != inferred:
                raise ValueError(f'CSV {line}행: 파일명 방향 {inferred}와 orientation={direction}가 다릅니다.')
            if not direction:
                raise ValueError(f'CSV {line}행: 방향 정보가 필요합니다.')
            key = (filename.casefold(), direction)
            if key in seen:
                raise ValueError(f'CSV {line}행: 같은 파일·방향이 중복되었습니다: {filename}')
            seen.add(key)
            recorded_dia = _number(raw.get('filament_diameter_mm'), line, '필라멘트 지름', optional=True)
            if recorded_dia is not None and recorded_dia <= 0:
                raise ValueError(f'CSV {line}행: 필라멘트 지름은 양수여야 합니다.')
            if recorded_dia is not None and filament_dia is not None and not np.isclose(recorded_dia, filament_dia):
                raise ValueError(f'CSV {line}행: --filament와 기록된 지름이 다릅니다. 측정 조건을 확인하세요.')
            dia = recorded_dia if recorded_dia is not None else (filament_dia if filament_dia is not None else 1.75)
            if recorded_dia is None:
                warnings.add(f'필라멘트 지름 기록이 없는 행은 {dia:g}mm로 가정했습니다.')
            pred = _number(raw.get('pred_support_mm3'), line, '저장된 예측 부피', optional=True)
            profile = _profile(raw.get('profile_json'), line)
            if raw.get('unit') not in (None, '', 'mm'):
                raise ValueError(f'CSV {line}행: 저장된 형상 항의 단위는 mm 기준이어야 합니다.')
            terms_values = [_number(raw.get(k), line, k, optional=True) for k in TERM_KEYS]
            if any(v is not None for v in terms_values) and any(v is None for v in terms_values):
                raise ValueError(f'CSV {line}행: 부피·둘레·면적 항 중 일부만 입력되어 있습니다.')
            terms = dict(zip(TERM_KEYS, terms_values)) if all(v is not None for v in terms_values) else None
            if terms is not None and profile is not None and pred is not None:
                expected = profile['support_density'] * terms['vol_term'] + profile['support_wall'] * terms['perim_term']
                if abs(expected - pred) > 0.051 + abs(expected) * 1e-10:
                    raise ValueError(f'CSV {line}행: 저장된 형상 항·계수로 계산한 값과 예측 부피가 다릅니다.')
            digest = (raw.get('stl_sha256') or '').strip()
            if digest and path.is_file() and file_sha256(path) != digest:
                raise ValueError(f'CSV {line}행: STL 해시가 기록과 다릅니다. 파일이 바뀌었는지 확인하세요.')
            if digest and not path.is_file():
                warnings.add('일부 STL이 없어 파일 해시는 확인하지 못했습니다. 저장된 수치만 분석합니다.')
            part_name = Path(filename).stem.rsplit('__', 1)[0]
            group = (raw.get('part_id') or '').strip() or (raw.get('source_sha256') or '').strip() or part_name
            basis, reason = 'stored', None
            term_profile = profile
            if recompute_terms:
                basis, term_profile, terms = 'current-recomputed', current, None
                try:
                    mesh = load_model(str(path), unit='mm')['mesh']
                    from src.processes.additive import AMRuleEngine
                    gate = AMRuleEngine._mesh_gate(mesh)
                    if not gate.passed:
                        raise ValueError(gate.detail)
                    terms = ga.support_terms(mesh, current['critical_angle'], current['bridge_limit'])
                    terms = {k: float(terms[k]) for k in TERM_KEYS}
                except Exception as exc:
                    reason = f'현재 코드의 형상 항 재계산 실패: {exc}'
                warnings.add('형상 항은 현재 코드로 새로 계산했습니다. 저장된 과거 예측값의 R²와 별도로 해석하세요.')
            elif terms is None:
                reason = '저장된 형상 항 없음. 현재 설정으로 자동 대체하지 않았습니다.'
            elif profile is None:
                warnings.add('일부 저장 형상 항은 계산 프로필 기록이 없습니다. 해당 회귀는 조건 미확인의 참고 결과입니다.')
            settings_id = (raw.get('cura_settings_id') or '').strip()
            cura_version = (raw.get('cura_version') or '').strip()
            if not settings_id or not cura_version:
                warnings.add('Cura 버전·설정 식별자가 없는 행이 있습니다. 슬라이싱 조건의 일치는 확인되지 않았습니다.')
            cohort = json.dumps(dict(profile=term_profile, term_basis=basis,
                                     geometry_code=raw.get('code_sha256') if basis == 'stored' else 'current',
                                     cura_settings_id=settings_id, cura_version=cura_version,
                                     filament_diameter_mm=dia), sort_keys=True, ensure_ascii=False)
            prediction_cohort = json.dumps(dict(profile=profile, code_sha256=raw.get('code_sha256'),
                                                 cura_settings_id=settings_id, cura_version=cura_version,
                                                 filament_diameter_mm=dia), sort_keys=True, ensure_ascii=False)
            measured = (on - off) * 1000 * np.pi * (dia / 2) ** 2
            if not np.isfinite(measured):
                raise ValueError(f'CSV {line}행: 환산 부피가 수치 범위를 벗어났습니다.')
            rows.append(dict(line=line, file=filename, orientation=direction, part_name=part_name,
                             group=group, pred=pred, meas=float(measured), filament_diameter_mm=dia,
                             terms=terms, term_basis=basis, term_profile=term_profile,
                             term_reason=reason, cohort=cohort, prediction_cohort=prediction_cohort, raw=raw))
    return rows, dict(total_rows=total, measured_rows=len(rows), part_count=len({r['group'] for r in rows}), skipped=skipped,
                      warnings=sorted(warnings), current_recompute_profile=current)


def analyze_records(csv_path, filament_dia=None, recompute_terms=False, bridge_limit=None):
    rows, reading = read_records(csv_path, filament_dia, recompute_terms, bridge_limit)
    prediction = prediction_summary(rows)
    current_prediction = None
    if recompute_terms:
        current_rows = []
        for row in rows:
            profile, terms = row['term_profile'], row['terms']
            value = (profile['support_density'] * terms['vol_term'] + profile['support_wall'] * terms['perim_term']
                     if terms is not None else None)
            row['current_pred'] = value
            current_rows.append(dict(row, pred=value, prediction_cohort=row['cohort']))
        current_prediction = prediction_summary(current_rows)
    cohorts = defaultdict(list)
    for row in rows:
        if row['terms'] is not None:
            cohorts[row['cohort']].append(row)
    fits = [dict(conditions=json.loads(key), result=model_comparison(items)) for key, items in cohorts.items()]
    raw = prediction['raw']
    result = dict(schema_version=2, status='ok' if rows else 'no_measurements',
                  input_file=Path(csv_path).name, input_sha256=file_sha256(csv_path),
                  runtime=runtime_record(), reading=reading, prediction=prediction, current_prediction=current_prediction,
                  model_comparisons=fits, rows=rows,
                  metric_scope='Cura 서포트 ON/OFF 필라멘트 길이 차이의 재료 부피 환산값. 실물 출력 성공률 아님.',
                  json_null_meaning='미측정, 적용 불가 또는 정의되지 않는 수치',
                  n=raw['n'], raw_r2=raw['r2'], r2=raw['r2'], mae=raw['mae'], rmse=raw['rmse'],
                  pearson=raw['pearson'], spearman=raw['spearman'], slope=prediction['fitted_scale'],
                  scaled_fit_r2=prediction['scaled_fit']['r2'] if prediction['scaled_fit'] else None)
    return result


def print_analysis(report, verbose=True):
    def number(x, digits=4):
        return 'N/A' if x is None else f'{x:.{digits}f}'
    reading, p = report['reading'], report['prediction']
    print(f"부품 {reading['part_count']}종 / 측정표 {reading['total_rows']}행 / 측정 완료 {reading['measured_rows']}행 / 저장 예측값 대조 {p['raw']['n']}행")
    print(f"원예측 R²={number(p['raw']['r2'])} · MAE={number(p['raw']['mae'],2)}mm³ · RMSE={number(p['raw']['rmse'],2)}mm³")
    print(f"0-0 행 {p['both_zero_n']}개 제외: n={p['nonzero']['n']}, R²={number(p['nonzero']['r2'])}")
    print(f"같은 자료에서 배율 재적합: 배율={number(p['fitted_scale'])}, R²={number(report['scaled_fit_r2'])}")
    print('배율 재적합은 원예측 평가와 구분합니다. 기존 계수와 측정값은 변경하지 않았습니다.')
    print('\n부품별 원예측 오차')
    for part in p['by_part']:
        m = part['metrics']
        print(f"  {part['label']}: n={m['n']}, R²={number(m['r2'])}, MAE={number(m['mae'],2)}mm³")
    if verbose:
        print('\n절대오차가 큰 조건 (예측 − Cura 환산값)')
        for row in p['residuals'][:6]:
            print(f"  {row['file']}: {row['predicted_mm3']:.1f} / {row['measured_mm3']:.1f}mm³, 오차 {row['error_mm3']:+.1f}mm³")
    if report['current_prediction'] is not None:
        current = report['current_prediction']['raw']
        print('\n현재 엔진의 고정 계수 예측 (계수 재적합 전)')
        print(f"  n={current['n']}, R²={number(current['r2'])}, MAE={number(current['mae'],2)}mm³, RMSE={number(current['rmse'],2)}mm³")
    print('\n형상 항 모델 비교 (설정별로 분리, 절편 없음, 중심화 R²)')
    if not report['model_comparisons']:
        print('  저장된 형상 항이 없어 회귀·교차검증은 수행하지 않았습니다.')
        print('  현재 엔진의 새 결과를 비교하려면 --recompute-terms를 명시하세요.')
    for i, comparison in enumerate(report['model_comparisons'], 1):
        result = comparison['result']
        conditions = comparison['conditions']
        mode = '저장된 형상 항' if conditions['term_basis'] == 'stored' else '현재 엔진에서 새로 계산한 형상 항'
        print(f"  설정 {i}: {mode}, n={result['n']}")
        if result['status'] != 'ok':
            print('   ', result['reason']); continue
        for name, model in result['models'].items():
            if model['status'] == 'ok':
                coefs = ' '.join(f'{k}={v:+.6f}' for k,v in model['coefficients'].items())
                print(f"    {name}: R²={number(model['metrics']['r2'])}, {coefs}")
            else:
                print(f"    {name}: {model['reason']}")
        cv = result['validation']
        print(f"    1행 제외 Q²={number(cv['leave_one_row_out']['q2'])}")
        by_part = cv['leave_one_part_out']
        print(f"    부품 전체 제외 통합 Q²={number(by_part['q2'])}")
        for fold in by_part.get('folds', []):
            if fold['status'] == 'ok':
                m = fold['metrics']
                print(f"      {fold['label']}: Q²={number(m['r2'])}, MAE={number(m['mae'],2)}mm³")
            else:
                print(f"      {fold['label']}: {fold['reason']}")
        print('   ', cv['scope'])
    for row in reading['skipped']:
        print(f"  미사용 {row['line']}행 ({row['file']}): {row['reason']}")
    missing_prediction = [r['line'] for r in report['rows'] if r['pred'] is None]
    if missing_prediction:
        print('  예측값 미입력 행:', ', '.join(map(str, missing_prediction)), '(측정값은 형상 항 회귀에 유지)')
    failed_terms = [r for r in report['rows'] if r['term_reason']]
    if failed_terms:
        print(f"  형상 항 미사용 {len(failed_terms)}행; 행별 사유는 저장된 분석 JSON의 rows를 확인하세요.")
    for warning in reading['warnings']:
        print('  참고:', warning)
    print('\nR²는 Cura 추가 재료량의 대조 지표입니다. 종합 제조성 등급과 실제 출력 품질은 별도 검증 대상입니다.')
