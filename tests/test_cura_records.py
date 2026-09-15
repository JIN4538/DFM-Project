"""Recorded Cura evidence and failure cases that previously lost reproducibility."""
import contextlib
import copy
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import trimesh

import cura_check
from src.core.cura_records import analyze_records
from src.core.model_loader import generate_sample_models, load_model
from src.core.reproducibility import file_sha256, json_text, save_new_json
from src.core.validation_metrics import cross_validate, metrics
from src.processes.additive import PROCESS_PARAMS, ProcessType

ROOT = Path(__file__).resolve().parents[1]
DIRECTIONS = ['posZ', 'negZ', 'posX', 'negX', 'posY', 'negY']


def synthetic_rows(n=12):
    result = []
    for i in range(n):
        v, p = float((i + 1) ** 2), float(i + 1)
        y = .2 * v + .3 * p
        result.append(dict(file=f'part{i//6}__{DIRECTIONS[i%6]}.stl', orientation=DIRECTIONS[i%6],
                           process='FDM', pred_support_mm3=y, cura_len_no_support_m=0,
                           cura_len_with_support_m=y / (1000 * np.pi),
                           vol_term=v, perim_term=p, area_term=1))
    return result


def write_csv(directory, rows):
    path = Path(directory) / 'measurements.csv'
    columns = list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader(); writer.writerows(rows)
    return path


class CuraRecordsRegression(unittest.TestCase):
    def analyze_rows(self, rows, **kwargs):
        with tempfile.TemporaryDirectory() as td:
            path = write_csv(td, rows)
            return analyze_records(path, filament_dia=2, **kwargs)

    def test_original_measurements_reproduce_r2_without_current_geometry(self):
        path = ROOT / 'cura_run' / 'measurements.csv'
        before = path.read_bytes()
        with patch('src.core.geometry_analyzer.support_terms', side_effect=AssertionError('no current geometry')) as fn:
            report = analyze_records(path)
        fn.assert_not_called()
        self.assertEqual(report['reading']['measured_rows'], 24)
        self.assertEqual(report['n'], 24)
        self.assertAlmostEqual(report['raw_r2'], .9784086106593225, places=12)
        self.assertAlmostEqual(report['mae'], 943.966599520746, places=7)
        self.assertAlmostEqual(report['prediction']['nonzero']['r2'], .9740608097454286, places=12)
        self.assertEqual(report['model_comparisons'], [])
        self.assertEqual(before, path.read_bytes())

    def test_old_csv_retains_nist_measurements_and_recovers_directions(self):
        report = analyze_records(ROOT / 'cura_run' / 'd.csv')
        self.assertEqual(report['reading']['measured_rows'], 24)
        self.assertEqual(report['n'], 18)
        self.assertEqual(sum(r['pred'] is None for r in report['rows']), 6)
        self.assertTrue(all(r['orientation'] in DIRECTIONS for r in report['rows']))
        self.assertAlmostEqual(report['scaled_fit_r2'], .9932450765255217, places=12)

    def test_missing_prediction_does_not_drop_valid_measurement_from_fit(self):
        rows = synthetic_rows(); rows[0]['pred_support_mm3'] = ''
        report = self.analyze_rows(rows)
        self.assertEqual(report['n'], 11)
        comparison = report['model_comparisons'][0]['result']
        self.assertEqual(comparison['n'], 12)
        beta = comparison['models']['volume_perimeter']['coefficients']
        self.assertAlmostEqual(beta['a'], .2)
        self.assertAlmostEqual(beta['b'], .3)

    def test_part_cross_validation_holds_out_all_six_directions(self):
        report = self.analyze_rows(synthetic_rows())
        cv = report['model_comparisons'][0]['result']['validation']['leave_one_part_out']
        self.assertAlmostEqual(cv['q2'], 1)
        self.assertEqual([(f['train_n'], f['test_n']) for f in cv['folds']], [(6, 6), (6, 6)])
        for fold in cv['folds']:
            np.testing.assert_allclose(fold['coefficients'], [.2, .3], atol=1e-12)

    def test_rank_deficient_training_fold_does_not_publish_full_q2(self):
        x = np.array([[1,2], [2,4], [3,6], [1,1], [2,1], [3,1]], dtype=float)
        y = x @ [.2, .3]
        cv = cross_validate(x, y, ['a']*3 + ['b']*3, {'a':'a','b':'b'})['leave_one_part_out']
        self.assertEqual(cv['status'], 'incomplete')
        self.assertEqual(cv['evaluated_n'], 3)
        self.assertIsNone(cv['q2'])

    def test_all_zero_target_has_no_r2_and_serializes_as_null(self):
        rows = synthetic_rows()
        for row in rows:
            row['pred_support_mm3'] = row['cura_len_with_support_m'] = 0
        report = self.analyze_rows(rows)
        self.assertIsNone(report['r2']); self.assertEqual(report['mae'], 0)
        text = json_text(report)
        self.assertNotIn('NaN', text); self.assertNotIn('Infinity', text)
        self.assertIsNone(json.loads(text)['r2'])

    def test_invalid_numeric_measurements_are_not_silently_ignored(self):
        for value in ['NaN', 'inf', '-1', 'invalid']:
            rows = synthetic_rows(); rows[2]['cura_len_with_support_m'] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, '4행'):
                self.analyze_rows(rows)

    def test_off_greater_than_on_is_rejected(self):
        rows = synthetic_rows(); rows[0]['cura_len_no_support_m'] = 1
        with self.assertRaisesRegex(ValueError, 'ON 길이'):
            self.analyze_rows(rows)

    def test_unfinished_rows_are_counted(self):
        rows = synthetic_rows(); rows[0]['cura_len_with_support_m'] = ''
        report = self.analyze_rows(rows)
        self.assertEqual(report['reading']['total_rows'], 12)
        self.assertEqual(report['reading']['measured_rows'], 11)
        self.assertEqual(report['reading']['skipped'][0]['line'], 2)

    def test_duplicate_measurement_is_rejected(self):
        rows = synthetic_rows(); rows.append(copy.deepcopy(rows[0]))
        with self.assertRaisesRegex(ValueError, '중복'):
            self.analyze_rows(rows)

    def test_filename_and_orientation_conflict_is_rejected(self):
        rows = synthetic_rows(); rows[0]['orientation'] = 'negZ'
        with self.assertRaisesRegex(ValueError, '파일명 방향'):
            self.analyze_rows(rows)

    def test_parent_or_absolute_stl_paths_are_rejected(self):
        for name in ['../outside.stl', '/tmp/outside.stl', 'C:\\outside.stl']:
            rows = synthetic_rows(); rows[0]['file'] = name
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, '경로'):
                self.analyze_rows(rows)

    def test_invalid_and_partial_terms_are_rejected(self):
        for value in ['NaN', -1, '']:
            rows = synthetic_rows(); rows[0]['perim_term'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.analyze_rows(rows)

    def test_recorded_diameter_conflict_is_rejected(self):
        rows = synthetic_rows(); rows[0]['filament_diameter_mm'] = 1.75
        with self.assertRaisesRegex(ValueError, '기록된 지름'):
            self.analyze_rows(rows)

    def test_mixed_cura_conditions_are_fitted_separately(self):
        rows = synthetic_rows()
        for i, row in enumerate(rows):
            row['cura_version'] = 'recorded-test-version'
            row['cura_settings_id'] = 'settings_a' if i < 6 else 'settings_b'
            row['part_id'] = 'shared-family'
        report = self.analyze_rows(rows)
        self.assertEqual(len(report['model_comparisons']), 2)
        self.assertEqual([c['result']['n'] for c in report['model_comparisons']], [6, 6])
        self.assertEqual(len(report['prediction']['by_part']), 2)

    def test_profile_term_prediction_mismatch_is_rejected(self):
        rows = synthetic_rows()
        rows[0]['profile_json'] = json.dumps(PROCESS_PARAMS[ProcessType.FDM])
        rows[0]['pred_support_mm3'] = 1000000
        with self.assertRaisesRegex(ValueError, '예측 부피가 다릅니다'):
            self.analyze_rows(rows)

    def test_changed_stl_hash_is_detected_before_using_stored_numbers(self):
        rows = synthetic_rows(); rows[0]['stl_sha256'] = '0'*64
        with tempfile.TemporaryDirectory() as td:
            path = write_csv(td, rows)
            (Path(td) / rows[0]['file']).write_bytes(b'changed content')
            with self.assertRaisesRegex(ValueError, 'STL 해시'):
                analyze_records(path, filament_dia=2)

    def test_explicit_recompute_does_not_stop_after_one_missing_stl(self):
        rows = synthetic_rows(6)
        with tempfile.TemporaryDirectory() as td:
            path = write_csv(td, rows)
            for row in rows[1:]:
                trimesh.creation.box([40,30,20]).export(Path(td) / row['file'])
            report = analyze_records(path, filament_dia=2, recompute_terms=True, bridge_limit=0)
        self.assertIsNone(report['rows'][0]['terms'])
        self.assertTrue(all(r['terms'] is not None for r in report['rows'][1:]))
        self.assertTrue(all(r['term_basis'] == 'current-recomputed' for r in report['rows']))
        self.assertEqual(report['current_prediction']['raw']['n'], 5)
        self.assertTrue(all(r['current_pred'] == 0 for r in report['rows'][1:]))
        self.assertTrue(all(r['pred'] > 0 for r in report['rows']))

    def test_analysis_output_cannot_overwrite_measurements(self):
        with tempfile.TemporaryDirectory() as td:
            path = write_csv(td, synthetic_rows())
            before = path.read_bytes()
            with self.assertRaises(FileExistsError):
                save_new_json(path, {'result': 1})
            self.assertEqual(path.read_bytes(), before)


class CuraExportRegression(unittest.TestCase):
    def export(self, paths, out, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return cura_check.export(paths, str(out), **kwargs)

    def test_export_never_overwrites_completed_measurements(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / 'existing'; out.mkdir()
            original = out / 'measurements.csv'; original.write_text('user measurement')
            with self.assertRaises(FileExistsError):
                self.export(['anything.stl'], out)
            self.assertEqual(original.read_text(), 'user measurement')

    def test_saved_terms_and_prediction_match_reloaded_stl_and_hash(self):
        from src.core import geometry_analyzer as ga
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / 'part.stl'
            generate_sample_models()['moderate']['mesh'].export(source)
            out = Path(td) / 'experiment'
            csvp = self.export([str(source)], out, orientations={'+X':(1,0,0)})
            with open(csvp, encoding='utf-8-sig') as stream:
                row = next(csv.DictReader(stream))
            mesh = load_model(str(out / row['file']))['mesh']
            profile = json.loads(row['profile_json'])
            terms = ga.support_terms(mesh, profile['critical_angle'], profile['bridge_limit'])
            for key in ('vol_term','perim_term','area_term'):
                self.assertAlmostEqual(float(row[key]), terms[key])
            self.assertEqual(row['stl_sha256'], file_sha256(out / row['file']))
            predicted = profile['support_density']*terms['vol_term'] + profile['support_wall']*terms['perim_term']
            self.assertEqual(float(row['pred_support_mm3']), round(predicted, 1))
            self.assertTrue((out / 'experiment.json').is_file())

    def test_failed_export_does_not_publish_partial_experiment(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td)/'part.stl'; trimesh.creation.box([40,30,20]).export(source)
            out = Path(td)/'out'
            with patch('src.core.geometry_analyzer.support_terms', side_effect=RuntimeError('injected')):
                with self.assertRaises(RuntimeError):
                    self.export([str(source)], out, orientations={'+X':(1,0,0)})
            self.assertFalse(out.exists())
            self.assertTrue(source.is_file())

    def test_same_basename_files_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            paths=[]
            for i, size in enumerate([10,20]):
                directory=Path(td)/str(i); directory.mkdir()
                path=directory/'part.stl'; trimesh.creation.box([size,size,size]).export(path); paths.append(str(path))
            csvp=self.export(paths,Path(td)/'out',orientations={'+X':(1,0,0)})
            with open(csvp,encoding='utf-8-sig') as stream:
                rows=list(csv.DictReader(stream))
            self.assertEqual(len({r['file'].casefold() for r in rows}),2)
            self.assertEqual(len({r['part_id'] for r in rows}),2)

    def test_centimeter_input_is_exported_in_mm(self):
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/'cm.stl'; trimesh.creation.box([4,3,2]).export(source)
            out=Path(td)/'out'
            csvp=self.export([str(source)],out,orientations={'one':(0,0,1)},unit='cm')
            with open(csvp,encoding='utf-8-sig') as stream:
                row=next(csv.DictReader(stream))
            np.testing.assert_allclose(load_model(str(out/row['file']))['mesh'].extents,[40,30,20])
            self.assertEqual(row['unit'],'mm');self.assertEqual(row['source_unit'],'cm')


if __name__ == '__main__':
    unittest.main()
