"""Record the frozen source/Desktop equality and completed test runs."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path('C:/Users/JIN/Documents/ChatGPT/DFM/DFM-Project')
DESKTOP = Path('C:/Users/JIN/Desktop/AM-DFM_v3_0')
OUT = ROOT / 'validation/conclusion-planning-2026-09-29'


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
              verified_equal_files=rows, tests=[suite('full-frozen.xml'),suite('desktop-frozen.xml')],
              plan_model_sha256=sha(ROOT / 'data/models/plan_ranker_v1.json'),
              python={key:subprocess.check_output([str(base / '.venv/Scripts/python.exe'),'--version'],text=True).strip()
                      for key,base in [('source',ROOT),('desktop',DESKTOP)]})
destination = OUT / 'summary.json'
with destination.open('x',encoding='utf-8',newline='\n') as stream:
    json.dump(record,stream,ensure_ascii=False,indent=2)
    stream.write('\n')
print(json.dumps({key:record[key] for key in ('source_runtime_sha256','tests','plan_model_sha256','python')},ensure_ascii=False,indent=2))
