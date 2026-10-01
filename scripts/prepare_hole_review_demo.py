"""Package three frozen CAD references for the ordinary review picker."""
from pathlib import Path
import hashlib,json,shutil
ROOT=Path(__file__).resolve().parents[1]

def main():
    source=ROOT.parent/'study/practical-holes-2026-09-30/independent-cad'
    target=ROOT/'examples/learning_validation/hole_review'
    target.mkdir(parents=True,exist_ok=True)
    original={r['file']:r for r in json.loads((source/'manifest.json').read_text())['records']}
    rows=[]
    for filename,title in [('through-3-0.step','관통 구멍 3개 · 지름 6 mm'),
                           ('blind-3-0.step','막힌 구멍 3개 · 깊이 7.2 mm'),
                           ('split-3-1.step','분할된 구멍 3개 · 기울어진 형상')]:
        src=source/filename;record=original[filename]
        if hashlib.sha256(src.read_bytes()).hexdigest()!=record['sha256']:raise ValueError('Frozen reference drift')
        dest=target/filename
        if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest()!=record['sha256']:raise ValueError('Separate demo must be preserved')
        shutil.copy2(src,dest)
        rows.append(dict(file=filename,title=title,sha256=record['sha256'],expected=record['expected'],
                         source='Independent OCCT Boolean cutters; no external/private model',usage='구멍 위치와 입구 방향 재검토 시연'))
    manifest=target/'manifest.json'
    text=json.dumps(rows,ensure_ascii=False,indent=2)
    if manifest.exists() and manifest.read_text(encoding='utf8')!=text:raise ValueError('Separate manifest must be preserved')
    manifest.write_text(text,encoding='utf8')
    inventory_path=ROOT/'examples/geometry_manifest.json'
    inventory=json.loads(inventory_path.read_text(encoding='utf8'))
    indexed={r['path'] for r in inventory['files']}
    for row in rows:
        p=target/row['file'];name=p.relative_to(ROOT).as_posix()
        if name not in indexed:
            inventory['files'].append(dict(path=name,group='examples/learning_validation',format='step',
                bytes=p.stat().st_size,sha256=row['sha256']))
    inventory.update(geometry_file_count=len(inventory['files']),unique_sha256_count=len({r['sha256'] for r in inventory['files']}),
        total_bytes=sum(r['bytes'] for r in inventory['files']))
    inventory['groups']={g:sum(r['group']==g for r in inventory['files']) for g in sorted({r['group'] for r in inventory['files']})}
    inventory_path.write_text(json.dumps(inventory,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(files=len(rows),folder=str(target)),ensure_ascii=False))

if __name__=='__main__':main()
