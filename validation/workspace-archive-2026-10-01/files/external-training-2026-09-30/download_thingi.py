import requests,hashlib,time,json
from pathlib import Path
root=Path('../study/external-training-2026-09-30/archives');out=root/'Thingi10K_npz-v1.5.0.tar.gz';url='https://huggingface.co/datasets/Thingi10K/Thingi10K/resolve/v1.5.0/Thingi10K_npz.tar.gz'
t=time.monotonic();h=hashlib.sha256();size=0;last=t
with requests.get(url,stream=True,timeout=(30,90)) as r:
 r.raise_for_status()
 with out.with_suffix(out.suffix+'.partial').open('xb') as f:
  for b in r.iter_content(2**20):
   if not b:continue
   f.write(b);h.update(b);size+=len(b)
   if time.monotonic()-last>20:print(round(size/2**20),'MiB',flush=True);last=time.monotonic()
 if r.headers.get('Content-Length') and size!=int(r.headers['Content-Length']):raise ValueError('Length mismatch')
out.with_suffix(out.suffix+'.partial').rename(out)
record=dict(source='Thingi10K authors Hugging Face mirror',url=url,revision='v1.5.0',bytes=size,sha256=h.hexdigest(),seconds=time.monotonic()-t,license='per-model metadata; no blanket license')
(root/'thingi-acquisition.json').write_text(json.dumps(record,indent=2),encoding='utf8'); print(json.dumps(record),flush=True)
