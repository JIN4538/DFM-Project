"""Independent exact CAD dimensions for every certified external feature group."""
import argparse, concurrent.futures, io, json, sqlite3, sys, tempfile, time
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dfm.cad_graph import read_step_graph
from dfm.external_features_review import pocket_dimensions
from dfm.feature_learning import CURVED_CLASS_NAMES


def worker(job):
    identifier, split, group_id, raw, graph_blob = job
    try:
        with np.load(io.BytesIO(graph_blob), allow_pickle=False) as z:
            y, inst, bottom = z['y'], z['inst'], z['bottom']
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'original.step'
            path.write_bytes(raw)
            graph = read_step_graph(path)
        measured = graph['measurements']
        seen = set()
        pockets = []
        attempted = 0
        for i, label in enumerate(y):
            if i in seen or int(label) not in (13, 14, 15):
                continue
            group = sorted(np.flatnonzero(inst[i]).tolist())
            seen.update(group)
            if not group:
                continue
            attempted += 1
            candidate = dict(feature=CURVED_CLASS_NAMES[int(label)], face_ids=[measured[j]['face_id'] for j in group], measured_faces=[measured[j] for j in group])
            for j in group:
                if not bottom[j] or np.linalg.norm(measured[j]['normal']) < .5:
                    continue
                result = pocket_dimensions(candidate, measured[j]['normal'])
                if result:
                    result['direction'] = measured[j]['normal']
                    result['source_instance_face_ids'] = candidate['face_ids']
                    pockets.append(result)
                    break
        return identifier, split, group_id, json.dumps(dict(id=identifier, split=split, group_id=group_id, pockets=pockets, attempted_instances=attempted)), None
    except Exception as error:
        return identifier, split, group_id, None, str(error)


def main(root, workers):
    root.mkdir(exist_ok=True)
    output = sqlite3.connect(root/'measured-features.sqlite')
    output.execute('CREATE TABLE IF NOT EXISTS parts(id TEXT PRIMARY KEY,split TEXT,group_id TEXT,measurement TEXT,error TEXT)')
    done = {r[0] for r in output.execute('SELECT id FROM parts')}
    verified = sqlite3.connect(f'file:{(root/"mfinstseg-verified.sqlite").as_posix()}?mode=ro', uri=True)
    source = sqlite3.connect(f'file:{(ROOT.parent/"study/external-training-2026-09-30/mfinstseg-complete.sqlite").as_posix()}?mode=ro', uri=True)
    start = time.monotonic()
    attempted = 0
    def commit(jobs, pool):
        for row in pool.map(worker, jobs):
            output.execute('INSERT INTO parts VALUES (?,?,?,?,?)', row)
        output.commit()
        print(json.dumps(dict(measured_this_run=attempted, records=output.execute('SELECT COUNT(*) FROM parts').fetchone()[0], seconds=time.monotonic()-start)), flush=True)
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        queue = []
        for identifier, split, group, blob in verified.execute('SELECT id,split,group_id,graph FROM parts WHERE graph IS NOT NULL ORDER BY id'):
            if identifier in done:
                continue
            with np.load(io.BytesIO(blob), allow_pickle=False) as z:
                measurable = np.isin(z['y'], [13, 14, 15]).any()
            if not measurable:
                output.execute('INSERT INTO parts VALUES (?,?,?,?,?)', (identifier, split, group, json.dumps(dict(id=identifier, split=split, group_id=group, pockets=[], attempted_instances=0)), None))
                continue
            raw = source.execute('SELECT step FROM parts WHERE id=?', (identifier,)).fetchone()[0]
            queue.append((identifier, split, group, raw, blob))
            attempted += 1
            if len(queue) >= workers*16:
                commit(queue, pool)
                queue = []
        if queue:
            commit(queue, pool)
    output.commit()
    cases = []
    instances = 0
    for raw, in output.execute('SELECT measurement FROM parts WHERE measurement IS NOT NULL'):
        record = json.loads(raw)
        instances += record['attempted_instances']
        if record['pockets']:
            cases.append(record)
    (root/'pocket-cases-full.json').write_text(json.dumps(cases, separators=(',', ':')), encoding='utf8')
    summary = dict(corpus_records=output.execute('SELECT COUNT(*) FROM parts').fetchone()[0], measurable_instances_attempted=instances,
        verified_pocket_parts=len(cases), verified_pockets=sum(len(c['pockets']) for c in cases),
        failures=list(output.execute('SELECT error,COUNT(*) FROM parts WHERE error IS NOT NULL GROUP BY error')),
        policy='Author instance and bottom labels select groups only; OCCT vertices and planes independently certify convex prism dimensions and entry circle', seconds=time.monotonic()-start)
    (root/'pocket-measurement-audit.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary), flush=True)
    output.close(); verified.close(); source.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    main(args.root.resolve(), args.workers)
