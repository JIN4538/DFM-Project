"""Attach only remeasured neural direction proposals to an AM report."""
from copy import deepcopy
import math

from .neural_orientation import enrich_orientations, _update_pareto
from .full_search import enrich_full as enrich_ensemble


def extend_review_orientations(model, profile, report, *, priority='balanced', enabled=True,
                               max_proposals=12, timeout_s=8.):
    result = deepcopy(report)
    previous_names = {p.get('name') for p in result.get('neural_search', {}).get('proposals', [])}
    baseline = [row for row in result.get('orientations', [])
                if row.get('proposal_source') not in ('deep_neural_surrogate', 'geometric_facet_seed', 'exact_height_geometry')
                and row.get('name') not in previous_names]
    result['orientations'] = baseline
    reliable = (result.get('summary') or {}).get('review_status') == 'geometry_review'
    _update_pareto(baseline, profile, reliable)
    if not enabled:
        result['neural_search'] = {'status': 'disabled', 'added_count': 0}
        result.setdefault('orientation_search', {})['neural_added_count'] = 0
        return result
    extra = enrich_ensemble(model.mesh, profile, baseline, priority=priority,
                                max_proposals=max_proposals, timeout_s=timeout_s,
                                reliable_normals=reliable)
    extra['metadata']['measured_count']=extra['metadata']['added_count']
    _filter_subresolution_height_proposals(extra, baseline, profile, result.get('model', {}))
    result['orientations'] = extra['rows']
    result['neural_search'] = extra['metadata']
    result.setdefault('orientation_search', {}).update(
        neural_added_count=extra['metadata']['added_count'], continuous_optimum=False)
    return result


def _filter_subresolution_height_proposals(extra, baseline, profile, metadata):
    """Avoid height-only rotations driven by tiny CAD tessellation differences.

    The smaller of twice the linear deflection and 0.1% of baseline height is
    a disclosed proposal-screening policy, NOT a certified geometric error
    bound. The relative cap preserves meaningful gains on small planar parts.
    Raw queried dimensions remain in the audit record; no measurement changes.
    """
    if profile.process != 'PBF_POLYMER' or metadata.get('source_format', '').lower() not in ('step', 'stp'):
        return
    tessellation = metadata.get('tessellation') or {}
    value = tessellation.get('requested_linear_deflection_mm')
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        return
    selected_body = metadata.get('selected_body')
    attempts = [r.get('effective_deflection_mm') for r in tessellation.get('body_attempts', [])
                if isinstance(r, dict) and (selected_body is None or r.get('body_id') == selected_body)]
    effective = [x for x in attempts if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0]
    usable = [r['height_mm'] for r in baseline if r.get('build_fit') is not False
              and (profile.build_volume_mm is None or r.get('build_fit') is True)
              and r.get('candidate_role') != 'current_only'
              and not isinstance(r.get('height_mm'), bool)
              and isinstance(r.get('height_mm'), (int, float)) and math.isfinite(r['height_mm'])]
    if not usable:
        return  # A new direction can still resolve an existing build-space failure.
    minimum = min(usable)
    threshold = min(2 * (max(effective) if effective else value), .001 * minimum)
    sources = ('deep_neural_surrogate', 'geometric_facet_seed', 'exact_height_geometry')
    omitted = [r['name'] for r in extra['rows'] if r.get('proposal_source') in sources
               and r.get('build_fit') is not False
               and isinstance(r.get('height_mm'), (int, float)) and not isinstance(r['height_mm'], bool)
               and math.isfinite(r['height_mm']) and 0 <= minimum-r['height_mm'] <= threshold]
    if not omitted:
        return
    extra['rows'] = [r for r in extra['rows'] if r.get('name') not in omitted]
    _update_pareto(extra['rows'], profile, True)
    record = extra['metadata']
    if record.get('selection_reference_rows'):
        record['selection_reference_rows'] = [r for r in record['selection_reference_rows'] if r.get('name') not in omitted]
    record['measured_count'] = record['added_count']
    record['added_count'] -= len(omitted)
    record['height_resolution_filter'] = dict(omitted_names=omitted, threshold_mm=threshold,
        basis='min(2 * CAD linear deflection, 0.001 * baseline height); proposal-screening policy, not certified error bound',
        baseline_minimum_height_mm=minimum)
