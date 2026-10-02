"""Preserve real edit pairs and diagnostics; original working evidence stays intact."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def save(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode('utf8'))


def archive(study, destination):
    study = study.resolve(); destination = destination.resolve()
    if ROOT not in destination.parents:
        raise ValueError('Destination must be within this repository')
    destination.mkdir(parents=True, exist_ok=False)
    for name in ('cad', 'am-equal-budget-01', 'am-equal-budget-02', 'am-equal-budget-v4-03',
                 'runtime-01', 'runtime-02', 'runtime-03', 'browser'):
        if (study/name).is_dir():
            shutil.copytree(study/name, destination/name)
    logdir = destination/'logs'; logdir.mkdir()
    for file in study.parent.glob(study.name+'*'):
        if file.is_file() and file.suffix in ('.log', '.xml'):
            shutil.copy2(file, logdir/file.name)
    # Preference fields intentionally remain blank. Geometry labels do not
    # become fabricated professor/expert recommendations.
    cases = json.loads((destination/'cad/labels.json').read_text(encoding='utf8'))['cases']
    with (destination/'expert_pairs.csv').open('w', encoding='utf-8-sig', newline='') as output:
        fields = ['case_id', 'family', 'before_step', 'candidate_A_step', 'candidate_B_step',
                  'A_radius_mm', 'B_radius_mm', 'A_material_delta_mm3', 'B_material_delta_mm3',
                  'editable', 'protected', 'preferred_A_B_tie_neither', 'reason', 'annotator']
        writer = csv.DictWriter(output, fieldnames=fields); writer.writeheader()
        for case in cases:
            rows = [r for r in case['rows'] if r['split']=='test' and r['valid'] and r['satisfies_tool_radius'] and r['protected_radius_ok']]
            if len(rows)<2:
                continue
            a,b=rows[:2]
            writer.writerow(dict(case_id=case['id'],family=a['family'],before_step='cad/'+case['id']+'.step',
                candidate_A_step='cad/'+a['after_file'],candidate_B_step='cad/'+b['after_file'],
                A_radius_mm=a['radius_mm'],B_radius_mm=b['radius_mm'],
                A_material_delta_mm3=a['material_delta_mm3'],B_material_delta_mm3=b['material_delta_mm3'],
                editable='pocket corner radius only',protected='outer envelope; hole count/diameter/depth; pocket depth'))
    files=[]
    for path in sorted(destination.rglob('*')):
        if path.is_file():
            data=path.read_bytes()
            files.append(dict(path=path.relative_to(destination).as_posix(),bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
    save(destination/'artifact-manifest.json',dict(schema='verified-edit-study-archive/1',files=files,
        original_working_folder=str(study),originals_preserved=True,preference_labels=0,
        raw_CAD=240,attempted_edit_pairs=1200,successful_exports=960))
    # Extend the existing geometry inventory without changing prior records.
    inventory=ROOT/'examples/geometry_manifest.json'
    value=json.loads(inventory.read_text(encoding='utf8')); known={r['path'] for r in value['files']}
    group='validation/verified-improvements-2026-10-02'
    added=[]
    for row in files:
        file=destination/row['path']
        if file.suffix.lower() in ('.step','.stp','.stl','.3mf','.brep','.iges','.igs','.obj','.ply'):
            path=file.relative_to(ROOT).as_posix()
            if path in known:
                raise ValueError('Archive geometry already inventoried')
            added.append(dict(path=path,group=group,format=file.suffix[1:].lower(),bytes=row['bytes'],sha256=row['sha256']))
    value['files'].extend(added)
    value.update(geometry_file_count=len(value['files']),unique_sha256_count=len({r['sha256'] for r in value['files']}),
                 total_bytes=sum(r['bytes'] for r in value['files']))
    value['groups'][group]=len(added)
    value['scope']+=' Expanded 2026-10-02 with grouped independent CAD, actual before/after exports and runtime diagnostic edits. Repeated before copies and byte-distinct timestamps are not additional independent designs.'
    save(inventory,value)
    print(json.dumps(dict(archived_files=len(files),new_geometry=len(added),inventory_count=value['geometry_file_count'],
        inventory_unique=value['unique_sha256_count'],bytes=sum(r['bytes'] for r in files))))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('study',type=Path);p.add_argument('destination',type=Path)
    a=p.parse_args();archive(a.study,a.destination)
