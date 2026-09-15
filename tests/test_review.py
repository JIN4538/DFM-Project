"""Regression cases found during the full-source review. python -m unittest discover -s tests -v"""
import contextlib
import copy
import csv
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import trimesh
from src.core import geometry_analyzer as ga
from src.core.model_loader import load_model
from src.core.scoring import evaluate_orientations, results_to_rows, pareto_front, sensitivity_analysis
from src.processes.additive import AMRuleEngine, PROCESS_PARAMS, ProcessType, BASE_WEIGHTS, provenance_report
import cura_check


def box(extents, center=(0,0,0)):
    m=trimesh.creation.box(extents=extents); m.apply_translation(center); return m


def sealed():
    return trimesh.boolean.difference([box([40,40,40]), box([20,20,20])])


class ReviewRegression(unittest.TestCase):
    def setUp(self):
        self.engine=AMRuleEngine(); self.box=box([40,30,20])

    def test_stl_roundtrip_preserves_cavity_and_material_volume(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'sealed.stl'; sealed().export(path)
            m=load_model(str(path))['mesh']
            self.assertAlmostEqual(m.volume,56000)
            tv=ga.compute_trapped_volume(m)
            self.assertEqual(tv['n_cavities'],1)
            self.assertAlmostEqual(tv['trapped_volume'],8000)
            self.assertAlmostEqual(tv['trapped_ratio'],8000/56000)
            r=self.engine.evaluate(m,'SLS')
            self.assertTrue(any(g.name=='갇힌 체적' and not g.passed for g in r.gates))
            self.assertTrue(self.engine.evaluate(m,'FDM').feasible)

    def test_single_inverted_shell_can_be_repaired_on_load(self):
        m=self.box.copy(); m.invert()
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'inverted.stl'; m.export(p)
            self.assertGreater(load_model(str(p))['mesh'].volume,0)

    def test_swapped_xy_uses_same_placement_for_gate_and_score(self):
        f=ga.compute_build_volume_fit(box([180,80,20]),[100,200,100])
        self.assertTrue(f['fits']); self.assertEqual(f['placement_rotation_deg'],90)
        self.assertAlmostEqual(f['utilization'],.9)
        self.assertEqual(f['margin'],[20,20,80])

    def test_wall_distribution_is_area_weighted(self):
        w=ga.compute_wall_thickness(box([60,40,2]))
        self.assertAlmostEqual(w['median_thickness'],2)
        self.assertAlmostEqual(w['p_thickness'],2)

    def test_detection_samples_do_not_bias_percentile(self):
        pin=trimesh.creation.cylinder(radius=.15,height=10,sections=48)
        pin.apply_translation([30,30,15])
        m=trimesh.boolean.union([box([80,80,20]),pin])
        w=ga.compute_wall_thickness(m)
        self.assertLess(w['min_thickness'],.4)
        self.assertGreater(w['p_thickness'],19)
        self.assertFalse(self.engine.evaluate(m).feasible)

    def test_bad_input_is_rejected_before_geometry(self):
        m=trimesh.Trimesh(vertices=self.box.vertices,faces=self.box.faces[:-1],process=False)
        with patch.object(ga,'run_full_analysis',side_effect=AssertionError('must not execute')):
            r=self.engine.evaluate(m)
        self.assertEqual(r.evaluation_status,'invalid_input'); self.assertIsNone(r.total_score)

    def test_nonfinite_mesh(self):
        m=self.box.copy(); m.vertices[0,0]=np.nan
        self.assertEqual(self.engine.evaluate(m).evaluation_status,'invalid_input')

    def test_invalid_dimensions_and_directions(self):
        for dims in [(np.nan,250,250),(np.inf,250,250),(0,1,1)]:
            with self.subTest(dims=dims), self.assertRaises(ValueError):
                self.engine.evaluate(self.box,printer_dims=dims)
        for d in [(0,0,0),(np.nan,0,1),(0,1),(0,0,np.inf)]:
            with self.subTest(direction=d), self.assertRaises(ValueError):
                self.engine.evaluate(self.box,build_direction=d)

    def test_invalid_weights(self):
        for w in [{},dict(BASE_WEIGHTS,wall_thickness=-1),dict(BASE_WEIGHTS,wall_thickness=np.nan),dict.fromkeys(BASE_WEIGHTS,0)]:
            with self.subTest(weights=w), self.assertRaises(ValueError):
                self.engine.evaluate(self.box,weights=w)

    def test_active_weight_sum_and_coverage(self):
        r=self.engine.evaluate(self.box,ProcessType.FDM)
        self.assertAlmostEqual(sum(x.weight for x in r.rule_results),1,places=14)
        self.assertAlmostEqual(r.coverage,.84)
        self.assertEqual(r.total_score,100)

    def test_weights_only_on_unmeasured_rules_give_no_score(self):
        w=dict.fromkeys(BASE_WEIGHTS,0); w['horizontal_hole']=1
        r=self.engine.evaluate(self.box,weights=w)
        self.assertEqual(r.evaluation_status,'indeterminate'); self.assertIsNone(r.total_score)

    def test_wall_measurement_failure_is_unknown(self):
        with patch.object(ga,'compute_wall_thickness',return_value={'available':False,'reason':'injected failure'}):
            r=self.engine.evaluate(self.box)
        self.assertEqual(r.evaluation_status,'indeterminate'); self.assertIsNone(r.total_score)

    def test_one_thin_sample_is_not_automatically_passed(self):
        w=ga.compute_wall_thickness(self.box)
        w['thicknesses'][0]=.2; w['min_thickness']=.2
        with patch.object(ga,'compute_wall_thickness',return_value=w):
            r=self.engine.evaluate(self.box)
        self.assertEqual(r.evaluation_status,'indeterminate'); self.assertIsNone(r.total_score)

    def test_support_failure_is_not_silently_plate_distance(self):
        with patch.object(ga,'support_regions',side_effect=RuntimeError('injected failure')):
            r=self.engine.evaluate(self.box)
        self.assertEqual(r.evaluation_status,'indeterminate'); self.assertIsNone(r.total_score)

    def test_aabb_overlap_is_not_solid_overlap(self):
        a=box([20,2,5]); a.apply_transform(trimesh.transformations.rotation_matrix(np.pi/4,[0,0,1]))
        b=a.copy(); b.apply_translation([-3,3,0])
        m=trimesh.util.concatenate([a,b])
        self.assertIsNone(self.engine._bodies_overlap(m))
        self.assertTrue(self.engine.evaluate(m).feasible)

    def test_actual_overlap_is_rejected(self):
        m=trimesh.util.concatenate([self.box,box([20,20,20],[5,5,5])])
        self.assertEqual(self.engine.evaluate(m).evaluation_status,'invalid_input')

    def test_negative_disjoint_shell_is_not_a_cavity(self):
        b=box([10,10,10],[100,0,0]);b.invert()
        r=self.engine.evaluate(trimesh.util.concatenate([self.box,b]))
        self.assertEqual(r.evaluation_status,'indeterminate')

    def test_orientation_table_handles_missing_rules(self):
        good=self.engine.evaluate(self.box)
        bad=self.engine.evaluate(trimesh.Trimesh())
        rows=results_to_rows({'good':good,'bad':bad})
        self.assertEqual(rows[0]['bad'],'N/A')
        self.assertEqual(results_to_rows({}),[{'규칙':'프로필 판정'},{'규칙':'종합 점수'}])

    def test_pareto_empty_single_and_different_na_sets(self):
        self.assertFalse(pareto_front({})['weight_free'])
        r=self.engine.evaluate(self.box)
        self.assertFalse(pareto_front({'a':r})['weight_free'])
        q=copy.deepcopy(r);q.rule_results[0].score=None
        self.assertFalse(pareto_front({'a':r,'b':q})['comparable'])

    def test_sensitivity_reuses_geometry_and_propagates_options(self):
        with patch.object(AMRuleEngine,'evaluate',wraps=self.engine.evaluate) as evaluate:
            out=sensitivity_analysis(self.box,n_trials=20,thickness_gradient_enabled=True)
        self.assertEqual(evaluate.call_count,1)
        self.assertTrue(evaluate.call_args.kwargs['thickness_gradient_enabled'])
        self.assertEqual(out['n_trials'],20)

    def test_sensitivity_matches_full_reweighting(self):
        seed=22; n=8; delta=.5
        out=sensitivity_analysis(self.box,seed=seed,n_trials=n,delta=delta)
        rng=np.random.default_rng(seed);scores=[]
        for _ in range(n):
            w={k:v*(1+rng.uniform(-delta,delta)) for k,v in BASE_WEIGHTS.items()}
            scores.append(self.engine.evaluate(self.box,weights=w).total_score)
        self.assertAlmostEqual(out['score_min'],min(scores));self.assertAlmostEqual(out['score_max'],max(scores))

    def test_orientation_options_propagate(self):
        with patch.object(AMRuleEngine,'evaluate',wraps=self.engine.evaluate) as evaluate:
            evaluate_orientations(self.box,orientations={'one':(0,0,1)},thickness_gradient_enabled=True)
        self.assertTrue(evaluate.call_args.kwargs['thickness_gradient_enabled'])

    def test_voxel_resolution_failure_is_na(self):
        r=ga.compute_min_feature_size(box([100,100,100]),.1,enabled=True)
        self.assertFalse(r['available'])

    def test_near_plate_overhang_is_not_contact(self):
        floor=box([4,4,.1],[0,0,.05]); plate=box([20,20,1],[0,0,1.0])
        m=trimesh.util.concatenate([floor,plate,box([1,1,100],[30,0,50])])
        r=ga.compute_overhang(m,45)
        self.assertGreater(r['overhang_area'],390)

    def test_bridge_span_uses_anchored_direction(self):
        # A 20mm long, 2mm wide beam anchored at its long ends is NOT a 2mm bridge.
        a=box([4,6,20],[-12,0,10]);b=box([4,6,20],[12,0,10]);beam=box([28,2,2],[0,0,21])
        m=trimesh.boolean.union([a,b,beam])
        self.assertEqual(len(ga.compute_overhang(m,45,bridge_limit=3)['bridges']),0)
        self.assertGreater(ga.compute_overhang(m,45,bridge_limit=25)['bridged_area'],0)

    def test_process_specific_provenance(self):
        rows=provenance_report('SLA')
        self.assertTrue(all(r['공정']=='SLA' and r['등급']=='판단' for r in rows))

    def test_cura_export_matches_engine_bridge_policy(self):
        m=trimesh.boolean.union([box([6,20,30],[-3.5,0,15]),box([6,20,30],[3.5,0,15]),box([13,20,4],[0,0,32])])
        with tempfile.TemporaryDirectory() as td, contextlib.redirect_stdout(io.StringIO()):
            p=Path(td)/'bridge.stl';m.export(p)
            csvp=cura_check.export([str(p)],str(Path(td)/'out'),orientations={'one':(0,0,1)})
            with open(csvp,encoding='utf-8-sig') as f: row=next(csv.DictReader(f))
            self.assertEqual(float(row['pred_support_mm3']),0)
            self.assertEqual(float(row['vol_term']),0)
            self.assertIn('bridge_limit',row['profile_json'])

    def test_cura_ties_and_unscaled_prediction_error(self):
        rows=[]
        for i,(p,m) in enumerate([(1,1),(1,2),(2,2),(2,4)]):
            rows.append(dict(file=f'x{i}.stl',orientation='posZ',process='FDM',pred_support_mm3=p,
                cura_len_no_support_m=0,cura_len_with_support_m=m/(1000*np.pi),vol_term=1,perim_term=1,area_term=1))
        with tempfile.TemporaryDirectory() as td, contextlib.redirect_stdout(io.StringIO()):
            path=Path(td)/'m.csv'
            with path.open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
            r=cura_check.analyze(str(path),filament_dia=2)
        from scipy.stats import spearmanr
        self.assertAlmostEqual(r['spearman'],spearmanr([1,1,2,2],[1,2,2,4]).statistic)
        self.assertAlmostEqual(r['mae'],.75)
        self.assertEqual(r['raw_r2'],r['r2'])
        self.assertLess(r['raw_r2'],r['scaled_fit_r2'])

    def test_ahp_requires_complete_positive_pairwise_data(self):
        from src.core.weights import ahp
        with self.assertRaises(ValueError): ahp(['a','b','c'],{('a','b'):2})
        with self.assertRaises(ValueError): ahp(['a','b'],{('a','b'):float('nan')})
        r=ahp(['a','b','c'],{('a','b'):2,('a','c'):4,('b','c'):2})
        self.assertAlmostEqual(r['weights']['a'],4/7)
        self.assertTrue(r['consistent'])

    def test_regression_preserves_predictive_parameters(self):
        from src.core.weights import regress_weights
        X=np.arange(30,dtype=float).reshape(-1,1); y=100-2*X[:,0]
        r=regress_weights(X,y,['wall'])
        pred=r['intercept']+((X[:,0]-r['feature_mean'][0])/r['feature_scale'][0])*r['coefficients']['wall']
        np.testing.assert_allclose(pred,y)
        self.assertLess(r['coefficients']['wall'],0)

if __name__=='__main__':
    unittest.main()
