"""External learned locations with independent planar pocket CAD verification."""
from __future__ import annotations
import numpy as np

def pocket_dimensions(candidate,direction):
    """Accept a single straight-sided prismatic recess with a complete floor.

    NN labels select a face group; exact vertices/planes establish dimensions.
    Intersections, mixed heights, split walls and partial groups are rejected.
    """
    if candidate['feature'] not in ('triangular_pocket','rectangular_pocket','6sides_pocket'): return None
    m=candidate['measured_faces'];axis=np.asarray(direction,float);axis/=np.linalg.norm(axis)
    floors=[f for f in m if np.dot(f['normal'],axis)>1-1e-7]
    if len(floors)!=1:return None
    floor=floors[0];walls=[f for f in m if f is not floor]
    pts=np.asarray(floor['vertex_points_mm'],float)
    sides={'triangular_pocket':3,'rectangular_pocket':4,'6sides_pocket':6}[candidate['feature']]
    if len(pts)!=sides or len(walls)!=sides:return None
    scale=max(np.linalg.norm(np.ptp(pts,axis=0)),1);tol=scale*1e-7
    floor_height=float(np.mean(pts@axis))
    if np.ptp(pts@axis)>tol:return None
    heights=[]; normals=[]; planes=[]; covered=set()
    for wall in walls:
        n=np.array(wall['normal']);v=np.asarray(wall['vertex_points_mm'])
        if abs(n@axis)>1e-7 or len(v)!=4:return None
        z=v@axis;bottom=v[np.abs(z-floor_height)<=tol];top=v[np.abs(z-floor_height)>tol]
        if len(bottom)!=2 or len(top)!=2 or np.ptp(top@axis)>tol:return None
        found=[int(np.argmin(np.linalg.norm(pts-b,axis=1))) for b in bottom]
        if any(np.linalg.norm(pts[j]-b)>tol for j,b in zip(found,bottom)) or found[0]==found[1]:return None
        covered.add(tuple(sorted(found)));heights.append(float(np.mean(top@axis)-floor_height));normals.append(n)
        inward=n if n@(pts.mean(0)-bottom[0])>0 else -n
        if np.min((pts-bottom[0])@inward)<-tol:return None  # convex floor only
        planes.append((inward,bottom[0]))
    if len(covered)!=sides or min(heights)<=tol or np.ptp(heights)>tol:return None
    # Width is explicitly the minimum polygon caliper, not an inscribed tool
    # diameter. Corner/tool-entry checks remain separate.
    widths=[float(np.ptp(pts@n)) for n in normals]
    if min(widths)<=tol:return None
    # Largest disk contained in a convex floor: maximize r subject to signed
    # distances from every wall >= r. This establishes entry clearance only;
    # sharp inside corners still need a geometry change.
    from scipy.optimize import linprog
    center=pts.mean(0);u=pts[1]-pts[0];u/=np.linalg.norm(u);v=np.cross(axis,u)
    matrix=np.array([[-n@u,-n@v,1.] for n,_ in planes]);bound=np.array([n@(center-point) for n,point in planes])
    disk=linprog([0.,0.,-1.],A_ub=matrix,b_ub=bound,bounds=[(None,None),(None,None),(0,None)],method='highs')
    if not disk.success or disk.x[2]<=tol:return None
    entry_center=center+u*disk.x[0]+v*disk.x[1]
    return dict(floor_face_id=floor['face_id'],face_ids=candidate['face_ids'],
        feature=candidate['feature'],width_mm=min(widths),wall_height_mm=float(np.mean(heights)),
        entry_circle_diameter_mm=float(2*disk.x[2]),entry_center_mm=entry_center.tolist(),
        area_mm2=floor['area_mm2'],measurement_method='Exact CAD face planes/vertices; closed prism boundary verified',
        width_definition='minimum floor polygon caliper; not tool-fit diameter')

def attach_external_features(report,model):
    selected=model.metadata.get('selected_body')
    records=[r for r in model.metadata.get('external_feature_recognition',[]) if selected is None or r['body_id']==selected]
    candidates=[dict(c,body_id=r['body_id'],recognition_model_id=r.get('model_id')) for r in records for c in r.get('candidates',[])]
    report['external_feature_recognition']=dict(records=records,candidates=candidates)
    if report.get('input',{}).get('solid_count')!=1 or not candidates:return report
    verified=[]
    for c in candidates:
        d=pocket_dimensions(c,report['direction'])
        if d:verified.append(d)
    p=report['profile'];bad=[]
    for d in verified:
        problems=[]
        d['width_too_small']=None if p.get('tool_diameter_mm') is None else p['tool_diameter_mm']>d['entry_circle_diameter_mm']+1e-7
        d['exceeds_flute_length']=None if p.get('flute_length_mm') is None else p['flute_length_mm']<d['wall_height_mm']-1e-7
        d['exceeds_reach']=None if p.get('reach_mm') is None else p['reach_mm']<d['wall_height_mm']-1e-7
        if d['width_too_small']:problems.append(f"공구 지름 {p['tool_diameter_mm']:g} mm > 바닥 진입원 지름 {d['entry_circle_diameter_mm']:g} mm")
        if d['exceeds_flute_length']:problems.append(f"날 길이 {p['flute_length_mm']:g} mm < 벽 높이 {d['wall_height_mm']:g} mm")
        if d['exceeds_reach']:problems.append(f"돌출 길이 {p['reach_mm']:g} mm < 벽 높이 {d['wall_height_mm']:g} mm")
        d['problems']=problems
        if problems:bad.append(d)
    # Rectangular floors already reviewed by the analytic engine are not
    # duplicated. Triangular/hexagonal pockets add previously unhandled sites.
    new=[d for d in verified if d['feature']!='rectangular_pocket']
    if new:
        bad=[d for d in bad if d in new];ids=sorted({i for d in (bad or new) for i in d['face_ids']})
        # Verified planar polygon recesses have sharp inside corners. A round
        # end mill cannot reproduce them exactly even when its diameter fits.
        for d in new:
            d['internal_corner_radius_mm']=0.
            d['problems'].append('내부 코너 반경 0 mm · 원형 엔드밀 반경 여유 필요')
        status='attention'
        radius=p.get('tool_diameter_mm')
        action=f'내부 코너를 R {radius/2:g} mm 이상으로 바꾸세요.' if radius else '내부 코너에 엔드밀 반경 이상의 여유를 추가하세요.'
        if any(d['width_too_small'] for d in new):
            entry=min(d['entry_circle_diameter_mm'] for d in new)
            action=f'먼저 지름 {entry:g} mm보다 작은 공구를 선택하고, 그 공구 반경 이상의 내부 코너 여유를 추가하세요.'
        short_flute=[d['wall_height_mm'] for d in new if d['exceeds_flute_length']]
        short_reach=[d['wall_height_mm'] for d in new if d['exceeds_reach']]
        if short_flute:action+=f' 날 길이는 {max(short_flute):g} mm 이상으로 검토하세요.'
        if short_reach:action+=f' 돌출 길이는 {max(short_reach):g} mm 이상으로 검토하세요.'
        report['findings'].append(dict(id='cnc_learned_pockets',title='추가 인식한 포켓',status=status,
            reason=f"추가 포켓 {len(new)}곳 · 진입원 최소 Ø{min(d['entry_circle_diameter_mm'] for d in new):g} mm · 벽 높이 최대 {max(d['wall_height_mm'] for d in new):g} mm",
            action=action,
            method='External MFCAD/MFInstSeg graph neural segmentation + independent exact CAD prism verification',
            evidence=['MFCAD_EXTERNAL'],
            measurements={'pockets':new},cad_face_ids=ids,
            face_indices=np.flatnonzero(np.isin(model.face_ids,ids)).tolist(),limitations=[],severity='review'))
        report.setdefault('sources',[]).append(dict(id='MFCAD_EXTERNAL',title='MFCAD · planar machining feature dataset',
            url='https://github.com/hducg/MFCAD',scope='외부 면 라벨로 특징 후보를 인식하고 CAD 기하에서 치수를 재측정',
            locator='ef6d58a40164d5192666821ce98d0cc90e379fac; 16-class semantic audit 2026-09-30',
            access='원본 15,488 STEP·라벨 반입 및 전체 기하 감사',
            local_path='data/training/MFCAD-LICENSE.txt'))
    report['external_feature_recognition']['verified_pockets']=verified
    if any('mfinstseg' in (r.get('model_id') or '') or r.get('localization_model_id') for r in records):
        report.setdefault('sources',[]).append(dict(id='MFINSTSEG_EXTERNAL',title='MFInstSeg · 25-class machining feature dataset',
            url='https://github.com/whjdark/AAGNet',scope='외부 면 라벨로 곡면 포함 특징 후보를 인식; 치수는 CAD에서 재측정',
            locator='62,395 per-record face geometry/adjacency certified graphs; disjoint family-group evaluation',
            access='전체 STEP와 저자 AAG의 면 종류·면적·중심·인접 관계 대조; 학습·검증·시험 분리'))
    return report
