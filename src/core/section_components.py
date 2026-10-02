"""Safe shortcuts and isolated closed-component recovery for planar linework."""
import numpy as np


def graph_data(segments):
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    points,inverse=np.unique(segments.reshape((-1,2)),axis=0,return_inverse=True)
    ends=inverse.reshape((-1,2))
    edges=np.unique(np.sort(ends,axis=1),axis=0)
    graph=coo_matrix((np.ones(len(edges)),(edges[:,0],edges[:,1])),shape=(len(points),len(points))).tocsr()
    _,labels=connected_components(graph,directed=False)
    degrees=np.bincount(edges.ravel(),minlength=len(points))
    balance=np.bincount(ends[:,0],minlength=len(points))-np.bincount(ends[:,1],minlength=len(points))
    return points,ends,edges,labels,degrees,balance


def simple_ring(points,edges):
    import shapely as sh
    # Each vertex has exactly two distinct neighbours in this component.
    adjacency={}
    for a,b in edges:
        adjacency.setdefault(int(a),[]).append(int(b));adjacency.setdefault(int(b),[]).append(int(a))
    if not adjacency or any(len(v)!=2 for v in adjacency.values()): return None
    first=min(adjacency);previous=-1;current=first;cycle=[];seen=set()
    while current not in seen:
        seen.add(current);cycle.append(current)
        a,b=adjacency[current];nxt=a if a!=previous else b
        previous,current=current,nxt
    if current!=first or len(seen)!=len(adjacency) or len(cycle)<3:return None
    ring=sh.LinearRing(points[cycle])
    return ring if ring.is_simple and sh.Polygon(ring).area>0 else None


def component_rings(segments):
    points,ends,edges,labels,degrees,balance=graph_data(segments)
    groups=[];edge_groups=labels[edges[:,0]];segment_groups=labels[ends[:,0]]
    # Sort once; do not rescan all edges for every disconnected component.
    order=np.argsort(edge_groups,kind='stable');cuts=np.r_[0,np.flatnonzero(np.diff(edge_groups[order]))+1,len(edges)]
    for start,end in zip(cuts[:-1],cuts[1:]):
        local=edges[order[start:end]];vertices=np.unique(local)
        group=int(labels[vertices[0]])
        ring=None
        if np.all(degrees[vertices]==2) and np.all(balance[vertices]==0):
            ring=simple_ring(points,local)
        xy=points[vertices]
        groups.append(dict(group=group,ring=ring,bounds=(*xy.min(axis=0),*xy.max(axis=0))))
    return groups,segment_groups


def fast_linework(groups,max_pair_tests=100000):
    """Use exact endpoint loops only after simplicity and cross-ring checks.

    Shared endpoints, crossing loops, seams and excessive pair candidates fall
    back to general noding. Nested nonintersecting rings remain supported.
    """
    import shapely as sh
    if any(g['ring'] is None for g in groups):return None
    rings=np.asarray([g['ring'] for g in groups],dtype=object);tree=sh.STRtree(rings);tested=0
    for i,ring in enumerate(rings):
        ids=tree.query(ring);ids=ids[ids>i];tested+=len(ids)
        if tested>max_pair_tests:return None
        if len(ids) and np.any(sh.intersects(ring,rings[ids])):return None
    return rings


def isolated_material(segments,groups,segment_groups,orphan_points,grid,max_tests):
    """Keep whole closed rings only when separated from uncertain envelopes.

    A damaged inner cavity excludes its enclosing outer ring too. Bounding-box
    exclusion is intentionally conservative. There is no guessed total area,
    no gap closure and no claim about material outside the observed linework.
    """
    import shapely as sh
    from src.core.section_index import WindingIndex
    boxes=[sh.box(*g['bounds']).buffer(grid*4) for g in groups]
    boxes.extend(sh.Point(p).buffer(grid*4).envelope for p in orphan_points)
    tree=sh.STRtree(boxes)
    uncertain={i for i,g in enumerate(groups) if g['ring'] is None}
    uncertain.update(range(len(groups),len(boxes)))
    pending=list(uncertain)
    while pending:
        i=pending.pop()
        for j in tree.query(boxes[i]):
            j=int(j)
            if j not in uncertain:
                uncertain.add(j);pending.append(j)
    accepted=[g['group'] for i,g in enumerate(groups) if i not in uncertain]
    raw=segments[np.isin(segment_groups,accepted)]
    material=sh.GeometryCollection();tests=0
    if len(raw):
        lines=sh.union_all(sh.linestrings(raw),grid_size=grid)
        cells=list(sh.get_parts(sh.polygonize_full(sh.get_parts(lines))[0]))
        index=WindingIndex(raw,max_tests)
        points=[(c.representative_point().x,c.representative_point().y) for c in cells]
        material=sh.union_all([c for c,w in zip(cells,index.values(points)) if w]).simplify(grid*2,preserve_topology=True)
        tests=index.tests
    bounds=[list(boxes[i].bounds) for i in sorted(uncertain)]
    return material,bounds,len(accepted),tests
