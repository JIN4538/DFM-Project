"""Traceable feature priorities and conservative scopes for partial sections."""


def meaningful_regions(geometry, grid):
    """Remove coordinate-roundoff only; a display threshold must not erase data."""
    import shapely as sh
    return [p for p in sh.get_parts(geometry)
            if p.area > max(8*grid*p.length, grid*grid*16)]


def classify_regions(material, residual, width, grid, prefix, wholly_affected,
                     max_details=50):
    """Record every numerical candidate and apply a display policy consistently.

    The 1% line-width-square cutoff is not a calibrated manufacturing limit.
    A whole affected material component stays prominent at any size. The caller
    supplies that condition for its measurement; erosion is only a thin-feature
    condition and must not be reused to classify support or layer persistence.
    """
    import shapely as sh
    candidates = meaningful_regions(residual, grid)
    # Empty residuals are common. Avoid indexing every material component when
    # there are no candidates to associate with them.
    parts = list(sh.get_parts(material)) if candidates else []
    tree = sh.STRtree(parts)
    affected = {}
    major, minor, records = [], [], []
    floor = .01 * width**2
    for region in sorted(candidates, key=lambda p: (-p.area, *p.bounds)):
        whole = False
        for j in tree.query(region.representative_point(), predicate='within'):
            j = int(j)
            if j not in affected:
                affected[j] = bool(wholly_affected(parts[j]))
            whole = whole or affected[j]
        prominent = region.area >= floor or whole
        (major if prominent else minor).append(region)
        if len(records) < max_details:
            item = dict(priority='review' if prominent else 'detail',
                        area_mm2=float(region.area), perimeter_mm=float(region.length),
                        area_perimeter_scale_mm=float(2*region.area/region.length) if region.length else None,
                        bounds_mm=list(region.bounds), whole_component_affected=whole)
            if prefix == 'thin':
                item['whole_component_lost'] = whole  # v2.5 compatibility
            records.append(item)
    metrics = {
        prefix+'_area_mm2': float(sum(p.area for p in major)),
        prefix+'_regions': len(major),
        prefix+'_detail_area_mm2': float(sum(p.area for p in minor)),
        prefix+'_detail_regions': len(minor),
        prefix+'_candidate_area_mm2': float(sum(p.area for p in candidates)),
        prefix+'_candidate_regions': len(candidates),
        prefix+'_display_floor_mm2': float(floor),
        prefix+'_details': records,
        prefix+'_details_truncated': len(candidates) > max_details,
    }
    return major, minor, metrics


def classify_thin_regions(material, residual, width, grid, max_details=50):
    """Planar offset loss; 2A/P is a shape scale, not local wall thickness."""
    return classify_regions(
        material, residual, width, grid, 'thin',
        lambda p: p.buffer(-width/2, join_style='mitre', mitre_limit=5).is_empty,
        max_details)


def classify_difference_regions(material, reference, width, grid, prefix,
                                max_details=50):
    """Classify missing support or layer persistence in an already-known scope.

    No interior area shared with the reference means the entire component is
    affected. Boundary-only contact is not positive area support. Uncertainty
    must be excluded by comparison_scope before calling this function.
    """
    import shapely as sh
    if prefix not in ('unsupported', 'single_layer'):
        raise ValueError('Difference classification requires a support or layer check.')
    residual = material.difference(reference)
    return classify_regions(
        material, residual, width, grid, prefix,
        lambda p: not sh.relate_pattern(p, reference, '2********'), max_details)


def comparison_scope(material, neighbor_rows, reach=0.0):
    """Exclude entire components touching uncertainty in any neighboring plane.

    None denotes an unexamined neighbor. An incomplete plane with no localized
    bounds is globally unknown. No unsupported/one-layer finding is inferred
    from that missing information. Complete empty air layers are valid neighbors.
    """
    import shapely as sh
    unknown=[]
    for row in neighbor_rows:
        if row is None:return sh.GeometryCollection()
        if row['complete']:continue
        bounds=row['diagnostics'].get('unknown_bounds_mm',[])
        if not bounds:return sh.GeometryCollection()
        unknown.extend(sh.box(*b).buffer(reach) if reach else sh.box(*b) for b in bounds)
    if not unknown:return material
    tree=sh.STRtree(unknown)
    return sh.union_all([p for p in sh.get_parts(material)
                         if not len(tree.query(p,predicate='intersects'))])
