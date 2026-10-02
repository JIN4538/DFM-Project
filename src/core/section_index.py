"""Bounded spatial queries for section winding and monotonically rising planes."""
import numpy as np


class WindingLimit(RuntimeError):
    pass


class WindingIndex:
    """Same signed crossing rule as the exhaustive oracle, fewer candidate edges.

    STRtree indexes bounding boxes, not material truth. Exact half-open crossing
    tests still decide the winding. Overlapping data can remain quadratic, so
    the cumulative candidate budget is retained.
    """
    def __init__(self, segments, max_tests=8000000):
        import shapely as sh
        self.segments = np.asarray(segments, dtype=float)
        self.tree = sh.STRtree(sh.linestrings(self.segments))
        self.right = float(self.segments[:,:,0].max()) if len(segments) else 0.0
        self.max_tests = int(max_tests)
        self.tests = 0

    def values(self, points):
        import shapely as sh
        out=[]
        for x,y in points:
            if x > self.right or not len(self.segments):
                out.append(0); continue
            ids=self.tree.query(sh.LineString([(x,y),(self.right+1.0,y)]))
            if self.tests+len(ids)>self.max_tests:
                raise WindingLimit('단면 내부 판별의 누적 계산 한도를 초과했습니다.')
            self.tests+=len(ids)
            a,b=self.segments[ids,0],self.segments[ids,1]
            left=(b[:,0]-a[:,0])*(y-a[:,1])-(x-a[:,0])*(b[:,1]-a[:,1])
            w=np.count_nonzero((a[:,1]<=y)&(b[:,1]>y)&(left>0))
            w-=np.count_nonzero((a[:,1]>y)&(b[:,1]<=y)&(left<0))
            out.append(w)
        return np.asarray(out,dtype=int)


class FaceZIndex:
    """Sorted face intervals: random queries plus an incremental layer sweep."""
    def __init__(self, mesh):
        # Capture once per immutable build-frame mesh, not at every plane.
        self.scale_mm = float(np.max(mesh.extents))
        z=mesh.vertices[:,2]
        self.projection=z.copy()
        self.low=z[mesh.faces].min(axis=1);self.high=z[mesh.faces].max(axis=1)
        self.lo=np.argsort(self.low,kind='stable');self.hi=np.argsort(self.high,kind='stable')
        self.sorted_low=self.low[self.lo];self.sorted_high=self.high[self.hi]
        self.active=set();self.add=0;self.remove=0;self.last=-np.inf

    def query(self,z,tolerance=0.0):
        a=np.searchsorted(self.sorted_low,z+tolerance,side='right')
        b=np.searchsorted(self.sorted_high,z-tolerance,side='left')
        if a<=len(self.high)-b:
            ids=self.lo[:a];ids=ids[self.high[ids]>=z-tolerance]
        else:
            ids=self.hi[b:];ids=ids[self.low[ids]<=z+tolerance]
        return np.sort(ids)

    def sweep(self,z,tolerance=1e-8):
        if z<self.last: raise ValueError('증분 단면 조회는 오름차순 높이만 지원합니다.')
        a=np.searchsorted(self.sorted_low,z+tolerance,side='right')
        b=np.searchsorted(self.sorted_high,z-tolerance,side='left')
        self.active.update(map(int,self.lo[self.add:a]))
        self.active.difference_update(map(int,self.hi[self.remove:b]))
        self.add,self.remove,self.last=a,b,z
        return np.array(sorted(self.active),dtype=int)
