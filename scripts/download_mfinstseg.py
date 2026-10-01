import requests, re, html, hashlib, time,json
from pathlib import Path
import argparse
from urllib.parse import urlparse
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);args=p.parse_args();root=args.root;root.mkdir(parents=True,exist_ok=True);(root/'archives').mkdir(exist_ok=True)
out=root/'archives/MFInstSeg-data2.zip'
if out.exists():raise FileExistsError(out)
page=requests.get('https://drive.google.com/uc?export=download&id=1T2sHlL-4qlsXTxu3AMBB4h-N1I5VqNky',timeout=40);page.raise_for_status();s=page.text
(root/'mfinstseg_download_page.txt').write_text(s,encoding='utf8')
action=html.unescape(re.search(r'<form[^>]+action="([^"]+)"',s).group(1))
if urlparse(action).scheme!='https' or urlparse(action).hostname!='drive.usercontent.google.com':raise ValueError('Unexpected public download form destination')
params={k:html.unescape(v) for k,v in re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]+)"',s)}
h=hashlib.sha256();total=0;t=time.monotonic();last=t
with requests.get(action,params=params,stream=True,timeout=(30,90)) as r:
 print('status',r.status_code,r.headers.get('Content-Type'),flush=True);r.raise_for_status()
 with out.with_suffix('.zip.partial').open('xb') as f:
  for b in r.iter_content(2**20):
   if not b:continue
   f.write(b);h.update(b);total+=len(b)
   if time.monotonic()-last>20:print(round(total/2**20),'MiB',flush=True);last=time.monotonic()
 with out.with_suffix('.zip.partial').open('rb') as f:
  if f.read(4)!=b'PK\x03\x04':raise ValueError('Not a zip')
 if r.headers.get('Content-Length') and total!=int(r.headers['Content-Length']):raise ValueError('Size mismatch')
out.with_suffix('.zip.partial').rename(out);record=dict(source='MFInstSeg author AAGNet Google Drive',public_page='https://github.com/whjdark/AAGNet',bytes=total,sha256=h.hexdigest(),license='to audit archive and author dataset record before training',seconds=time.monotonic()-t);(root/'mfinstseg-acquisition.json').write_text(json.dumps(record,indent=2),encoding='utf8');print(json.dumps(record),flush=True)
