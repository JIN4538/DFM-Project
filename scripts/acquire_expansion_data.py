"""Immutable author datasets; ordinary HTTPS, bounded downloads, no source execution."""
import argparse, concurrent.futures, hashlib, json, time
from pathlib import Path
import requests

SOURCES = {
    'pbf': ('sebius/pbflbm-part-orientation', '24d4f3f5f05cad5488fcf9a4cbc95e28ff528a8a',
            ['plates_with_bores_10000.zip', 'platonic_solids_with_inscriptions_10000.zip',
             'primitives_with_two_bores_10000.zip', 'pyramids_10000.zip']),
    'cadquarry': ('jacobjennings/cadquarry', 'be52b95de212431d995c3ebd25bdd9d56a5c96bf',
                 ['1k/corpus-step.parquet', '1k/corpus-stl.parquet', '1k/corpus.jsonl']),
}

def download(root, dataset, revision, filename, item):
    target=root/'archives'/filename.replace('/', '_'); target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists(): raise ValueError(f'Preserve existing source: {target}')
    url=f'https://huggingface.co/datasets/{dataset}/resolve/{revision}/{filename}'
    expected=item.get('lfs',{}).get('oid'); started=time.monotonic(); digest=hashlib.sha256(); size=0
    with requests.get(url,stream=True,timeout=(30,120)) as response:
        response.raise_for_status()
        with target.with_suffix(target.suffix+'.partial').open('xb') as stream:
            for chunk in response.iter_content(1024*1024):
                stream.write(chunk);digest.update(chunk);size+=len(chunk)
    if size!=item['size'] or expected and digest.hexdigest()!=expected:
        raise ValueError(f'Author checksum/size mismatch: {filename}')
    target.with_suffix(target.suffix+'.partial').rename(target)
    record=dict(dataset=dataset,revision=revision,file=filename,url=url,bytes=size,
                sha256=digest.hexdigest(),author_lfs_sha256=expected,seconds=time.monotonic()-started)
    print(json.dumps(record),flush=True);return record

def main(root):
    root.mkdir(parents=True,exist_ok=True); jobs=[]
    for key,(dataset,revision,files) in SOURCES.items():
        tree=[]
        for directory in sorted({str(Path(name).parent).replace('\\','/') for name in files}):
            suffix='' if directory=='.' else '/'+directory
            response=requests.get(f'https://huggingface.co/api/datasets/{dataset}/tree/{revision}{suffix}',timeout=40)
            response.raise_for_status();tree.extend(response.json())
        byname={item['path']:item for item in tree}
        (root/f'{key}-source-tree.json').write_text(json.dumps(tree,indent=2),encoding='utf8')
        for name in files:jobs.append((root,dataset,revision,name,byname[name]))
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for record in pool.map(lambda args:download(*args),jobs):results.append(record)
    (root/'acquisition.json').write_text(json.dumps(results,indent=2),encoding='utf8')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);main(p.parse_args().root)
