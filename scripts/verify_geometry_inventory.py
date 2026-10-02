"""Verify shipped test geometry without loading CAD or changing any input."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

FORMATS={'.step','.stp','.stl','.3mf','.brep','.iges','.igs','.obj','.ply'}


def verify(root, require_tracked=False):
    root=Path(root).resolve()
    manifest=json.loads((root/'examples/geometry_manifest.json').read_text(encoding='utf-8'))
    records=manifest['files']
    errors=[]
    names=[r['path'] for r in records]
    if len(names)!=len(set(names)):
        errors.append('Duplicate inventory paths')
    if len(records)!=manifest['geometry_file_count']:
        errors.append('Inventory file count mismatch')
    if len({r['sha256'] for r in records})!=manifest['unique_sha256_count']:
        errors.append('Inventory unique SHA count mismatch')
    if sum(r['bytes'] for r in records)!=manifest['total_bytes']:
        errors.append('Inventory total size mismatch')
    for row in records:
        path=(root/row['path']).resolve()
        if root not in path.parents:
            errors.append('Path outside repository: '+row['path'])
            continue
        if not path.is_file():
            errors.append('Missing: '+row['path'])
            continue
        data=path.read_bytes()
        if len(data)!=row['bytes'] or hashlib.sha256(data).hexdigest()!=row['sha256']:
            errors.append('Changed bytes: '+row['path'])
    discovered={p.relative_to(root).as_posix() for folder in ('examples','validation','cura_run','src')
                for p in (root/folder).rglob('*') if p.is_file() and p.suffix.lower() in FORMATS
                and not p.is_relative_to(root/'validation/v3/runs')}
    for name in sorted(discovered-set(names)):
        errors.append('Unlisted geometry: '+name)
    if require_tracked:
        tracked=set(subprocess.check_output(['git','ls-files','-z'],cwd=root).decode('utf-8').split('\0'))
        errors.extend('Not tracked: '+name for name in names if name not in tracked)
    return {'verified':not errors,'geometry_files':len(records),
            'unique_sha256':len({r['sha256'] for r in records}),'errors':errors}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--require-tracked',action='store_true')
    args=parser.parse_args()
    result=verify(args.root,args.require_tracked)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['verified'] else 1)
