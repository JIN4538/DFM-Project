"""Public-domain/CC0 STEP demonstrations; original rights and hashes retained."""
import argparse, hashlib, io, json, sqlite3, zipfile, sys
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from amdfm.io import load_model

TITLES={'bracket':'브래킷','block':'구멍·포켓 블록','plate':'구멍 패턴 판','enclosure':'얇은 벽 케이스',
 'ribbed':'리브 보강 판','flanged':'플랜지','tapped':'나사 체결 형상','threaded':'나사 형상',
 'gear':'기어','revolved':'회전 형상','swept':'곡선 경로 형상','sketched':'스케치 돌출',
 'compound':'복합 형상','profiled':'프로파일','lofted':'로프트 형상'}

def main(root):
    out=ROOT/'examples/public_demo';out.mkdir(exist_ok=False);desktop=Path.home()/'Desktop/DFM_공개_STEP_시연';desktop.mkdir(exist_ok=True)
    db=sqlite3.connect(f'file:{(root/"public-expansion.sqlite").resolve()}?mode=ro',uri=True);manifest=[];rejected=[]
    for family in TITLES:
        rows=list(db.execute("SELECT id,step,metadata,step_sha256 FROM parts WHERE dataset='CadQuarry' AND family=? AND split='test' ORDER BY LENGTH(step)",(family,)))
        for identifier,raw,metadata,sha in rows[:8]:
            meta=json.loads(metadata);signature=json.loads(meta['geometry_signature'])
            if len(raw)>750000:continue
            filename='cadquarry_'+family+'_'+identifier[:12]+'.step'
            try:
                model=load_model(raw,filename,deflection_mm=.1,timeout_s=50)
                if model.metadata.get('solid_count',1)>1:continue
                solid_count=model.metadata.get('solid_count',0)
                title=TITLES[family] if solid_count else '케이스 · 표면 모델'
                record=dict(file=filename,title=title+' · CadQuarry',dataset='CadQuarry',source_id=identifier,
                    source_url='https://huggingface.co/datasets/jacobjennings/cadquarry',license='CC0-1.0',sha256=sha,
                    family=family,dimensions_mm=model.mesh.extents.tolist(),cad_volume_mm3=model.metadata.get('exact_volume_mm3'),
                    solid_count=solid_count,cad_geometry_kind='solid' if solid_count else 'surface',
                    params=meta['params'],source_signature=signature,split='test',purpose='독립 공개 CAD 시연; 학습 제외 형상')
                (out/filename).write_bytes(raw);(desktop/filename).write_bytes(raw);manifest.append(record);break
            except (ValueError,MemoryError,OSError) as e:rejected.append(dict(id=identifier,reason=str(e)))
    db.close()
    url='https://www.nist.gov/system/files/documents/2017/10/19/nist_test_artifact_ver3b.zip'
    r=requests.get(url,timeout=90);r.raise_for_status();(root/'nist_test_artifact_ver3b.zip').write_bytes(r.content)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names=[n for n in z.namelist() if Path(n).suffix.lower() in ('.step','.stp')]
        for index,name in enumerate(names):
            raw=z.read(name);filename=f'nist_am_test_artifact_{index+1}.step'
            model=load_model(raw,filename,deflection_mm=.1,timeout_s=120)
            (out/filename).write_bytes(raw);(desktop/filename).write_bytes(raw)
            manifest.append(dict(file=filename,title='NIST 적층제조 시험 형상',dataset='NIST',source_url=url,
                source_page='https://www.nist.gov/el/intelligent-systems-division-73500/production-systems-group/nist-additive-manufacturing-test',
                original_filename=name,license='U.S. Government public domain; acknowledge NIST',sha256=hashlib.sha256(raw).hexdigest(),
                archive_sha256=hashlib.sha256(r.content).hexdigest(),dimensions_mm=model.mesh.extents.tolist(),purpose='공개 시험 형상 시연'))
    raw=json.dumps(manifest,ensure_ascii=False,indent=2);(out/'manifest.json').write_text(raw,encoding='utf8');(desktop/'manifest.json').write_text(raw,encoding='utf8')
    (root/'demo-audit.json').write_text(json.dumps(dict(accepted=manifest,rejected=rejected),ensure_ascii=False,indent=2),encoding='utf8')
    guide='공개 STEP 시연 파일\n\n앱 왼쪽 입력에서 「공개 STEP 시연」을 선택하세요. 같은 파일은 이 폴더에서 직접 업로드할 수 있습니다.\n\n'
    guide+='\n'.join(f"{x['file']} : {x['title']}\n출처: {x['source_url']}\n이용조건: {x['license']}\n" for x in manifest)
    (desktop/'사용법.txt').write_text(guide,encoding='utf8');(out/'README.md').write_text(guide,encoding='utf8');print(json.dumps(dict(files=len(manifest),folder=str(desktop)),ensure_ascii=False),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);main(p.parse_args().root)
