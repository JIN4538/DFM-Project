"""Cura 대조 외부 검증 도구

지금까지의 검증(verify.py)은 모두 자기 일관성 검사다. '의도한 대로 계산하는가'는
확인했지만 '그 의도가 현실과 맞는가'는 확인하지 못했다. 상용 슬라이서가 실제로
생성하는 지지구조물 부피와 우리 추정치를 대조하면 그 간극을 좁힐 수 있다.

사용법
------
1) 슬라이싱할 STL 과 기록표를 생성한다.

       python cura_check.py export --stl NIST.stl --out cura_run

   cura_run/ 아래에 방향별 STL 과 measurements.csv 가 만들어진다.
   measurements.csv 에는 우리 도구의 예측값이 이미 채워져 있고,
   Cura 에서 읽은 값을 넣을 빈 칸이 있다.

2) Cura 로 각 STL 을 서포트 끄고 한 번, 켜고 한 번 슬라이싱해서
   필라멘트 사용량(m)을 measurements.csv 에 적는다.

3) 분석한다.

       python cura_check.py analyze --csv cura_run/measurements.csv

   원예측 오차와 부품별 오차를 출력하고 분석 JSON을 저장한다.
   과거 설정·분해항이 없으면 현재 설정으로 자동 대체하지 않는다.
"""

import argparse
import csv
import os
import sys
import json
import re
import tempfile
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import trimesh

from src.core import geometry_analyzer as ga
from src.core.model_loader import load_model
from src.core.scoring import AXIS_ORIENTATIONS
from src.processes.additive import AMRuleEngine, PROCESS_PARAMS, ProcessType
from src.core.model_loader import UNIT_SCALE
from src.core.reproducibility import file_sha256, runtime_record, save_new_json

# 1.75mm 필라멘트 단면적 (mm^2). Cura 가 보고하는 길이를 부피로 바꾼다.
FILAMENT_AREA_175 = np.pi * (1.75 / 2.0) ** 2      # 2.4053
FILAMENT_AREA_285 = np.pi * (2.85 / 2.0) ** 2      # 6.3794

COLUMNS = [
    'file', 'orientation', 'process', 'printer_xyz',
    'profile_json', 'source_sha256', 'part_id', 'stl_sha256', 'code_sha256',
    'unit', 'source_unit', 'filament_diameter_mm', 'cura_version', 'cura_settings_id',
    'vol_term', 'perim_term', 'area_term',
    'pred_support_mm3', 'pred_overhang_pct', 'pred_score', 'pred_grade',
    'cura_len_no_support_m', 'cura_len_with_support_m',
    'cura_time_no_support_min', 'cura_time_with_support_min', 'note',
]


def export(stl_paths, out_dir, process='FDM', printer=(300, 300, 340),
           orientations=None, unit='mm', filament_dia=1.75):
    """Publish a complete experiment in a new folder, without overwriting records.

    Exported STL is reloaded before evaluation so saved terms, prediction and
    the file sliced by Cura describe the same geometry and build direction.
    """
    if process.upper() != 'FDM':
        raise ValueError('Cura 필라멘트 대조는 FDM 프로필만 지원합니다.')
    if unit not in UNIT_SCALE:
        raise ValueError(f'지원하지 않는 단위: {unit}')
    if not np.isfinite(filament_dia) or filament_dia <= 0:
        raise ValueError('필라멘트 지름은 유한한 양수여야 합니다.')
    printer = np.asarray(printer, dtype=float)
    if printer.shape != (3,) or not np.isfinite(printer).all() or np.any(printer <= 0):
        raise ValueError('장비 크기는 3축 모두 유한한 양수여야 합니다.')
    output = Path(out_dir)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise FileExistsError(f'기존 자료를 보존합니다. 비어 있는 새 출력 폴더를 지정하세요: {output}')
    paths = [Path(p) for p in stl_paths]
    if not paths or len({p.resolve() for p in paths}) != len(paths):
        raise ValueError('중복되지 않는 STL 경로가 하나 이상 필요합니다.')
    directions = AXIS_ORIENTATIONS if orientations is None else orientations
    if not directions:
        raise ValueError('내보낼 방향이 하나 이상 필요합니다.')
    aliases = {'+Z (기본)': 'posZ', '-Z (뒤집기)': 'negZ', '+X': 'posX',
               '-X': 'negX', '+Y': 'posY', '-Y': 'negY'}
    prepared_directions = []
    for label, direction in directions.items():
        safe = aliases.get(label, re.sub(r'[^A-Za-z0-9_]', '', label))
        if not safe:
            raise ValueError('방향 이름에 영문 또는 숫자가 필요합니다.')
        prepared_directions.append((safe, ga.unit(direction)))
    if len({k.casefold() for k, _ in prepared_directions}) != len(prepared_directions):
        raise ValueError('파일명으로 변환한 방향 이름이 중복됩니다.')
    source_records = []
    used_names = set()
    for path in paths:
        digest = file_sha256(path)
        base = re.sub(r'[^A-Za-z0-9_-]', '_', path.stem).strip('_-') or 'part'
        name = base
        if name.casefold() in used_names:
            name = f'{base}_{digest[:10]}'
        count = 2
        while name.casefold() in used_names:
            name = f'{base}_{digest[:10]}_{count}'; count += 1
        used_names.add(name.casefold())
        source_records.append((path, name, digest))

    engine = AMRuleEngine()
    profile = dict(PROCESS_PARAMS[ProcessType.FDM])
    runtime = runtime_record()
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with tempfile.TemporaryDirectory(prefix='.cura-export-', dir=str(output.parent)) as temp:
        stage = Path(temp) / 'records'; stage.mkdir()
        for path, name, source_hash in source_records:
            mesh = load_model(str(path), unit=unit)['mesh']
            gate = engine._mesh_gate(mesh)
            if not gate.passed:
                raise ValueError(f'{path.name}: 내보내기 전 입력 형상 검토 필요 — {gate.detail}')
            print(f'[{name}] {len(mesh.faces):,}개 면, {mesh.volume:,.1f}mm³')
            for safe, direction in prepared_directions:
                oriented = ga.to_build_frame(mesh, direction)
                oriented.apply_translation([0, 0, -oriented.bounds[0][2]])
                filename = f'{name}__{safe}.stl'
                stl_path = stage / filename
                oriented.export(str(stl_path))
                # Re-read the exact bytes that will be opened by Cura.
                measured_mesh = load_model(str(stl_path), unit='mm')['mesh']
                result = engine.evaluate(measured_mesh, 'FDM', (0, 0, 1), printer,
                                         layer_review_enabled=False)
                if not result.mesh_diagnostics.get('solid_check_passed'):
                    raise ValueError(f'{filename}: STL 재로드 후 입력 검토 실패 — {result.summary}')
                terms = ga.support_terms(measured_mesh, profile['critical_angle'], profile['bridge_limit'])
                predicted = profile['support_density'] * terms['vol_term'] + profile['support_wall'] * terms['perim_term']
                if not np.isfinite([predicted, *(terms[k] for k in ('vol_term', 'perim_term', 'area_term'))]).all():
                    raise ValueError(f'{filename}: 서포트 항 계산값이 유한하지 않습니다.')
                overhang = next((r for r in result.rule_results if r.rule_name == 'overhang_area'), None)
                row = dict(
                    file=filename, orientation=safe, process='FDM',
                    printer_xyz='x'.join(f'{v:g}' for v in printer),
                    profile_json=json.dumps(profile, ensure_ascii=False, sort_keys=True),
                    source_sha256=source_hash, part_id=source_hash,
                    stl_sha256=file_sha256(stl_path), code_sha256=runtime['code_sha256'],
                    unit='mm', source_unit=unit, filament_diameter_mm=filament_dia,
                    cura_version='', cura_settings_id='',
                    vol_term=terms['vol_term'], perim_term=terms['perim_term'], area_term=terms['area_term'],
                    pred_support_mm3=round(float(predicted), 1),
                    pred_overhang_pct=overhang.value if overhang else '',
                    pred_score=result.total_score if result.total_score is not None else '', pred_grade=result.grade,
                    cura_len_no_support_m='', cura_len_with_support_m='',
                    cura_time_no_support_min='', cura_time_with_support_min='',
                    note='' if result.feasible else result.summary)
                rows.append(row)
                print(f'  {safe}: {predicted:.1f}mm³ / {result.grade}')
        with (stage / 'measurements.csv').open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=COLUMNS)
            writer.writeheader(); writer.writerows(rows)
        save_new_json(stage / 'experiment.json', dict(
            schema_version=2, runtime=runtime, profile=profile, rows=len(rows),
            exported_stl_unit='mm', source_unit=unit, filament_diameter_mm=filament_dia,
            expected_cura_settings=dict(support_overhang_angle=profile['critical_angle'], support_density_percent=15,
                                        support_placement='Everywhere', build_plate_adhesion='None'),
            actual_cura_settings_status='미확인 — Cura 측정 시 버전·설정 식별자를 CSV에 기록하세요.',
            sources=[dict(name=path.name, source_sha256=digest) for path, _, digest in source_records]))
        # rmdir only succeeds for an empty directory; it cannot remove user data.
        if output.exists():
            output.rmdir()
        stage.rename(output)
    print(f'\n{len(rows)}개 STL과 측정표: {output.resolve()}')
    print(f"Cura 기준 조건: 오버행 {profile['critical_angle']:g}도 / 서포트 밀도 15% / Everywhere / 접착 None")
    print('STL은 이미 빌드 방향과 mm 단위로 변환됐습니다. Cura에서 회전·크기를 바꾸지 마세요.')
    print('필라멘트 지름을 확인하고 Cura 버전·설정 식별자, OFF/ON 길이를 기록하세요.')
    return str(output / 'measurements.csv')


def analyze(csv_path, filament_dia=None, verbose=True, *, recompute_terms=False,
            bridge_limit=None):
    """Analyze stored measurements; geometry recomputation requires an explicit option."""
    from src.core.cura_records import analyze_records, print_analysis
    report = analyze_records(csv_path, filament_dia, recompute_terms, bridge_limit)
    print_analysis(report, verbose)
    return report


def pick_files(title, filetypes, multiple=True):
    """파일 선택 창을 띄운다. 경로를 손으로 입력할 필요를 없앤다."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        print("파일 선택 창을 열 수 없다(tkinter 미설치). --stl 로 경로를 직접 지정한다.")
        return []
    try:
        root = tk.Tk()
    except tk.TclError:
        print('파일 선택 창을 열 수 없습니다. --stl 또는 --csv로 경로를 지정하세요.')
        return []
    root.withdraw()
    root.attributes('-topmost', True)
    if multiple:
        res = filedialog.askopenfilenames(title=title, filetypes=filetypes)
    else:
        r = filedialog.askopenfilename(title=title, filetypes=filetypes)
        res = (r,) if r else ()
    root.destroy()
    return [r for r in res if r]


def write_sample_stls(out_dir):
    """검증용 샘플 3종을 STL 로 저장해 대조 표본 수를 늘린다."""
    from src.core.model_loader import generate_sample_models
    src = os.path.join(out_dir, '_samples')
    os.makedirs(src, exist_ok=True)
    paths = []
    for k, d in generate_sample_models().items():
        fp = os.path.join(src, f'sample_{k}.stl')
        d['mesh'].export(fp)
        paths.append(fp)
    return paths


def open_folder(path):
    """결과 폴더를 탐색기에서 연다."""
    try:
        full = os.path.abspath(path)
        if sys.platform.startswith('win'):
            os.startfile(full)
        elif sys.platform == 'darwin':
            import subprocess
            subprocess.run(['open', full], check=False)
    except Exception:
        pass


def explain(stl_path, process='FDM', printer=(300, 300, 340), unit='mm', report_path=None):
    """Show safe partial results; never ray-cast an invalid mesh for diagnostics."""
    mesh = load_model(stl_path, unit=unit)['mesh']
    result = AMRuleEngine().evaluate(mesh, process, (0, 0, 1), printer)
    print(f"파일: {os.path.basename(stl_path)} · 단위: {unit}")
    print(f"검사 범위: {result.analysis_scope} · 상태: {result.evaluation_status}")
    for key in ('boundary_edges', 'nonmanifold_edges', 'duplicate_faces', 'degenerate_faces'):
        if key in result.mesh_diagnostics:
            print(f"  {key}: {result.mesh_diagnostics[key]}")
    print(result.summary)
    for gate in result.gates:
        print(f"[{gate.status}] {gate.name}: {gate.detail}")
    if result.partial_metrics:
        print(json.dumps(result.partial_metrics, ensure_ascii=False, default=lambda v: v.tolist()))
    for rule in result.rule_results:
        print(f"  {rule.label}: {rule.value} {rule.unit} · {rule.detail}")
    print(f"종합 점수: {result.total_score} · {result.grade}")
    review = result.layer_review
    if review.get('status') not in ('not_applicable', 'not_requested'):
        print(f"FDM 단면 검토: {review.get('status')} · 확정 단면 {review.get('complete_layers',0)}/{review.get('expected_layers',0)}층")
        for check in review.get('checks', []):
            print(f"  {check['name']}: {check['status']} · 검토 영역이 있는 층 {check.get('risk_layers','—')}")
        if review.get('reason'):
            print(review['reason'])
    if report_path:
        save_new_json(report_path, dict(runtime=runtime_record(), source_sha256=file_sha256(stl_path),
                                       source_unit=unit, result=result))
        print(f"진단 JSON: {Path(report_path).resolve()}")
    return result


def main():
    ap = argparse.ArgumentParser(description="Cura 대조 외부 검증 도구")
    sub = ap.add_subparsers(dest='cmd', required=True)

    e = sub.add_parser('export', help='방향별 STL 과 기록표 생성')
    e.add_argument('--stl', nargs='*', default=None,
                   help='생략하면 파일 선택 창이 열린다')
    e.add_argument('--no-samples', action='store_true',
                   help='샘플 모델 3종을 함께 내보내지 않는다')
    e.add_argument('--out', default=None, help='생략하면 cura_runs 아래 새 실험 폴더 생성')
    e.add_argument('--process', default='FDM')
    e.add_argument('--unit', choices=list(UNIT_SCALE), default='mm', help='입력 STL 단위')
    e.add_argument('--filament', type=float, default=1.75, help='Cura 필라멘트 지름(mm)')
    e.add_argument('--printer', nargs=3, type=float, default=[300, 300, 340],
                   help='빌드 볼륨 X Y Z (기본: Ender-3 Max)')

    d_ = sub.add_parser('why', help='메시 진단·부분 분석·프로필 판정 근거 설명')
    d_.add_argument('--stl', nargs='?', default=None)
    d_.add_argument('--process', default='FDM')
    d_.add_argument('--unit', choices=list(UNIT_SCALE), default='mm')
    d_.add_argument('--report', default=None, help='진단 JSON을 새 파일로 저장')
    d_.add_argument('--printer', nargs=3, type=float, default=[300, 300, 340])

    a = sub.add_parser('analyze', help='기록표 분석')
    a.add_argument('--csv', nargs='?', default=None,
                   help='생략하면 파일 선택 창이 열린다')
    a.add_argument('--filament', type=float, default=None,
                   help='기록이 없는 CSV에 적용할 필라멘트 지름(mm); 생략 시 1.75mm 가정 표시')
    a.add_argument('--recompute-terms', action='store_true',
                   help='현재 엔진으로 형상 항을 새로 계산해 별도 비교 (과거 결과 재현 아님)')
    a.add_argument('--bridge-limit', type=float, default=None,
                   help='현재 형상 항 재계산에만 적용할 브리지 한계(mm)')
    a.add_argument('--out', default=None, help='분석 JSON 저장 경로; 기존 파일 덮어쓰기 금지')

    args = ap.parse_args()

    if args.cmd == 'export':
        if args.out is None:
            args.out = os.path.join('cura_runs', datetime.now(timezone.utc).strftime('run_%Y%m%d_%H%M%S_%f'))
        paths = list(args.stl or [])
        if not paths:
            picked = pick_files("슬라이싱할 STL 파일을 고르세요 (여러 개 선택 가능)",
                                [("STL 파일", "*.stl"), ("모든 파일", "*.*")])
            paths = list(picked)
        if not paths and args.no_samples:
            print("선택된 파일이 없다. 종료한다.")
            return
        with tempfile.TemporaryDirectory(prefix='am-dfm-samples-') as samples_temp:
            if not args.no_samples and args.unit == 'mm':
                paths += write_sample_stls(samples_temp)
            elif not args.no_samples:
                print('내장 샘플은 mm 단위이므로 이번 단위 설정에서는 자동 추가하지 않습니다.')
            if not paths:
                print('내보낼 모델이 없습니다. --stl로 파일을 지정하세요.')
                return 1
            csv_path = export(paths, args.out, args.process, tuple(args.printer),
                              unit=args.unit, filament_dia=args.filament)
        open_folder(args.out)
        print()
        print("다음 순서")
        print("  1) 열린 폴더의 STL 을 Cura 로 하나씩 불러온다 (모델을 회전시키지 말 것)")
        print("  2) 서포트 OFF 로 Slice -> 필라멘트 길이(m) 를 적는다")
        print("  3) 서포트 ON  으로 Slice -> 필라멘트 길이(m) 를 적는다")
        print("  4) measurements.csv 에 두 값을 채운다")
        print("  5) 5_CURA_ANALYZE.bat 을 실행한다")
    elif args.cmd == 'why':
        path = args.stl
        if not path:
            picked = pick_files("진단할 STL 을 고르세요",
                                [("STL 파일", "*.stl"), ("모든 파일", "*.*")], multiple=False)
            path = picked[0] if picked else None
        if not path:
            print("선택된 파일이 없다. 종료한다.")
            return
        explain(path, args.process, tuple(args.printer), args.unit, args.report)

    else:
        csv_path = args.csv
        if not csv_path:
            picked = pick_files("작성한 measurements.csv 를 고르세요",
                                [("CSV 파일", "*.csv"), ("모든 파일", "*.*")],
                                multiple=False)
            csv_path = picked[0] if picked else None
        if not csv_path:
            print("선택된 파일이 없다. 종료한다.")
            return
        report = analyze(csv_path, args.filament, recompute_terms=args.recompute_terms,
                         bridge_limit=args.bridge_limit)
        output = args.out or str(Path(csv_path).parent / 'analysis_results' /
                 (Path(csv_path).stem + '_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f') + '.json'))
        save_new_json(output, report)
        print(f'\n분석 결과 저장: {Path(output).resolve()}')
        if report['status'] != 'ok':
            return 1
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError, RuntimeError, np.linalg.LinAlgError) as exc:
        print(f'오류: {exc}', file=sys.stderr)
        sys.exit(1)
