"""Fit shape-local neural residuals using only already measured directions.

This module selects geometry queries; corrected predictions are never report
measurements. The frozen networks and their feature/measurement contracts stay
unchanged. A small kernel fit is rebuilt after each exact query.
"""
from __future__ import annotations

import time
import numpy as np

from .neural_orientation import predict_surrogates, proposal_scores


def residual_predictions(model, descriptor, directions, observed, angle, *,
                         height_only=False, width_deg=40., ridge=.05, strength=1.):
    """Correct an offline model with within-part observed residuals only."""
    directions=np.asarray(directions,dtype=float)
    predicted=predict_surrogates(model,descriptor,directions,angle,height_only=height_only)
    if strength==0:
        return predicted
    rows=[row for row in observed if row.get('candidate_role','search')=='search']
    measured_directions=np.asarray([row['direction'] for row in rows],dtype=float)
    fitted=predict_surrogates(model,descriptor,measured_directions,angle,height_only=height_only)
    width=1.-np.cos(np.deg2rad(width_deg))
    if not 0 < width or ridge <= 0 or not np.isfinite([width,ridge,strength]).all():
        raise ValueError('Finite positive residual width and ridge are required')
    for field,measurement,scale in (
            ('height','height_mm',descriptor['diagonal_mm']),
            ('overhang','overhang_projected_area_sum_mm2',descriptor['area_mm2'])):
        if field not in predicted:
            continue
        truth=np.array([row[measurement]/scale for row in rows],dtype=float)
        if not np.isfinite(truth).all():
            raise ValueError('Residual observations must be finite measured values')
        dot=measured_directions@measured_directions.T
        query_dot=directions@measured_directions.T
        # Height is unchanged by turning a build axis upside down. Downward
        # area has no such symmetry, and must keep the sign of the direction.
        if field=='height':
            dot=np.abs(dot)
            query_dot=np.abs(query_dot)
        kernel=np.exp((np.minimum(dot,1.)-1.)/width)
        coefficients=np.linalg.solve(kernel+ridge*np.eye(len(rows)),truth-fitted[field])
        correction=np.exp((np.minimum(query_dot,1.)-1.)/width)@coefficients
        predicted[field]=np.clip(predicted[field]+strength*correction,0.,1.)
    return predicted


def adaptive_queries(model,descriptor,directions,sources,observed,angle,measure,*,
                     priority='balanced',height_only=False,budget=6,deadline=float('inf'),
                     width_deg=40.,ridge=.05,strength=1.,facet_reserve=0,warm_start=()):
    """Select at most `budget` exact queries from one fixed candidate pool.

    A completed query is the sole source of the next residual observation.
    Existing rows are not mutated; same-call near duplicates are avoided.
    """
    directions=np.asarray(directions,dtype=float)
    results=[]
    old=np.asarray([row['direction'] for row in observed],dtype=float)
    available=np.max(directions@old.T,axis=1)<1.-1e-8
    acquired=[]
    for iteration in range(budget):
        if time.monotonic()>=deadline or not available.any():
            break
        predicted=residual_predictions(model,descriptor,directions,observed+results,angle,
            height_only=height_only,width_deg=width_deg,ridge=ridge,strength=strength)
        scores=proposal_scores(predicted,descriptor,priority=priority,height_only=height_only)
        allowed=available.copy()
        reserved=None
        if iteration < len(warm_start):
            dots=directions@np.asarray(warm_start[iteration])
            selected=int(np.argmax(dots))
            if dots[selected] > 1.-1e-8 and available[selected]:
                reserved=selected
        if reserved is None and iteration < facet_reserve:
            facets=allowed & np.array([source=='facet' for source in sources])
            if facets.any():
                allowed=facets
        indices=np.flatnonzero(allowed)
        index=reserved if reserved is not None else int(indices[np.argmin(scores[indices])])
        if time.monotonic()>=deadline:
            break
        row=measure(directions[index])
        results.append(row)
        acquired.append(dict(pool_index=index,pool_source=sources[index],
            prediction={key:float(values[index]) for key,values in predicted.items()},
            observations=len(observed)+len(results)-1))
        available &= directions@directions[index] < np.cos(np.deg2rad(8.))
    return results,acquired
