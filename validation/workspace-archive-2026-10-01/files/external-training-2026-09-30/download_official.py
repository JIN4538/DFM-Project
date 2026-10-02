"""Fetch exactly the public archive linked by the official QUB dataset page."""
from pathlib import Path
import hashlib
import json
import time
import requests

root = Path(__file__).resolve().parent
url = 'https://pure.qub.ac.uk/files/278385243/MFCAD_dataset.zip'
final = root / 'MFCAD_dataset.zip'
partial = root / 'MFCAD_dataset.zip.partial'
if final.exists():
    raise SystemExit('Archive already present; no overwrite')
start = time.monotonic()
with requests.get(url, stream=True, timeout=(30, 60)) as response:
    record = dict(url=url, response_url=response.url, status=response.status_code,
                  headers={k: v for k, v in response.headers.items() if k.lower() in ('content-length', 'content-type', 'etag', 'last-modified')})
    (root / 'archive-response.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    print(json.dumps(record), flush=True)
    response.raise_for_status()
    digest = hashlib.sha256()
    last = 0
    total = 0
    with partial.open('xb') as handle:
        for chunk in response.iter_content(2 ** 20):
            if not chunk:
                continue
            handle.write(chunk)
            digest.update(chunk)
            total += len(chunk)
            if time.monotonic() - last >= 30:
                print(f'Downloaded {total / 2**20:.1f} MiB in {time.monotonic()-start:.1f}s', flush=True)
                last = time.monotonic()
    if 'Content-Length' in response.headers:
        assert total == int(response.headers['Content-Length'])
    record.update(bytes=total, sha256=digest.hexdigest(), seconds=time.monotonic()-start)
    partial.rename(final)
    (root / 'archive-manifest.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    print('Complete', json.dumps(record), flush=True)
