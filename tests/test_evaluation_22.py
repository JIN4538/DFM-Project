"""Failure propagation and comparable-direction selection for v2.2."""
import copy
import json
import unittest
from unittest.mock import patch

import numpy as np
import trimesh
from src.core import geometry_analyzer as ga
from src.core.model_loader import generate_sample_models
from src.core.reproducibility import json_text
from src.core.scoring import pick_best, find_optimal_orientation
from src.processes.additive import AMRuleEngine


class Evaluation22Regression(unittest.TestCase):
    def test_failed_region_partition_does_not_merge_all_overhangs(self):
        mesh=generate_sample_models()['moderate']['mesh']
        with patch('trimesh.graph.connected_components',side_effect=RuntimeError('injected')):
            result=ga.compute_support_volume(mesh,45,bridge_limit=0)
        self.assertFalse(result['available'])
        self.assertIn('연결 성분',result['reason'])

    def test_failed_boolean_generation_cannot_return_overlapping_samples(self):
        with patch('trimesh.boolean.union',side_effect=RuntimeError('injected')):
            with self.assertRaisesRegex(RuntimeError,'샘플 합집합 생성 실패'):
                generate_sample_models()

    def test_unknown_directions_are_not_reported_as_all_blocked(self):
        result=AMRuleEngine().evaluate(trimesh.Trimesh())
        result.evaluation_status='indeterminate'
        best=pick_best({'one':result})
        self.assertIsNone(best['best_orientation'])
        self.assertIn('판정 보류',best['note'])
        self.assertNotIn('모든 방향에서 하드',best['note'])

    def test_na_scope_difference_prevents_total_score_winner(self):
        engine=AMRuleEngine(); mesh=trimesh.creation.box([40,30,20])
        first=engine.evaluate(mesh)
        with patch.object(ga,'compute_feature_gap',return_value={'available':False,'reason':'injected'}):
            second=engine.evaluate(mesh)
        self.assertTrue(first.feasible and second.feasible)
        best=pick_best({'one':first,'two':second})
        self.assertIsNone(best['best_orientation'])
        self.assertFalse(best['comparable'])

    def test_find_optimal_orientation_propagates_gradient_option(self):
        mesh=trimesh.creation.box([40,30,20]); engine=AMRuleEngine()
        with patch.object(AMRuleEngine,'evaluate',wraps=engine.evaluate) as evaluate:
            find_optimal_orientation(mesh,orientations={'one':(0,0,1)},thickness_gradient_enabled=True)
        self.assertTrue(evaluate.call_args.kwargs['thickness_gradient_enabled'])

    def test_evaluation_json_is_portable_when_gap_is_infinite(self):
        result=AMRuleEngine().evaluate(trimesh.creation.box([40,30,20]))
        text=json_text({'result':result,'optional':[np.inf,np.nan,np.float64(1)]})
        self.assertNotIn('NaN',text);self.assertNotIn('Infinity',text)
        self.assertEqual(json.loads(text)['optional'],[None,None,1])


if __name__=='__main__':
    unittest.main()
