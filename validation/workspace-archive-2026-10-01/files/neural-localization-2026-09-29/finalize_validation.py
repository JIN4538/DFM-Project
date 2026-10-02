"""Record the frozen source/Desktop equality and completed test runs."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path('C:/Users/JIN/Documents/ChatGPT/DFM/DFM-Project')
DESKTOP = Path('C:/Users/JIN/Desktop/AM-DFM_v3_0')
OUT = ROOT / 'validation/neural-localization-2026-09-29'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def suite(name):
    path = OUT / name
    root = ET.parse(path).getroot()
    rows = list(root.iter('testsuite'))
    result = {key:sum(int(row.get(key, 0)) for row in rows) for key in ('tests','failures','errors','skipped')}
    result.update(path=name, seconds=sum(float(row.get('time',0)) for row in rows), sha256=sha(path))
    if result['failures'] or result['errors'] or result['skipped']:
        raise RuntimeError('Final test run is incomplete: ' + str(result))
    return result


files = [ROOT / 'app.py']
for directory, pattern in [('amdfm','*.py'),('dfm','*.py'),('src/core','*.py'),('data/conditions','*.json'),('data/models','**/*.json')]:
    files.extend(sorted((ROOT / directory).glob(pattern)))
rows = []
for source in files:
    relative = source.relative_to(ROOT)
    target = DESKTOP / relative
    if sha(source) != sha(target):
        raise RuntimeError('Desktop mismatch: ' + str(relative))
    rows.append(dict(path=relative.as_posix(), sha256=sha(source), bytes=source.stat().st_size))

record = dict(timestamp_utc=datetime.now(timezone.utc).isoformat(), source=str(ROOT), desktop=str(DESKTOP),
              source_runtime_sha256=hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(),
              verified_equal_files=rows, tests=[suite('full-final.xml'),suite('desktop-final.xml'),suite('wall-framing-final.xml'),suite('desktop-wall-final.xml')],
              plan_model_sha256=sha(ROOT / 'data/models/plan_ranker_v1.json'),
              neural_model_sha256=sha(ROOT / 'data/models/neural_orientation_v1.json'),
              rl_model_sha256=sha(ROOT / 'data/models/rl_planner_v1.json'),
              python={key:subprocess.check_output([str(base / '.venv/Scripts/python.exe'),'--version'],text=True).strip()
                      for key,base in [('source',ROOT),('desktop',DESKTOP)]})
record['validation_sequence'] = dict(
    full_and_desktop_108_code_digest='04ba33c513121166a9527a47e00d052e6bc15e5334e56ef467ae52d37304f95c',
    final_code_digest='a9148fdddce5c474a6a051198a9ca463be6133511801b25335447ef2045cf56a',
    final_change='wall_visual.py display-axis framing only, equal millimetre scale preserved; measured geometry and both learned model runtimes unchanged',
    final_change_checks=['wall-framing-final.xml','desktop-wall-final.xml'])
destination = OUT / 'summary.json'
with destination.open('x',encoding='utf-8',newline='\n') as stream:
    json.dump(record,stream,ensure_ascii=False,indent=2)
    stream.write('\n')
print(json.dumps({key:record[key] for key in ('source_runtime_sha256','tests','plan_model_sha256','neural_model_sha256','rl_model_sha256','python')},ensure_ascii=False,indent=2))
