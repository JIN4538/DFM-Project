"""Independent OCCT through passages, parallel repeats and interrupted walls.

Construct and freeze before model evaluation. Truth follows analytic cutter
surfaces, not the predictions. These cases do not cover circular through slots.
"""
from __future__ import annotations
import argparse,gzip,hashlib,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dfm.cad_graph import extract_graph


def build_case(sides,count,interrupted,radius,height,phase,offset):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox,BRepPrimAPI_MakeCylinder,BRepPrimAPI_MakePrism
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon,BRepBuilderAPI_MakeFace
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopoDS import TopoDS
    from OCP.GeomAbs import GeomAbs_Cylinder,GeomAbs_Plane
    from OCP.gp import gp_Pnt,gp_Vec,gp_Ax2,gp_Dir
    shape=BRepPrimAPI_MakeBox(gp_Pnt(-24,-20,-height/2),48,40,height).Shape()
    centers=[(0.,0.)] if count==1 else [(-offset,0.),(offset,0.)]
    polygons=[]
    for cx,cy in centers:
        if sides==0:
            tool=BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(cx,cy,-height),gp_Dir(0,0,1)),radius,height*2).Shape();polygons.append(None)
        else:
            points=np.array([(cx+radius*np.cos(t+phase),cy+radius*np.sin(t+phase)) for t in np.linspace(0,2*np.pi,sides,endpoint=False)])
            poly=BRepBuilderAPI_MakePolygon()
            for x,y in points:poly.Add(gp_Pnt(float(x),float(y),-height))
            poly.Close();tool=BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(poly.Wire()).Face(),gp_Vec(0,0,height*2)).Shape();polygons.append(points)
        cut=BRepAlgoAPI_Cut(shape,tool);cut.Build();shape=cut.Shape()
    if interrupted:
        width=2*(offset+radius+1) if count==2 else 2*(radius+1)
        tool=BRepPrimAPI_MakeBox(gp_Pnt(-width/2,-25,-height*.12),width,50,height*.24).Shape()
        cut=BRepAlgoAPI_Cut(shape,tool);cut.Build();shape=cut.Shape()
    if not BRepCheck_Analyzer(shape).IsValid():raise ValueError('Invalid independent construction')
    faces=[];ex=TopExp_Explorer(shape,TopAbs_FACE)
    while ex.More():
        f=TopoDS.Face_s(ex.Current())
        if not any(f.IsSame(old) for old in faces):faces.append(f)
        ex.Next()
    graph=extract_graph(shape,faces);truth=[]
    for (cx,cy),polygon in zip(centers,polygons):
        selected=[]
        for i,face in enumerate(faces):
            surface=BRepAdaptor_Surface(face,True)
            if sides==0 and surface.GetType()==GeomAbs_Cylinder:
                cylinder=surface.Cylinder();axis=cylinder.Axis();point=np.asarray(axis.Location().Coord());direction=np.asarray(axis.Direction().Coord())
                if abs(cylinder.Radius()-radius)<1e-7 and abs(direction[2])>1-1e-7 and np.linalg.norm(point[:2]-[cx,cy])<1e-7:selected.append(i)
            elif sides and surface.GetType()==GeomAbs_Plane:
                vertices=np.asarray(graph['measurements'][i]['vertex_points_mm'])
                if not len(vertices) or abs(surface.Plane().Axis().Direction().Z())>1e-7:continue
                for a,b in zip(polygon,np.roll(polygon,-1,axis=0)):
                    tangent=(b-a)/np.linalg.norm(b-a);normal=np.array([-tangent[1],tangent[0]])
                    if np.max(np.abs((vertices[:,:2]-a)@normal))<1e-7:selected.append(i);break
        expected=(1 if sides==0 else sides)*(2 if interrupted else 1)
        if len(selected)!=expected:raise ValueError(f'Analytic face truth mismatch: expected {expected}, got {len(selected)}')
        truth.append(dict(label={0:1,3:2,6:4}[sides],faces=selected))
    return shape,graph,truth


def generate(output):
    from OCP.STEPControl import STEPControl_Writer,STEPControl_AsIs
    output.mkdir(parents=True,exist_ok=False);rng=np.random.default_rng(847193)
    records=[]
    for sides in (0,3,6):
        for count in (1,2):
            for interrupted in (False,True):
                for repeat in range(5):
                    radius=float(rng.uniform(2.2,4.1));height=float(rng.uniform(18,35));phase=float(rng.uniform(0,2*np.pi));offset=float(rng.uniform(8,12))
                    shape,graph,truth=build_case(sides,count,interrupted,radius,height,phase,offset)
                    ident=f'cad-{sides}-{count}-{int(interrupted)}-{repeat}'
                    path=output/f'{ident}.step';writer=STEPControl_Writer();writer.Transfer(shape,STEPControl_AsIs);writer.Write(str(path))
                    m=graph['measurements'];np.savez_compressed(output/f'{ident}.npz',x=graph['x'],edges=graph['edges'],centroids=[v['centroid_mm'] for v in m],normals=[v['normal'] for v in m],areas=[v['area_mm2'] for v in m],scale=graph['scale_mm'])
                    records.append(dict(id=ident,truth=truth,scope='curved' if sides==0 else 'planar',parameters=dict(sides=sides,count=count,interrupted=interrupted,radius=radius,height=height,phase=phase,offset=offset),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    manifest=dict(seed=847193,cases=len(records),truth_scope='Analytic cutter surfaces, independent of model outputs; three through classes, no circular-through-slot claim',
        generated_before_evaluation=True,generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),records=records)
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8');print(json.dumps(dict(cases=len(records),source_sha=manifest['generator_sha256'])),flush=True)


def evaluate(output,model_path):
    from threadpoolctl import threadpool_limits
    from dfm.feature_localization import load_model as load_joint,predict_localization
    from dfm.feature_instance_refinement import load_model,group_records,pair_inputs,predict_affinity
    from scripts.train_feature_instance_affinity import metrics
    manifest=json.loads((output/'manifest.json').read_text(encoding='utf8'));head,backbone=load_joint();model=load_model(model_path)
    records=[];scores=[]
    with threadpool_limits(limits=1):
        for record in manifest['records']:
            with np.load(output/f"{record['id']}.npz",allow_pickle=False) as z:g={k:z[k] for k in z.files}
            p=predict_localization(g,head,backbone);groups=group_records(g,p,head['edge_threshold']);x,pairs=pair_inputs(g,groups,backbone)
            row=dict(record,groups=groups,pairs=pairs,start=len(scores),count=len(pairs));scores.extend(predict_affinity(x,model));records.append(row)
    scores=np.asarray(scores)
    results=dict(cases=len(records),model_sha256=hashlib.sha256(model_path.read_bytes()).hexdigest(),proposed=metrics(records,scores,model['merge_threshold'],model['class_thresholds']),
        no_merge=metrics(records,scores,1.1,model['class_thresholds']),by_stratum={})
    for kind in ('single','repeated','interrupted','continuous'):
        subset=[r for r in records if (r['parameters']['count']==1 if kind=='single' else r['parameters']['count']==2 if kind=='repeated' else r['parameters']['interrupted'] if kind=='interrupted' else not r['parameters']['interrupted'])]
        results['by_stratum'][kind]=metrics(subset,scores,model['merge_threshold'],model['class_thresholds'])
    (output/'evaluation.json').write_text(json.dumps(results,indent=2),encoding='utf8')
    with gzip.open(output/'evaluated-records.json.gz','wt',encoding='utf8') as f:json.dump(records,f)
    print(json.dumps(results),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('generate','evaluate'));p.add_argument('--output',type=Path,required=True);p.add_argument('--model',type=Path)
    args=p.parse_args();generate(args.output) if args.mode=='generate' else evaluate(args.output,args.model)
