"""New CAD families; count descriptor measurements; frozen equal-budget AM controls."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import numpy as np
import trimesh

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from amdfm.orientation import candidates,measure_orientation
from amdfm.profiles import Profile
from amdfm.neural_orientation import load_model,baseline_descriptor,predict_surrogates
from amdfm.full_search import MODEL_PATH
from amdfm.proposal_selector import cheap_geometry


def score(h,o,c,scales):
    values=np.column_stack(((np.asarray(h)-scales['h0'])/scales['hs'],
        (np.asarray(o)-scales['o0'])/scales['os'],(scales['c0']-np.asarray(c))/scales['cs']))
    return .7*values.max(axis=1)+.3*values.mean(axis=1)


def scalars(rows):
    return ([r['height_mm'] for r in rows],[r['overhang_projected_area_sum_mm2'] for r in rows],
            [r['contact_triangle_area_mm2'] for r in rows])


def mesh_from_step(path, record):
    from dfm.cad_edit_pairs import read_shape
    from amdfm.cad_worker import prepare_tessellation, items
    from amdfm.io import exact_weld
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopoDS import TopoDS
    from OCP.TopLoc import TopLoc_Location
    from OCP.BRep import BRep_Tool
    # No feature recognizer/model used to produce AM truth meshes.
    shape, audit = prepare_tessellation(read_shape(path), .05, 250000)
    if not (audit.get('retry',{}).get('topology',{}).get('ready') if audit.get('adopted_refinement') else audit['original_topology']['ready']):
        raise ValueError('Independent CAD tessellation topology incomplete')
    xyz, cells, offset=[],[],0
    for raw in items(shape,TopAbs_FACE):
        face,location=TopoDS.Face_s(raw),TopLoc_Location();tri=BRep_Tool.Triangulation_s(face,location)
        vertices=np.asarray([tri.Node(i).Transformed(location.Transformation()).Coord() for i in range(1,tri.NbNodes()+1)])
        faces=np.asarray([tri.Triangle(i).Get() for i in range(1,tri.NbTriangles()+1)],dtype=np.int64)-1
        if face.Orientation()==TopAbs_REVERSED:faces=faces[:,[0,2,1]]
        xyz.append(vertices);cells.append(faces+offset);offset+=len(vertices)
    mesh=exact_weld(np.vstack(xyz),np.vstack(cells))
    if not mesh.is_watertight or not mesh.is_winding_consistent or abs(mesh.volume-record['expected_volume_mm3'])/record['expected_volume_mm3']>.005:
        raise ValueError('Independent CAD-to-mesh check failed')
    return mesh


def run(folder,output,limit):
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import Matern,WhiteKernel
    from scipy.stats import norm
    from threadpoolctl import threadpool_limits
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf8'))
    records=[r for r in manifest['records'] if r['split']!='train'][:limit]
    output.mkdir(parents=True,exist_ok=False)
    protocol=dict(cad_manifest_sha256=hashlib.sha256((folder/'manifest.json').read_bytes()).hexdigest(),
        record_ids=[r['id'] for r in records],model_sha256=hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest(),
        process='MEX',angle_deg=45.,baseline_queries=26,extra_budgets=[6,12,24],total_budgets=[32,38,50],
        initial_query_cost_charged=True,scope='balanced height/downward projection/contact geometry; no manufacturing-success labels',
        reference='26 initial directions plus fixed 256 Fibonacci directions and up to 36 oriented facet normals; discrete reference only',
        methods=['uniform','random','geometry','neural_verified','hybrid_verified','bayesian'],
        frozen_before_results=True,source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (output/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf8')
    started=time.perf_counter();cold=time.perf_counter();model=load_model(MODEL_PATH);cold_load=time.perf_counter()-cold;results=[]
    with threadpool_limits(limits=1):
        for record in records:
            path=folder/record['file']
            if hashlib.sha256(path.read_bytes()).hexdigest()!=record['sha256']:raise ValueError('Independent CAD drift')
            t=time.perf_counter();mesh=mesh_from_step(path,record)
            load_seconds=time.perf_counter()-t
            profile=Profile(process='MEX',build_volume_mm=None)
            initial=list(candidates(None,dense=True).values());t=time.perf_counter()
            base=[measure_orientation(mesh,d,profile) for d in initial];base_seconds=time.perf_counter()-t
            if len(base)!=26:raise ValueError('Descriptor budget contract changed')
            for name,row in zip(candidates(None,dense=True),base):row['name']=name
            h,o,c=map(np.asarray,scalars(base));diag=float(np.linalg.norm(mesh.extents));area=float(mesh.area)
            scales=dict(h0=float(h.min()),hs=max(float(np.ptp(h)),.05*diag),o0=float(o.min()),os=max(float(np.ptp(o)),.05*area),
                c0=float(c.max()),cs=max(float(np.ptp(c)),.05*area))
            base_scores=score(h,o,c,scales);baseline=float(base_scores.min())
            t=time.perf_counter();n=256;z=1-2*(np.arange(n)+.5)/n;phi=np.arange(n)*np.pi*(3-np.sqrt(5))
            sphere=np.column_stack((np.sqrt(1-z*z)*np.cos(phi),np.sqrt(1-z*z)*np.sin(phi),z))
            pool=list(sphere);normals=mesh.face_normals[np.argsort(-mesh.area_faces,kind='stable')]
            for d in normals:
                for direction in (d,-d):
                    if max(np.asarray(initial+pool)@direction)<1-1e-8:pool.append(direction)
                if len(pool)>=292:break
            pool=np.asarray([d for d in pool if max(np.asarray(initial)@d)<1-1e-8]);pool_seconds=time.perf_counter()-t
            t=time.perf_counter();geometry=cheap_geometry(mesh,pool);geometry_seconds=time.perf_counter()-t
            t=time.perf_counter();descriptor=baseline_descriptor(mesh,base);pred=predict_surrogates(model,descriptor,pool)
            neural_seconds=time.perf_counter()-t
            neural_scores=score(pred['height']*diag,pred['overhang']*area,geometry['contact']*area,scales)
            geometry_scores=score(geometry['height']*diag,np.zeros(len(pool)),geometry['contact']*area,scales)
            orders={};orders['uniform']=list(range(len(pool)));rng=np.random.default_rng(int(record['sha256'][:8],16))
            orders['random']=rng.permutation(len(pool)).tolist();orders['geometry']=np.argsort(geometry_scores,kind='stable').tolist()
            orders['neural_verified']=np.argsort(neural_scores,kind='stable').tolist()
            mixed=[]
            for pair in zip(orders['geometry'],orders['neural_verified']):
                for i in pair:
                    if i not in mixed:mixed.append(i)
            orders['hybrid_verified']=mixed
            methods={};query_indices={};raw_pred_best=int(np.argmin(neural_scores))
            # True dense-pool evaluations are diagnostic oracle work, outside
            # each method's access. Selection sees only its own queried rows.
            t=time.perf_counter();reference=[measure_orientation(mesh,d,profile) for d in pool];reference_seconds=time.perf_counter()-t
            reference_scores=score(*scalars(reference),scales);oracle=float(min(baseline,reference_scores.min()))
            for method in protocol['methods']:
                acquired=[];selected=[];optimization=0.;query_seconds=0.
                for step in range(24):
                    if method=='bayesian':
                        t=time.perf_counter();x=np.asarray(initial+[pool[i] for i in selected]);y=np.r_[base_scores,score(*scalars(acquired),scales)] if acquired else base_scores
                        gp=GaussianProcessRegressor(kernel=Matern(length_scale=.55,nu=2.5)+WhiteKernel(1e-5),optimizer=None,normalize_y=True,random_state=1002)
                        gp.fit(x,y);mu,sd=gp.predict(pool,return_std=True);gain=y.min()-mu-.005
                        ei=gain*norm.cdf(gain/np.maximum(sd,1e-10))+sd*norm.pdf(gain/np.maximum(sd,1e-10));ei[selected]=-np.inf
                        index=int(np.argmax(ei));optimization+=time.perf_counter()-t
                    else:index=orders[method][step]
                    selected.append(index);t=time.perf_counter();acquired.append(measure_orientation(mesh,pool[index],profile));query_seconds+=time.perf_counter()-t
                    if step+1 in protocol['extra_budgets']:
                        measured=score(*scalars(acquired),scales);best=min(baseline,float(measured.min()))
                        acquisition=geometry_seconds if method in ('geometry','neural_verified','hybrid_verified') else 0.
                        acquisition+=neural_seconds if method in ('neural_verified','hybrid_verified') else 0.
                        methods[f'{method}_{26+step+1}']=dict(score=best,regret=max(0.,best-oracle),queries=26+step+1,
                            improvement=baseline-best,seconds=base_seconds+pool_seconds+query_seconds+optimization+acquisition,
                            extra_direction_indices=selected.copy(),cheap_geometry_directions=len(pool) if acquisition else 0)
                query_indices[method]=selected
            results.append(dict(id=record['id'],family=record['family'],baseline_score=baseline,reference_best=oracle,reference_queries=26+len(pool),
                methods=methods,raw_neural_predicted_direction_score=float(reference_scores[raw_pred_best]),raw_neural_predicted_score=float(neural_scores[raw_pred_best]),
                load_seconds=load_seconds,reference_seconds=reference_seconds))
            if len(results)%10==0:
                (output/'progress.json').write_text(json.dumps(results,indent=2),encoding='utf8')
                print(json.dumps(dict(processed=len(results),total=len(records),seconds=time.perf_counter()-started)),flush=True)
    summary={}
    for method in results[0]['methods']:
        extra=int(method.rsplit('_',1)[1]);values=[r['methods'][method] for r in results];baseline=[r['methods'][f'geometry_{extra}'] for r in results]
        delta=np.array([a['score']-b['score'] for a,b in zip(values,baseline)])
        groups={}
        for r,d in zip(results,delta):groups.setdefault(r['family'],[]).append(float(d))
        group_values=np.asarray([np.mean(v) for v in groups.values()]);rng=np.random.default_rng(100210)
        boot=group_values[rng.integers(0,len(group_values),(2000,len(group_values)))].mean(axis=1)
        summary[method]=dict(cases=len(values),queries_per_case=extra,better_than_geometry=int((delta < -1e-8).sum()),worse_than_geometry=int((delta > 1e-8).sum()),
            same_as_geometry=int((np.abs(delta)<=1e-8).sum()),mean_regret=float(np.mean([v['regret'] for v in values])),
            mean_seconds=float(np.mean([v['seconds'] for v in values])),grouped_difference_ci95=np.quantile(boot,[.025,.975]).tolist())
    report=dict(protocol=protocol,case_count=len(results),group_count=len({r['family'] for r in results}),cold_model_load_seconds=cold_load,
        model_loading_charged_separately=True,results=results,summary=summary,seconds=time.perf_counter()-started,
        warning='same discrete-reference geometric objective; benchmark does not establish physical output quality or continuous optimum',
        adoption='research comparison only; no product model replaced using this holdout')
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(dict(cases=len(results),summary=summary)),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder',type=Path);p.add_argument('output',type=Path);p.add_argument('--limit',type=int,default=120)
    a=p.parse_args();run(a.folder,a.output,a.limit)
