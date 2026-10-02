"""Held-out public CAD before/after fillet reconstruction and analytic checks."""
import concurrent.futures,hashlib,json,sqlite3,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dfm.cad_edit_pairs import read_shape,round_corners,write_step


def worker(job):
    case,pocket,raw,output=job
    name=case['id']+'-'+pocket['feature']
    folder=Path(output)/name;folder.mkdir(exist_ok=True)
    (folder/'before.step').write_bytes(raw)
    try:
        shape=read_shape(folder/'before.step')
        after,audit=round_corners(shape,pocket,pocket['entry_circle_diameter_mm']*.1)
        audit.update(id=case['id'],group_id=case['group_id'],split=case['split'],feature=pocket['feature'],
            source_sha256=hashlib.sha256(raw).hexdigest(),after_sha256=write_step(after,folder/'after.step'),
            source_url='https://github.com/whjdark/AAGNet',license='Author dataset page CC0 declaration; repository code MIT is separate',pocket=pocket)
        (folder/'audit.json').write_text(json.dumps(audit,indent=2))
        return dict(id=case['id'],feature=pocket['feature'],status='verified',folder=str(folder),audit=audit)
    except Exception as error:
        return dict(id=case['id'],feature=pocket['feature'],status='rejected',reason=str(error),folder=str(folder))


def main():
    run=ROOT.parent/'study/ai-full-corpus-2026-09-30';output=run/'paired-cad';output.mkdir(exist_ok=True)
    cases=json.loads((run/'pocket-cases-full.json').read_text())
    source=sqlite3.connect(f'file:{(ROOT.parent/"study/external-training-2026-09-30/mfinstseg-complete.sqlite").as_posix()}?mode=ro',uri=True)
    jobs=[];seen=set();counts={name:0 for name in ('triangular_pocket','rectangular_pocket','6sides_pocket')}
    for c in sorted(cases,key=lambda c:hashlib.sha256(c['id'].encode()).hexdigest()):
        if c['split']!='test' or c['group_id'] in seen:continue
        p=next((p for p in c['pockets'] if counts[p['feature']]<35),None)
        if p is None:continue
        seen.add(c['group_id']);counts[p['feature']]+=1
        raw=source.execute('SELECT step FROM parts WHERE id=?',(c['id'],)).fetchone()[0]
        jobs.append((c,p,raw,str(output)))
        if len(jobs)==105:break
    start=time.monotonic();results=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=2) as pool:
        for r in pool.map(worker,jobs):
            results.append(r)
            print(json.dumps(dict(processed=len(results),verified=sum(r['status']=='verified' for r in results),seconds=time.monotonic()-start)),flush=True)
    summary=dict(attempted=len(results),verified=sum(r['status']=='verified' for r in results),counts=counts,results=results,
        scope='Independent test family public CAD; actual OCCT reconstruction, single-solid validity, unchanged bounds and separate tangent-arc volume formula. No use in weight fitting.',seconds=time.monotonic()-start)
    (run/'cad-pair-benchmark.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps({k:v for k,v in summary.items() if k!='results'}),flush=True)
if __name__=='__main__':main()
