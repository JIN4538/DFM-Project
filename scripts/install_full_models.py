"""Check new portable artifacts, preserve old ones and install approved roles."""
import hashlib, json, shutil, sys
from pathlib import Path
import numpy as np
import torch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from amdfm.neural_orientation import load_model
from dfm.plan_learning import load_plan_model
from dfm.rl_planner import load_model as load_rl


def main():
    run=ROOT.parent/'study/ai-full-corpus-2026-09-30'
    path=run/'am-full/neural_orientation_external_v4.json'
    model=load_model(path)
    errors={}
    torch.set_num_threads(1)
    for name,net in model['networks'].items():
        x=np.load(run/f'am-full/arrays/test-{name}-x.npy',mmap_mode='r')[:8192]
        h=(x-net['mean'])/net['scale']
        t=torch.from_numpy(h.astype('float32'))
        for i,(w,b) in enumerate(zip(net['weights'],net['biases'])):
            h=h@w+b
            t=t@torch.tensor(w,dtype=torch.float32)+torch.tensor(b,dtype=torch.float32)
            if i<len(net['weights'])-1:
                h=np.maximum(h,0);t=torch.relu(t)
        errors[name]=float(np.max(np.abs(np.clip(h,0,1)-torch.clip(t,0,1).numpy())))
    if max(errors.values())>1e-5:
        raise ValueError('AM portable parity mismatch')
    names=[path,run/'base-plan/plan_ranker_v1.json',run/'plan-full/plan_ranker_external_v3.json',run/'rl-full/rl_planner_v1.json']
    for p in names[1:3]:load_plan_model(p)
    load_rl(names[-1])
    saved=run/'repo-models-before'; saved.mkdir(exist_ok=True)
    records=[]
    for p in names:
        for source in (p,p.with_suffix('.manifest.json')):
            dest=ROOT/'data/models'/source.name
            if dest.exists() and not (saved/dest.name).exists():shutil.copy2(dest,saved/dest.name)
            shutil.copy2(source,dest)
            records.append(dict(file=dest.name,sha256=hashlib.sha256(dest.read_bytes()).hexdigest()))
    (run/'portable-installation.json').write_text(json.dumps(dict(am_portable_error=errors,files=records),indent=2))
    print(json.dumps(dict(am_portable_error=errors,installed=len(records))))


if __name__=='__main__':main()
