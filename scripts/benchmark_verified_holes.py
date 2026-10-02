"""Independent cutters and counterexamples, frozen before geometry evaluation."""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def build(kind, *, radius=3., height=12., count=1, rotated=False):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform, BRepBuilderAPI_MakeFace
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.gp import gp_Pnt, gp_Dir, gp_Ax2, gp_Ax1, gp_Trsf, gp_Vec
    box=BRepPrimAPI_MakeBox(gp_Pnt(-24,-18,0),48,36,height).Shape()
    expected=[]
    centers=np.linspace(-14,14,count) if count>1 else [0.]
    for x in centers:
        bottom=height*.4 if kind=='blind' else -2.
        if kind=='sealed':bottom=2.
        length=height+4 if kind!='sealed' else height-4
        pos=gp_Ax2(gp_Pnt(float(x),0,bottom),gp_Dir(0,0,1))
        if kind=='split':
            first=BRepPrimAPI_MakeCylinder(pos,radius,length,np.pi).Shape()
            transform=gp_Trsf();transform.SetRotation(gp_Ax1(gp_Pnt(float(x),0,0),gp_Dir(0,0,1)),np.pi)
            second=BRepBuilderAPI_Transform(first,transform,True).Shape()
            cutter=BRepAlgoAPI_Fuse(first,second).Shape()
        elif kind=='axial_split':
            first=BRepPrimAPI_MakeCylinder(pos,radius,height/2+2).Shape()
            second=BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(float(x),0,height/2),gp_Dir(0,0,1)),radius,height/2+2).Shape()
            cutter=BRepAlgoAPI_Fuse(first,second).Shape()
        else:cutter=BRepPrimAPI_MakeCylinder(pos,radius,length).Shape()
        if kind=='boss':box=BRepAlgoAPI_Fuse(box,cutter).Shape()
        else:box=BRepAlgoAPI_Cut(box,cutter).Shape()
        if kind in ('through','split','blind','remote_boss'):
            expected.append(dict(diameter_mm=2*radius, depth_mm=height*.6 if kind=='blind' else height,
                                 hole_kind='blind' if kind=='blind' else 'through'))
        if kind=='stepped':
            wide=BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(float(x),0,height*.55),gp_Dir(0,0,1)),radius*1.7,height).Shape()
            box=BRepAlgoAPI_Cut(box,wide).Shape()
        if kind=='cross':
            cross=BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(-30,0,height/2),gp_Dir(1,0,0)),radius,60).Shape()
            box=BRepAlgoAPI_Cut(box,cross).Shape()
    if kind=='remote_boss':
        boss=BRepPrimAPI_MakeBox(gp_Pnt(16,10,height),6,6,30).Shape()
        box=BRepAlgoAPI_Fuse(box,boss).Shape()
    if rotated:
        transform=gp_Trsf();transform.SetRotation(gp_Ax1(gp_Pnt(0,0,0),gp_Dir(.3,.8,.5)),.873)
        box=BRepBuilderAPI_Transform(box,transform,True).Shape()
        transform=gp_Trsf();transform.SetTranslation(gp_Vec(57,-32,18))
        box=BRepBuilderAPI_Transform(box,transform,True).Shape()
    if not BRepCheck_Analyzer(box).IsValid():raise ValueError('Independent construction invalid')
    return box,expected


def generate(folder):
    from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
    folder.mkdir(parents=True,exist_ok=False)
    records=[]
    for kind in ('through','blind','split','axial_split','stepped','cross','sealed','boss','remote_boss'):
        for rotated in (False,True):
            for count in ((1,3) if kind in ('through','blind','split') else (1,)):
                name=f'{kind}-{count}-{int(rotated)}'
                shape,expected=build(kind,count=count,rotated=rotated,radius=2.7 if rotated else 3.,height=17.3 if rotated else 12.)
                target=folder/(name+'.step')
                writer=STEPControl_Writer();writer.Transfer(shape,STEPControl_AsIs);writer.Write(str(target))
                records.append(dict(file=target.name,sha256=hashlib.sha256(target.read_bytes()).hexdigest(),expected=expected,
                                    scope='simple complete cylinders with circular planar ends',parameters=dict(kind=kind,count=count,rotated=rotated)))
    manifest=dict(generated_before_evaluation=True,generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),records=records)
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    print(json.dumps(dict(cases=len(records),folder=str(folder))),flush=True)


def model_from_native(path, folder):
    """Same native worker conversion, cached NN artifacts, no modified sources."""
    from amdfm.cad_worker import convert
    from amdfm.io import exact_weld
    from amdfm.models import Model
    target=folder/path.stem
    folder.mkdir(parents=True,exist_ok=True)
    convert(path,target,.05)
    info=json.loads(target.with_suffix('.json').read_text(encoding='utf8'))
    arrays=np.load(target.with_suffix('.npz'))
    mesh=exact_weld(arrays['vertices'],arrays['faces'])
    features=info.pop('features')
    info.update(filename=path.name,source_format='step',unit_status='declared_in_step',dimensions_confirmed=True)
    return Model(mesh,info,features,arrays['face_ids'].copy(),arrays['body_ids'].copy())


def evaluate(folder, output):
    from dfm.verified_holes import measure_holes
    from dfm.machining import MachiningProfile, review_machining
    from dfm.tool_recommendation import review_with_tool_recommendation
    from dfm.hole_view import entry_choice
    from dfm.enhanced_planning import recommend_plan
    from threadpoolctl import threadpool_limits
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf8'))
    output.mkdir(parents=True,exist_ok=False)
    results=[]
    with threadpool_limits(limits=1):
        for record in manifest['records']:
            path=folder/record['file']
            if hashlib.sha256(path.read_bytes()).hexdigest()!=record['sha256']:raise ValueError('Frozen input drift')
            model=model_from_native(path,output/'native')
            inventory=measure_holes(model)
            expected=sorted(record['expected'],key=lambda r:(r['hole_kind'],r['diameter_mm'],r['depth_mm']))
            holes=sorted(inventory['holes'],key=lambda r:(r['hole_kind'],r['diameter_mm'],r['depth_mm']))
            good=len(expected)==len(holes) and all(e['hole_kind']==h['hole_kind'] and
                np.allclose([e['diameter_mm'],e['depth_mm']],[h['diameter_mm'],h['depth_mm']],rtol=1e-8,atol=1e-7) for e,h in zip(expected,holes))
            raw=review_machining(model,MachiningProfile())
            raw_holes=next(f for f in raw['findings'] if f['id']=='cnc_holes')['measurements']['cylindrical_faces']
            nn=[c for r in model.metadata.get('external_feature_recognition',[]) for c in r.get('candidates',[]) if c['feature'] in ('through_hole','blind_hole')]
            checks={}
            if holes:
                direction=entry_choice(holes,(0,0,1))['direction']
                report=review_with_tool_recommendation(model,MachiningProfile(),direction)
                good_direction=all(h['entry_matches_direction'] for h in report['verified_hole_inventory']['holes'])
                tool=report['tool_recommendation']
                checks.update(entry_direction_works=good_direction,values=tool['values'],
                              depth_proposals_correct=all(np.isclose(c['reach_min_mm'],holes[0]['depth_mm']) and c['length_basis']=='verified_hole_depth' for c in tool['constraints']),
                              drill_requirements=tool['drill_requirements'])
                if any(h['hole_kind']=='blind' for h in holes):
                    wrong=review_with_tool_recommendation(model,MachiningProfile(),(-np.asarray(direction)).tolist())
                    checks['wrong_side_no_tool_dimensions']=not wrong['tool_recommendation']['automatic_fields']
                    plan=recommend_plan(wrong,feedback_path=output/'nonexistent-feedback.json')
                    checks['wrong_side_no_numeric_plan']=plan['selected'] is None and plan.get('entry_direction_required')
                checks['bounded_count']=len({i for h in holes for i in h['face_ids']})>=len(holes)
                good=good and checks['entry_direction_works'] and checks['depth_proposals_correct'] and checks.get('wrong_side_no_tool_dimensions',True) and checks.get('wrong_side_no_numeric_plan',True)
            result=dict(file=record['file'],passed=bool(good),expected=expected,inventory=inventory,
                        raw_full_cylinder_count=len(raw_holes),raw_neural_hole_candidate_count=len(nn),checks=checks)
            results.append(result)
            (output/'progress.json').write_text(json.dumps(results,indent=2),encoding='utf8')
            print(json.dumps(dict(file=path.name,passed=bool(good),expected=len(expected),confirmed=len(holes),nn=len(nn))),flush=True)
    summary=dict(cases=len(results),passed=sum(r['passed'] for r in results),results=results,
                 source_manifest_sha256=hashlib.sha256((folder/'manifest.json').read_bytes()).hexdigest(),
                 geometry_complement_not_retraining=True)
    (output/'result.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
    if summary['passed']!=summary['cases']:raise SystemExit(1)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['generate','evaluate']);parser.add_argument('folder',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.action=='generate':generate(args.folder)
    else:evaluate(args.folder,args.output)
