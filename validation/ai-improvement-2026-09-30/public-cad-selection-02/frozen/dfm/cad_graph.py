"""Label-free, scale/rotation invariant B-rep graph; training/runtime contract.

OCP is imported only in the worker. STEP names never enter model inputs.
Coordinates/areas are kept separately for exact CAD remeasurement.
"""
from __future__ import annotations
import numpy as np

SCHEMA = 'dfm-brep-graph-1'
FEATURES = ('plane','cylinder','cone','sphere','torus','other','area_fraction',
            'perimeter_over_scale','compactness','centroid_distance',
            'outward_radial_cosine','edge_count','wire_count','vertex_count',
            'spread_0','spread_1','spread_2','radius_over_scale',
            'degree','neighbor_cos_min','neighbor_cos_mean','neighbor_cos_max')

def extract_graph(shape, faces=None):
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX, TopAbs_WIRE, TopAbs_REVERSED
    from OCP.TopoDS import TopoDS
    from OCP.BRep import BRep_Tool
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Cone, GeomAbs_Sphere, GeomAbs_Torus
    def unique(parent, kind):
        ex=TopExp_Explorer(parent,kind); values=[]
        while ex.More():
            item=ex.Current()
            if not any(item.IsSame(old) for old in values): values.append(item)
            ex.Next()
        return values
    if faces is None: faces=[TopoDS.Face_s(f) for f in unique(shape,TopAbs_FACE)]
    if not 1 <= len(faces) <= 2000: raise ValueError('Graph face budget exceeded')
    props=GProp_GProps(); BRepGProp.VolumeProperties_s(shape,props)
    center=np.array(props.CentreOfMass().Coord()); volume=abs(props.Mass())
    surface=GProp_GProps(); BRepGProp.SurfaceProperties_s(shape,surface)
    total_area=surface.Mass(); scale=max(np.sqrt(total_area),1e-10)
    nodes=[]; measurements=[]; normals=[]; edges=[]; owners=[]
    for i,face in enumerate(faces):
        p=GProp_GProps(); BRepGProp.SurfaceProperties_s(face,p)
        area=p.Mass(); point=np.array(p.CentreOfMass().Coord())
        fe=unique(face,TopAbs_EDGE); vertices=unique(face,TopAbs_VERTEX)
        perimeter=0.
        for edge in fe:
            lp=GProp_GProps(); BRepGProp.LinearProperties_s(edge,lp); perimeter+=lp.Mass()
            k=next((j for j,old in enumerate(edges) if edge.IsSame(old)),None)
            if k is None: edges.append(edge); owners.append([i])
            else: owners[k].append(i)
        xyz=np.array([BRep_Tool.Pnt_s(TopoDS.Vertex_s(v)).Coord() for v in vertices])
        spread=np.zeros(3)
        if len(xyz)>1:
            spread=np.sqrt(np.maximum(0,np.linalg.eigvalsh((xyz-xyz.mean(0)).T@(xyz-xyz.mean(0))/len(xyz))))[::-1]/scale
        a=BRepAdaptor_Surface(face,True); typ=a.GetType(); radius=0.; normal=np.zeros(3)
        types=(GeomAbs_Plane,GeomAbs_Cylinder,GeomAbs_Cone,GeomAbs_Sphere,GeomAbs_Torus)
        onehot=[float(typ==t) for t in types]+[float(typ not in types)]
        if typ==GeomAbs_Plane:
            normal=np.array(a.Plane().Axis().Direction().Coord())
            if face.Orientation()==TopAbs_REVERSED: normal=-normal
        elif typ==GeomAbs_Cylinder: radius=a.Cylinder().Radius()
        elif typ==GeomAbs_Sphere: radius=a.Sphere().Radius()
        elif typ==GeomAbs_Torus: radius=a.Torus().MinorRadius()
        radial=point-center; radial_cos=float(normal@radial/max(np.linalg.norm(radial),1e-10))
        node=onehot+[area/total_area,perimeter/scale,4*np.pi*area/max(perimeter**2,1e-10),
                       float(np.linalg.norm(radial)/scale),radial_cos,len(fe)/12,
                       len(unique(face,TopAbs_WIRE))/4,len(vertices)/12,*spread,radius/scale]
        nodes.append(node); normals.append(normal)
        measurements.append(dict(face_id=i+1,area_mm2=float(area),perimeter_mm=float(perimeter),
                                 centroid_mm=point.tolist(),radius_mm=radius or None,
                                 normal=normal.tolist(),surface_kind=int(np.argmax(onehot)),
                                 vertex_points_mm=xyz.tolist()))
    pairs=set()
    for ids in owners:
        for i in ids:
            for j in ids:
                if i!=j: pairs.add((i,j))
    for i,node in enumerate(nodes):
        adjacent=[j for a,j in pairs if a==i]
        cos=[float(normals[i]@normals[j]) for j in adjacent]
        node.extend([len(adjacent)/12,min(cos,default=0),float(np.mean(cos)) if cos else 0,max(cos,default=0)])
    x=np.asarray(nodes,dtype=np.float32); e=np.array(sorted(pairs),dtype=np.int64).reshape(-1,2)
    if x.shape[1]!=len(FEATURES) or not np.isfinite(x).all(): raise ValueError('Invalid graph features')
    return dict(schema=SCHEMA,x=x,edges=e,measurements=measurements,volume_mm3=volume,area_mm2=total_area,scale_mm=scale)

def read_step_graph(path, labels=None, mapping='index'):
    from OCP.STEPControl import STEPControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopoDS import TopoDS
    from OCP.BRepCheck import BRepCheck_Analyzer
    reader=STEPControl_Reader()
    if reader.ReadFile(str(path))!=IFSelect_RetDone: raise ValueError('STEP read failed')
    reader.SetSystemLengthUnit(1.0); reader.TransferRoots(); shape=reader.OneShape()
    if not BRepCheck_Analyzer(shape).IsValid(): raise ValueError('Invalid CAD topology')
    ex=TopExp_Explorer(shape,TopAbs_FACE); faces=[]
    while ex.More():
        face=TopoDS.Face_s(ex.Current())
        if not any(face.IsSame(old) for old in faces): faces.append(face)
        ex.Next()
    graph=extract_graph(shape,faces)
    if labels is not None:
        names=[reader.WS().TransferReader().EntityFromShapeResult(face,1).Name().ToCString() for face in faces]
        if mapping=='index':
            ids=[int(name) for name in names]
            if sorted(ids)!=list(range(len(labels))): raise ValueError('Face names/labels not a permutation')
            graph['y']=np.array([labels[i] for i in ids],dtype=np.int64)
        elif mapping=='class': graph['y']=np.array([int(name) for name in names],dtype=np.int64)
        else: raise ValueError('Unverified face mapping')
    return graph
