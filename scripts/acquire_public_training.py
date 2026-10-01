"""Download allow-listed public training archives without executing contents."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import requests

SOURCES = {
    'mfcad': dict(url='https://codeload.github.com/hducg/MFCAD/zip/ef6d58a40164d5192666821ce98d0cc90e379fac',
                  filename='MFCAD-original.zip', license='MIT', attribution='hducg/MFCAD',
                  page='https://github.com/hducg/MFCAD', commit='ef6d58a40164d5192666821ce98d0cc90e379fac'),
    'uvnet_mfcad': dict(url='https://uv-net-data.s3.us-west-2.amazonaws.com/MFCADDataset.zip',
                        filename='UVNet-MFCADDataset.zip', license='archive license to inspect',
                        attribution='AutodeskAILab/UV-Net; original hducg/MFCAD',
                        page='https://github.com/AutodeskAILab/UV-Net'),
    'mfcadpp': dict(url='https://pure.qub.ac.uk/files/278385243/MFCAD_dataset.zip',
                    filename='MFCAD_dataset.zip', license='CC BY; version unreported on official page',
                    attribution='Colligan, Robinson, Nolan, Hua; QUB, 2022',
                    page='https://doi.org/10.17034/d1fec5a0-8c10-4630-b02e-b92dc81df823'),
}

def acquire(dataset, root):
    spec = SOURCES[dataset]
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    final = root / spec['filename']
    if final.exists():
        raise FileExistsError(final)
    partial = final.with_suffix(final.suffix + '.partial')
    started = time.monotonic()
    record = dict(dataset=dataset, **spec)
    try:
        with requests.get(spec['url'], stream=True, timeout=(30, 90)) as response:
            record.update(status=response.status_code, response_url=response.url)
            response.raise_for_status()
            digest = hashlib.sha256()
            total = 0
            last = started
            with partial.open('xb') as handle:
                for block in response.iter_content(1024 * 1024):
                    if not block:
                        continue
                    handle.write(block)
                    digest.update(block)
                    total += len(block)
                    if time.monotonic() - last > 20:
                        print(f'{dataset}: {total/2**20:.1f} MiB', flush=True)
                        last = time.monotonic()
            if response.headers.get('Content-Length'):
                if total != int(response.headers['Content-Length']):
                    raise ValueError('Content length mismatch')
            with partial.open('rb') as header:
                magic = header.read(4)
            if magic != b'PK\x03\x04':
                raise ValueError('Response is not a ZIP archive')
            partial.rename(final)
            record.update(bytes=total, sha256=digest.hexdigest(), seconds=time.monotonic()-started, state='downloaded')
    except Exception as error:
        record.update(state='failed', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        with (root / (dataset + '-acquisition.json')).open('x', encoding='utf-8') as handle:
            json.dump(record, handle, indent=2)
    print(json.dumps(record), flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', choices=SOURCES)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    acquire(args.dataset, args.root)
