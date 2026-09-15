"""Contracts for partial analysis, non-destructive cleanup and thin-feature risk."""
import copy
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import trimesh

import cura_check
from src.core import geometry_analyzer as ga
from src.core.mesh_diagnostics import inspect_mesh, cleanup_preview, mesh_digest
from src.core.model_loader import load_model
from src.core.reproducibility import json_text
from src.core.scoring import pick_best, sensitivity_analysis
from src.processes.additive import AMRuleEngine


def box(dims=(40, 30, 20)):
    return trimesh.creation.box(dims)


def open_box():
    b = box()
    b.update_faces(np.arange(len(b.faces)-1))
    return b


class MeshReview23(unittest.TestCase):
    def setUp(self):
        self.engine = AMRuleEngine()

    def test_closed_looking_nonmanifold_is_distinct_from_open_boundary(self):
        b = box()
        m = trimesh.Trimesh(b.vertices, np.vstack([b.faces, b.faces[:1]]), process=False)
        d = inspect_mesh(m)
        self.assertEqual(d['boundary_edges'], 0)
        self.assertEqual(d['nonmanifold_edges'], 3)
        self.assertEqual(d['duplicate_faces'], 1)
        r = self.engine.evaluate(m)
        self.assertNotIn('닫혀 있지', r.summary)
        self.assertIn('3개 이상 면', r.summary)
        self.assertEqual(r.analysis_scope, 'partial')

    def test_partial_metrics_do_not_invoke_solid_analysis_or_supply_total(self):
        with patch.object(ga, 'run_full_analysis', side_effect=AssertionError('invalid mesh')):
            r = self.engine.evaluate(open_box(), printer_dims=[35, 50, 50])
        self.assertEqual(r.evaluation_status, 'invalid_input')
        self.assertEqual(r.analysis_scope, 'partial')
        self.assertFalse(r.feasible)
        self.assertIsNone(r.total_score)
        self.assertEqual(r.rule_results, [])
        self.assertEqual(r.coverage, 0)
        self.assertTrue(r.partial_metrics['build_volume_fit']['fits'])
        self.assertEqual(r.in_plane_rotation_deg, 90)

    def test_partial_does_not_mask_actual_size_failure(self):
        r = self.engine.evaluate(open_box(), printer_dims=[10, 10, 10])
        self.assertFalse(next(g for g in r.gates if g.name == '빌드 볼륨').passed)
        self.assertIsNone(pick_best({'partial': r})['best_orientation'])

    def test_nonfinite_and_empty_have_no_partial_geometry(self):
        bad = box(); bad.vertices[0, 0] = np.nan
        for m in (bad, trimesh.Trimesh()):
            r = self.engine.evaluate(m)
            self.assertEqual(r.analysis_scope, 'none')
            self.assertEqual(r.partial_metrics, {})
            self.assertIsNone(r.total_score)

    def test_broken_face_index_is_an_input_error(self):
        b = box(); f = b.faces.copy(); f[0, 0] = 999
        m = trimesh.Trimesh(b.vertices, f, process=False)
        r = self.engine.evaluate(m)
        self.assertEqual(r.analysis_scope, 'none')
        self.assertIn('인덱스', r.summary)

    def test_overflowing_extents_cannot_produce_partial_measurements(self):
        m = box((2, 2, 2)); m.vertices *= 1e308
        self.assertTrue(np.isfinite(m.vertices).all())
        with np.errstate(over='ignore', invalid='ignore'):
            r = self.engine.evaluate(m)
        self.assertEqual(r.analysis_scope, 'none')
        self.assertEqual(r.partial_metrics, {})

    def test_cleanup_export_after_cm_input_remains_mm_geometry(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/'cm.stl'; box((4, 3, 2)).export(p)
            mesh = load_model(str(p), unit='cm')['mesh']
            candidate, _ = cleanup_preview(mesh)
            out = Path(td)/'candidate_mm.stl'; candidate.export(out)
            reread = load_model(str(out), unit='mm')['mesh']
            np.testing.assert_allclose(reread.extents, [40, 30, 20])

    def test_cleanup_does_not_change_source_or_fill_holes(self):
        m = open_box(); before = mesh_digest(m)
        candidate, record = cleanup_preview(m)
        self.assertEqual(mesh_digest(m), before)
        self.assertFalse(candidate.is_watertight)
        self.assertEqual(record['before']['boundary_edges'], record['after']['boundary_edges'])
        self.assertEqual(record['removed_zero_area_faces'], 0)

    def test_cleanup_of_exact_same_winding_duplicate_preserves_box(self):
        b = box()
        m = trimesh.Trimesh(b.vertices, np.vstack([b.faces, b.faces[:1], [0, 0, 1]]), process=False)
        before = mesh_digest(m)
        candidate, record = cleanup_preview(m)
        self.assertEqual(mesh_digest(m), before)
        self.assertEqual(record['removed_zero_area_faces'], 1)
        self.assertEqual(record['removed_oriented_duplicates'], 1)
        self.assertTrue(candidate.is_watertight)
        self.assertAlmostEqual(candidate.volume, b.volume)
        self.assertTrue(self.engine.evaluate(candidate).feasible)
        self.assertEqual(record['analyzed_mesh_sha256'], mesh_digest(candidate))

    def test_opposite_winding_duplicate_is_retained_for_review(self):
        b = box()
        m = trimesh.Trimesh(b.vertices, np.vstack([b.faces, b.faces[:1, ::-1]]), process=False)
        candidate, record = cleanup_preview(m)
        self.assertEqual(record['removed_oriented_duplicates'], 0)
        self.assertEqual(record['after']['duplicate_faces'], 1)
        self.assertFalse(self.engine.evaluate(candidate).feasible)

    def test_tiny_positive_faces_are_not_deleted_by_area_threshold(self):
        b = box((.002, .003, .001))
        candidate, record = cleanup_preview(b)
        self.assertEqual(len(candidate.faces), len(b.faces))
        self.assertEqual(record['removed_zero_area_faces'], 0)
        self.assertAlmostEqual(candidate.volume, b.volume)

    def test_cleanup_preserves_cavity_and_small_isolated_component(self):
        outer = box(); inner = box((10, 10, 10)); inner.invert()
        small = box((.3, .3, .3)); small.apply_translation([100, 0, 0])
        m = trimesh.util.concatenate([outer, inner, small])
        candidate, _ = cleanup_preview(m)
        parts = candidate.split(only_watertight=False, repair=False)
        self.assertEqual(len(parts), 3)
        self.assertEqual(sum(p.volume < 0 for p in parts), 1)
        self.assertAlmostEqual(candidate.volume, m.volume)

    def test_all_degenerate_cleanup_stays_invalid(self):
        m = trimesh.Trimesh([[0, 0, 0], [1, 0, 0]], [[0, 0, 1]], process=False)
        candidate, record = cleanup_preview(m)
        self.assertFalse(record['after']['geometry_available'])
        self.assertIsNone(self.engine.evaluate(candidate).total_score)

    def test_analysis_never_implicitly_repairs_shells(self):
        m = trimesh.boolean.difference([box(), box((10, 10, 10))], engine='manifold')
        with patch('trimesh.Trimesh.fill_holes', side_effect=AssertionError('implicit repair')):
            self.assertTrue(self.engine.evaluate(m).feasible)

    def test_true_thin_wall_keeps_profile_failure(self):
        r = self.engine.evaluate(box((40, 30, .2)))
        self.assertEqual(r.evaluation_status, 'blocked')
        self.assertEqual(r.grade, '프로필 미충족')
        self.assertEqual(r.measurement_evidence['wall_thickness']['classification'], 'corroborated_thin_region')
        self.assertIsNone(r.total_score)

    def test_small_pin_is_not_ignored_due_to_small_surface_fraction(self):
        pin = trimesh.creation.cylinder(radius=.15, height=10, sections=48)
        pin.apply_translation([0, 0, 14.9])
        m = trimesh.boolean.union([box(), pin], engine='manifold')
        r = self.engine.evaluate(m)
        self.assertEqual(r.evaluation_status, 'blocked')
        self.assertIsNone(r.total_score)

    def test_duplicate_suspect_measurements_without_confirmation_do_not_prove_failure(self):
        b = box(); w = ga.compute_wall_thickness(b)
        w['thicknesses'][:2] = .2; w['min_thickness'] = .2
        with patch.object(ga, 'compute_wall_thickness', return_value=w):
            r = self.engine.evaluate(b)
        self.assertEqual(r.evaluation_status, 'indeterminate')
        self.assertIsNone(r.total_score)
        self.assertTrue(r.rule_results)

    def test_lost_near_surface_hits_do_not_pass_as_thick_material(self):
        w = ga.compute_wall_thickness(box()); w['discarded_near_hits'] = 1
        with patch.object(ga, 'compute_wall_thickness', return_value=w):
            r = self.engine.evaluate(box())
        self.assertEqual(r.evaluation_status, 'indeterminate')
        self.assertIsNone(r.total_score)

    def test_refinement_failure_keeps_suspect_state(self):
        b = box((40, 30, .2)); w = ga.compute_wall_thickness(b)
        with patch.object(b.ray, 'intersects_location', side_effect=RuntimeError('injected')):
            w['verification'] = ga.verify_thin_regions(b, w, .4)
        self.assertIn('실패', w['verification']['reason'])
        self.assertEqual(ga.wall_evidence(w, .4)['classification'], 'suspect_thin_region')

    def test_partial_json_has_counts_scope_and_no_fake_volume_rule(self):
        data = json.loads(json_text(self.engine.evaluate(open_box())))
        self.assertEqual(data['analysis_scope'], 'partial')
        self.assertGreater(data['mesh_diagnostics']['boundary_edges'], 0)
        self.assertIsNone(data['total_score'])
        self.assertEqual(data['rule_results'], [])

    def test_cli_why_uses_partial_geometry_and_no_unsafe_thickness(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/'open.stl'; open_box().export(p)
            out = Path(td)/'result.json'
            with patch.object(ga, 'compute_wall_thickness', side_effect=AssertionError('no rays')), contextlib.redirect_stdout(io.StringIO()):
                r = cura_check.explain(str(p), report_path=str(out))
            self.assertEqual(r.analysis_scope, 'partial')
            self.assertEqual(json.loads(out.read_text(encoding='utf-8'))['result']['analysis_scope'], 'partial')

    def test_partial_sensitivity_is_not_manufacturing_impossibility(self):
        r = sensitivity_analysis(open_box())
        self.assertIn('보류', r['note'])
        self.assertNotIn('인쇄 불가', r['note'])


if __name__ == '__main__':
    unittest.main()
