from pathlib import Path
import sys, math, json
import numpy as np
import trimesh

OUT=Path(__file__).resolve().parent
if (OUT/'summary.json').exists():
    raise SystemExit('Existing output set: preserve it and run a copy in a new output folder under deliverables.')
ROOT=OUT.parents[1]
sys.path.insert(0,str(ROOT/'study/versions/AM-DFM_v2_6/dfm2'))
from src.core.model_loader import load_model
from src.core.mesh_diagnostics import inspect_mesh
from src.core.reproducibility import runtime_record, file_sha256, save_new_json, json_ready
from src.processes.additive import AMRuleEngine

def box(x,y,z,at=(0,0,0)):
    m=trimesh.creation.box([x,y,z]); m.apply_translation(np.array(at)+np.array([x,y,z])/2); return m
def union(*ms): return trimesh.boolean.union(list(ms),engine='manifold')
def diff(a,b): return trimesh.boolean.difference([a,b],engine='manifold')
def roof(w,h,t): return union(box(3,3,h+0.5,((w-3)/2,(w-3)/2,0)),box(w,w,t,(0,0,h)))

models=[]
def add(stem,title,mesh,target,design,**options):
    models.append(dict(stem=stem,title=title,mesh=mesh,target=target,design=design,options=options))
add('00_control','정상 대조 큐브',box(10,10,10),'control','10×10×10mm 정육면체')
add('01_wall_recommended','권장 벽두께 미달',box(20,.6,12),'wall_thickness','두께 0.6mm, 폭 20mm, 높이 12mm')
add('02_overhang','오버행 면적 비율',roof(40,8,1),'overhang_area','40×40×1mm 지붕 아래 중앙 3×3mm 기둥; 지붕 아래 높이 8mm')
add('03_support_volume','지지구조 추정 부피 비율',roof(20,40,2),'support_volume','20×20×2mm 지붕 아래 3×3×40mm 기둥')
add('04_aspect_ratio','높은 종횡비',box(2,2,30),'aspect_ratio','2×2×30mm 기둥; 높이/폭=15')
add('05_build_margin','장비 여유 부족',box(220,10,3),'build_margin','220×10×3mm; 250mm 장비 축 점유율 88%')
comb=union(box(10,8,1),*[box(.5,6,5,(.5+i*1.5,1,.8)) for i in range(6)])
add('06_min_feature','작은 특징',comb,'min_feature_size','10×8×1mm 베이스 위 두께 0.5mm의 빗살 6개',min_feature_enabled=True)
m=box(30,20,2); m.apply_transform(trimesh.transformations.rotation_matrix(math.radians(15),[0,1,0])); m.apply_translation(-m.bounds[0])
add('07_staircase','계단 효과',m,'staircase','30×20×2mm 판을 Y축 기준 15° 기울인 형상; 최저점 Z=0')
add('08_thickness_gradient','급격한 두께 변화',union(box(20,12,1),box(10,12,10,(10,0,0))),'thickness_gradient','판 두께가 X=10mm에서 1mm→10mm로 변화',thickness_gradient_enabled=True)
add('09_feature_gap','좁은 형상 간격',union(box(12,8,2),box(4,8,12,(0,0,1)),box(4,8,12,(4.25,0,1))),'feature_gap','높이 13mm의 두 벽 사이 간격 0.25mm; 베이스 연결')
h=trimesh.creation.cylinder(radius=2,height=14,sections=64); h.apply_transform(trimesh.transformations.rotation_matrix(math.pi/2,[1,0,0])); h.apply_translation([6,5,7])
add('10_horizontal_hole_NA','수평 구멍—미구현 설명용',diff(box(12,10,14),h),'horizontal_hole','Y축 방향 지름 4mm 관통 구멍. 현재 규칙은 N/A이며 위반 판정 불가')
add('11_wall_hard_gate','최소 벽두께 게이트',box(20,.3,12),'gate_wall','두께 0.3mm, 폭 20mm, 높이 12mm')
add('12_build_size_gate','장비 크기 초과',box(260,10,3),'gate_build','260×10×3mm; 250×250×250mm 장비 초과')
add('13_trapped_cavity','밀폐 내부 공동',diff(box(20,20,20),box(10,10,10,(5,5,5))),'gate_cavity','20mm 정육면체 내부의 밀폐된 10mm 정육면체 공동. FDM 경고 정책')
m=box(10,10,10); m.update_faces(np.arange(len(m.faces))!=0); m.remove_unreferenced_vertices()
add('14_mesh_integrity_FAIL','메시 무결성 실패',m,'gate_mesh','10mm 큐브의 삼각형 하나를 삭제한 의도적 손상 파일')
add('15_layer_thin','단면 얇은 특징',union(box(12,8,2),box(.3,6,10,(5,1,1))),'layer_thin','베이스 위 0.3mm 벽; 선폭 0.4mm에서 검토')
add('16_layer_bridge','단면 지지·브리지',union(box(3,8,10),box(3,8,10,(18,0,0)),box(21,8,2,(0,0,10))),'layer_unsupported','15mm의 열린 간격을 건너는 두께 2mm 브리지; 아래 면 Z=10mm')
add('17_single_layer','한 층에만 나타나는 영역',union(box(3,6,10),box(10,6,.16,(2,0,5))),'layer_single_layer','기둥 측면에 Z=5.00~5.16mm 두께 0.16mm 돌출판; 0.2mm 중간 평면 중 Z=5.1만 통과')

if not (OUT/'runtime.json').exists(): save_new_json(OUT/'runtime.json',runtime_record())
summary=[]
for item in models:
    stem=item['stem']; mesh=item.pop('mesh'); path=OUT/(stem+'.stl')
    mesh.export(path)
    raw=trimesh.load_mesh(path,process=True)
    diag=inspect_mesh(raw)
    if stem!='14_mesh_integrity_FAIL': assert diag['topology_ready'],(stem,diag)
    loaded=load_model(str(path),unit='mm')['mesh']
    result=AMRuleEngine().evaluate(loaded,printer_dims=(250,250,250),**item['options'])
    row=dict(**item,file=path.name,sha256=file_sha256(path),diagnostics=diag,evaluation=result)
    if not (OUT/(stem+'.json')).exists(): save_new_json(OUT/(stem+'.json'),row)
    compact=json_ready(row); compact['evaluation'].pop('analysis',None)
    summary.append(dict(stem=stem,title=item['title'],target=item['target'],design=item['design'],options=item['options'],
       mesh_ok=diag['topology_ready'],status=result.evaluation_status,score=result.total_score,
       gates=json_ready(result.gates),rules=json_ready(result.rule_results),
       layers={k:v for k,v in result.layer_review.items() if k in ['status','checks','expected_layers','complete_layers']}))
    print(stem,result.evaluation_status,[(r.rule_name,r.status,r.value) for r in result.rule_results],flush=True)
save_new_json(OUT/'summary.json',summary)
