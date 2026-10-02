"""Preserve existing measured proposals and add queries from broader learning."""
from pathlib import Path
import time
import numpy as np
from .neural_orientation import (enrich_orientations,load_model,baseline_descriptor,proposal_pool,
    predict_surrogates,proposal_scores,choose_proposals,_update_pareto,MAX_FACES)
from .orientation import measure_orientation

EXPANDED_MODEL=Path(__file__).resolve().parents[1]/'data/models/neural_orientation_external_v3.json'

def enrich_ensemble(mesh,profile,baseline_rows,*,priority='balanced',max_proposals=12,timeout_s=8.,reliable_normals=True):
    started=time.monotonic()
    result=enrich_orientations(mesh,profile,baseline_rows,priority=priority,max_proposals=max_proposals,
                               timeout_s=timeout_s,reliable_normals=reliable_normals)
    record=result['metadata'];record['ensemble_models']=[]
    if record.get('model_id'):record['ensemble_models'].append(dict(id=record['model_id'],sha256=record['model_sha256']))
    # Existing measurements remain intact even when a new model is absent or
    # rejected. Small explicit budgets remain exactly bounded for callers.
    if max_proposals!=12 or record['status'] not in ('complete','partial') or time.monotonic()-started>=timeout_s or len(mesh.faces)>MAX_FACES:return result
    try:
        model=load_model(EXPANDED_MODEL);height_only=profile.process=='PBF_POLYMER'
        descriptor=baseline_descriptor(mesh,baseline_rows,require_overhang=not height_only)
        directions,sources=proposal_pool(mesh,baseline_rows)
        old=np.array([r['direction'] for r in result['rows']])
        available=np.array([i for i,d in enumerate(directions) if np.max(old@d)<1-1e-10 and sources[i]=='sphere'],dtype=int)
        predictions=predict_surrogates(model,descriptor,directions,profile.overhang_angle_deg,height_only=height_only)
        scores=proposal_scores(predictions,descriptor,priority=priority,height_only=height_only)
        selected=[int(available[i]) for i in choose_proposals(directions[available],scores[available],6)] if len(available) else []
        record['ensemble_models'].append(dict(id=model['model_id'],sha256=model['sha256']))
        record['expanded_model_id']=model['model_id'];record['expanded_added_count']=0
        record['requested_count']+=len(selected)
        for index in selected:
            if time.monotonic()-started>=timeout_s:break
            row=measure_orientation(mesh,directions[index],profile,reliable_normals=reliable_normals);row.pop('overhang_face_indices',None)
            name=f"AI 확장 {record['expanded_added_count']+1}"
            row.update(name=name,candidate_role='search',proposal_source='deep_neural_surrogate',neural_model_sha256=model['sha256'])
            predicted={'height_mm':float(predictions['height'][index]*descriptor['diagonal_mm'])}
            if not height_only:predicted['overhang_projected_area_sum_mm2']=float(predictions['overhang'][index]*descriptor['area_mm2'])
            record['proposals'].append(dict(name=name,direction=row['direction'],pool_source='sphere',selection_source='deep_neural_surrogate',
                model_id=model['model_id'],model_sha256=model['sha256'],predicted=predicted,measured={k:row[k] for k in predicted},build_fit=row['build_fit']))
            result['rows'].append(row);record['expanded_added_count']+=1;record['neural_query_count']+=1;record['added_count']+=1
        record['status']='complete' if record['added_count']==record['requested_count'] else 'partial'
        record['elapsed_s']=time.monotonic()-started;record['search_policy']='retain existing 12 measured proposals; up to 6 new neural queries; shared wall-clock budget'
        _update_pareto(result['rows'],profile,reliable_normals)
    except (OSError,ValueError,KeyError,TypeError,IndexError,OverflowError) as e:
        record['expanded_model_unavailable_reason']=str(e)
    return result
