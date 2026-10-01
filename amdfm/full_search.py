"""Full-corpus neural continuous refinement with retained measured candidates."""
from pathlib import Path
from copy import deepcopy
import time
import numpy as np
from .ensemble_search import enrich_ensemble
from .neural_orientation import (load_model, baseline_descriptor, proposal_pool, predict_surrogates,
    proposal_scores, choose_proposals, _update_pareto, MAX_FACES)
from .orientation import direction_from_angles, direction_angles, measure_orientation
MODEL_PATH = Path(__file__).resolve().parents[1]/'data/models/neural_orientation_external_v4.json'


def refined_directions(model, descriptor, directions, angle, priority, height_only, deadline):
    from scipy.optimize import minimize
    predicted = predict_surrogates(model, descriptor, directions, angle, height_only=height_only)
    scores = proposal_scores(predicted, descriptor, priority=priority, height_only=height_only)
    seeds = choose_proposals(directions, scores, 12)
    output = []
    def objective(parameters):
        if time.monotonic() >= deadline:
            raise TimeoutError('Neural refinement budget exhausted')
        d = direction_from_angles(float(parameters[0]), float(parameters[1]))
        p = predict_surrogates(model, descriptor, np.array([d]), angle, height_only=height_only)
        return float(proposal_scores(p, descriptor, priority=priority, height_only=height_only)[0])
    for index in seeds:
        if time.monotonic() >= deadline:
            break
        angles = direction_angles(directions[index])
        try:
            fit = minimize(objective, angles, method='L-BFGS-B', bounds=((0., 180.), (0., 360.)),
                options={'maxiter': 24, 'maxfun': 90, 'eps': 1e-4, 'ftol': 1e-9})
        except TimeoutError:
            break
        if np.isfinite(fit.x).all() and np.isfinite(fit.fun):
            output.append((float(fit.fun), direction_from_angles(*fit.x)))
    return [d for _, d in sorted(output, key=lambda r: r[0])]


def enrich_full(mesh, profile, baseline_rows, *, priority='balanced', max_proposals=12, timeout_s=8., reliable_normals=True):
    start = time.monotonic()
    result = enrich_ensemble(mesh, profile, baseline_rows, priority=priority, max_proposals=max_proposals,
        timeout_s=timeout_s, reliable_normals=reliable_normals)
    record = result['metadata']
    if max_proposals != 12 or record['status'] not in ('complete', 'partial') or len(mesh.faces) > MAX_FACES or time.monotonic()-start >= timeout_s:
        return result
    try:
        model = load_model(MODEL_PATH)
        height_only = profile.process == 'PBF_POLYMER'
        if not height_only and not model['angle_range_deg'][0] <= profile.overhang_angle_deg <= model['angle_range_deg'][1]:
            record['full_model_unavailable_reason'] = 'Angle outside full-corpus training domain'
            return result
        descriptor = baseline_descriptor(mesh, baseline_rows, require_overhang=not height_only)
        directions, _ = proposal_pool(mesh, baseline_rows)
        old = [np.asarray(r['direction']) for r in result['rows']]
        available = np.array([d for d in directions if max(float(d@v) for v in old) < 1-1e-10])
        if not len(available):
            return result
        deadline = min(start+timeout_s*.75, time.monotonic()+.7)
        refined = refined_directions(model, descriptor, available, profile.overhang_angle_deg, priority, height_only, deadline)
        prediction = predict_surrogates(model, descriptor, available, profile.overhang_angle_deg, height_only=height_only)
        scores = proposal_scores(prediction, descriptor, priority=priority, height_only=height_only)
        # Low-score discrete queries remain available when local optimization
        # stops early. Diversity avoids six nearly identical neural minima.
        options = refined + [available[i] for i in np.argsort(scores, kind='stable')[:40]]
        selected = []
        for d in options:
            if any(float(d@v) > 1-1e-8 for v in old+selected):
                continue
            if selected and max(float(d@v) for v in selected) > np.cos(np.deg2rad(8.)):
                continue
            selected.append(d)
            if len(selected) >= 6:
                break
        record['ensemble_models'].append(dict(id=model['model_id'], sha256=model['sha256']))
        record.update(full_model_id=model['model_id'], full_added_count=0, continuous_refined_candidates=len(refined))
        record['requested_count'] += len(selected)
        def append_query(d, *, guided=None):
            p = predict_surrogates(model, descriptor, np.array([d]), profile.overhang_angle_deg, height_only=height_only)
            row = measure_orientation(mesh, d, profile, reliable_normals=reliable_normals)
            row.pop('overhang_face_indices', None)
            counter = 'guided_added_count' if guided is not None else 'full_added_count'
            pure_geometry = guided is not None and guided['learned_component'] is None
            name = ('AI 보완 방향 ' if guided is not None else 'AI 정밀 방향 ') + str(record[counter]+1)
            row.update(name=name, candidate_role='search', proposal_source='exact_height_geometry' if pure_geometry else 'deep_neural_surrogate', neural_model_sha256=model['sha256'])
            if guided is not None:
                row['acquisition_method'] = guided['policy']
                row['learned_acquisition_component'] = guided['learned_component']
            predicted = dict(height_mm=float(p['height'][0]*descriptor['diagonal_mm']))
            if not height_only:
                predicted['overhang_projected_area_sum_mm2'] = float(p['overhang'][0]*descriptor['area_mm2'])
            record['proposals'].append(dict(name=name, direction=row['direction'], pool_source='geometry_guided_pool' if guided is not None else 'continuous_refinement',
                selection_source='exact_height_geometry' if pure_geometry else 'geometry_guided_neural' if guided is not None else 'deep_neural_surrogate', model_id=model['model_id'], model_sha256=model['sha256'],
                predicted=predicted, measured={k: row[k] for k in predicted}, build_fit=row['build_fit']))
            result['rows'].append(row)
            record[counter] += 1
            record['added_count'] += 1
            if pure_geometry:
                record['geometry_query_count'] = record.get('geometry_query_count', 0) + 1
            else:
                record['neural_query_count'] += 1
        for d in selected:
            if time.monotonic()-start >= timeout_s:
                break
            append_query(d)
        # Retain every old query. Up to six more scoped acquisition queries
        # use only the remaining original deadline. Keep the original measured
        # comparison range, so adding a candidate cannot change its scales.
        guided = None
        try:
            from .geometry_guided_search import rank_geometry_guided_queries
            known = [np.asarray(r['direction']) for r in result['rows']]
            common = [d for d in available if not any(float(d@v)>1-1e-8 for v in known)]
            for d in refined:
                if not any(float(d@v)>1-1e-8 for v in known+common):
                    common.append(d)
            guided = rank_geometry_guided_queries(mesh, model, descriptor, common, profile,
                priority=priority, budget=6, deadline=start+timeout_s, reliable_normals=reliable_normals)
            if guided is not None:
                reference = deepcopy(result['rows'])
                record.update(geometry_guided_acquisition=guided,guided_added_count=0)
                # Set before the first query: a later bounded/native failure
                # must retain the same scales for earlier successful queries.
                record['selection_reference_rows'] = reference
                record['selection_reference_policy'] = 'Frozen measured search before extra acquisition; preserve old candidates and comparison scales'
                record['requested_count'] += len(guided['directions'])
                for d in guided['directions']:
                    if time.monotonic()-start >= timeout_s:
                        break
                    append_query(np.asarray(d),guided=guided)
        except (OSError, ValueError, KeyError, TypeError, IndexError, OverflowError) as error:
            record['geometry_guided_unavailable_reason'] = str(error)
        record['status'] = 'complete' if record['added_count'] == record['requested_count'] else 'partial'
        record['elapsed_s'] = time.monotonic()-start
        record['search_policy'] = ('Retain all previous measured candidates; up to six extra exact-height/contact plus neural-area queries; fixed comparison scales and one shared deadline'
            if guided is not None else 'Retain previous measured candidates; up to six full-corpus neural continuous queries; one shared deadline')
        _update_pareto(result['rows'], profile, reliable_normals)
    except (OSError, ValueError, KeyError, TypeError, IndexError, OverflowError) as error:
        record['full_model_unavailable_reason'] = str(error)
    return result
