import requests,hashlib,time,json
from pathlib import Path
import argparse
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--metadata-only',action='store_true');args=p.parse_args()
root=args.root/'archives';root.mkdir(parents=True,exist_ok=True);out=root/'Thingi10K_npz-v1.5.0.tar.gz';url='https://huggingface.co/datasets/Thingi10K/Thingi10K/resolve/v1.5.0/Thingi10K_npz.tar.gz'
if not args.metadata_only and out.exists():raise FileExistsError(out)
records=[]
for name in ('contextual_data.csv','input_summary.csv','geometry_data.csv'):
 source=f'https://huggingface.co/datasets/Thingi10K/Thingi10K/resolve/v1.5.0/metadata/{name}'
 response=requests.get(source,timeout=40);response.raise_for_status();path=args.root/name
 if path.exists():
  if path.read_bytes()!=response.content:raise ValueError('Preserve conflicting metadata: '+name)
 else:path.write_bytes(response.content)
 records.append(dict(file=name,url=source,bytes=len(response.content),sha256=hashlib.sha256(response.content).hexdigest()))
manifest=args.root/'metadata-acquisition.json'
with manifest.open('x',encoding='utf8') as f:json.dump(records,f,indent=2)
if args.metadata_only:print(json.dumps(records));raise SystemExit(0)
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
