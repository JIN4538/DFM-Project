"""Dimensioned original STEP pairs for manual before/after demonstrations."""
import hashlib,json,math,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from OCP.gp import gp_Pnt,gp_Vec
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon,BRepBuilderAPI_MakeFace
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox,BRepPrimAPI_MakePrism
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from dfm.cad_graph import read_step_graph
from dfm.external_features_review import pocket_dimensions
from dfm.cad_edit_pairs import round_corners,read_shape,write_step


def main():
    folder=ROOT/'examples/learning_validation/corner_edits';folder.mkdir(parents=True,exist_ok=True)
    desktop=Path.home()/'Desktop/DFM_개선전후_STEP';desktop.mkdir(exist_ok=True)
    records=[]
    for sides in (3,4,6):
        feature={3:'triangular_pocket',4:'rectangular_pocket',6:'6sides_pocket'}[sides]
        polygon=BRepBuilderAPI_MakePolygon()
        for i in range(sides):
            a=math.pi*2*i/sides;polygon.Add(gp_Pnt(25+10*math.cos(a),30+10*math.sin(a),14))
        polygon.Close()
        tool=BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(polygon.Wire()).Face(),gp_Vec(0,0,10)).Shape()
        shape=BRepAlgoAPI_Cut(BRepPrimAPI_MakeBox(50.,60.,20.).Shape(),tool).Shape()
        before=folder/(feature+'_before.step');write_step(shape,before)
        graph=read_step_graph(before)
        faces=[m for m in graph['measurements'] if abs(m['centroid_mm'][2]-14)<1e-7 or abs(m['centroid_mm'][2]-17)<1e-7]
        candidate=dict(feature=feature,face_ids=[m['face_id'] for m in faces],measured_faces=faces)
        pocket=pocket_dimensions(candidate,[0,0,1]);pocket['direction']=[0,0,1]
        after,audit=round_corners(read_shape(before),pocket,1.)
        destination=folder/(feature+'_after_R1.step');write_step(after,destination)
        (folder/(feature+'_audit.json')).write_text(json.dumps(dict(pocket=pocket,audit=audit),indent=2))
        for path,phase in ((before,'before'),(destination,'after')):
            shutil.copy2(path,desktop/path.name)
            records.append(dict(file=path.name,feature=feature,phase=phase,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                creator='DFM project independently constructed reference CAD',license='Project reference fixture',
                dimensions_mm=[50,60,20],floor_z_mm=14,wall_height_mm=6,corner_radius_mm=0 if phase=='before' else 1))
    raw=json.dumps(records,ensure_ascii=False,indent=2);(folder/'manifest.json').write_text(raw,encoding='utf8');(desktop/'manifest.json').write_text(raw,encoding='utf8')
    guide='개선 전후 STEP 시연\n\n앱에서 절삭가공 → 절삭 검증 형상 → 삼각 포켓 · 수정 전을 선택하고 검토하세요.\n공구 치수를 입력하지 않아도 자동 제안합니다. 종합 결론의 ‘문제 위치 보기’로 위치를 확인하고,\n‘개선 형상 보기 · 코너 수정’을 누르면 추천 반경을 적용한 전후 그림과 수정 STEP을 얻습니다.\n\n제공된 R1 기준쌍은 같은 목록에서 ‘수정 전’과 ‘코너 R 1 mm 수정 후’를 각각 선택해 비교합니다.\n엔드밀 지름 2 mm, 날 길이 8 mm, 돌출 길이 10 mm 조건을 사용하면 코너 수정 차이를 볼 수 있습니다.\n삼각·직사각·육각 포켓: 소재 50×60×20 mm, 포켓 깊이 6 mm, 수정 반경 R1 mm.\n'
    (desktop/'사용법.txt').write_text(guide,encoding='utf8');(folder/'README.md').write_text(guide,encoding='utf8')
    inventory_path=ROOT/'examples/geometry_manifest.json';inventory=json.loads(inventory_path.read_text(encoding='utf8'))
    known={r['path'] for r in inventory['files']}
    for row in records:
        path=folder/row['file'];relative=path.relative_to(ROOT).as_posix()
        if relative in known:continue
        inventory['files'].append(dict(path=relative,group='examples/learning_validation',format='step',bytes=path.stat().st_size,sha256=row['sha256'],purpose='Independent CAD corner-edit pair fixture'))
    inventory['geometry_file_count']=len(inventory['files']);inventory['unique_sha256_count']=len({r['sha256'] for r in inventory['files']})
    inventory['total_bytes']=sum(r['bytes'] for r in inventory['files'])
    inventory['groups']={g:sum(r['group']==g for r in inventory['files']) for g in sorted({r['group'] for r in inventory['files']})}
    inventory_path.write_text(json.dumps(inventory,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(step_pairs=3,files=6,desktop=str(desktop)),ensure_ascii=False))
if __name__=='__main__':main()
