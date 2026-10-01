"""Resumeable full-corpus CAD/label certification; source archives stay immutable."""
import argparse, concurrent.futures, hashlib, io, json, sqlite3, sys, tempfile, time, zipfile
from pathlib import Path
import ijson
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dfm.cad_graph import read_step_graph
from scripts.verify_mfinstseg_graphs import certify


def validate_labels(identifier, raw, count):
    entries = [row[1] for row in json.loads(raw) if row[0] == identifier]
    if len(entries) != 1:
        raise ValueError('Original label identifier mismatch')
    label = entries[0]
    y = np.array([label['seg'][str(i)] for i in range(count)], dtype=np.int64)
    bottom = np.array([label['bottom'][str(i)] for i in range(count)], dtype=np.uint8)
    instance = np.asarray(label['inst'], dtype=np.uint8)
    if instance.shape != (count, count) or not np.array_equal(instance, instance.T):
        raise ValueError('Invalid instance matrix shape/symmetry')
    if not np.isin(instance, [0, 1]).all() or not np.isin(bottom, [0, 1]).all() or not np.isin(y, np.arange(25)).all():
        raise ValueError('Label value outside schema')
    return y, bottom, instance


def worker(job):
    identifier, raw, label, original = job
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'source.step'
            path.write_bytes(raw)
            graph = read_step_graph(path)
        audit = certify(graph, original)
        y, bottom, inst = validate_labels(identifier, label, len(graph['x']))
        group = ','.join(map(str, sorted(v for v in y.tolist() if v != 24)))
        bucket = int(hashlib.sha256(group.encode()).hexdigest()[:8], 16) % 100
        split = 'train' if bucket < 70 else 'val' if bucket < 85 else 'test'
        measurements = graph['measurements']
        buffer = io.BytesIO()
        np.savez_compressed(buffer, x=graph['x'], edges=graph['edges'], y=y, bottom=bottom, inst=inst,
            centroids=np.array([m['centroid_mm'] for m in measurements]),
            normals=np.array([m['normal'] if m['normal'] is not None else [0., 0., 0.] for m in measurements]),
            areas=np.array([m['area_mm2'] for m in measurements]),
            scale=np.array(graph['scale_mm']))
        audit['step_sha256'] = hashlib.sha256(raw).hexdigest()
        audit['label_sha256'] = hashlib.sha256(label).hexdigest() if isinstance(label, bytes) else hashlib.sha256(label.encode()).hexdigest()
        audit['bottom_faces'] = int(bottom.sum())
        return identifier, split, group, buffer.getvalue(), json.dumps(audit), None
    except Exception as error:
        return identifier, None, None, None, None, str(error)


def main(root, workers, limit):
    root.mkdir(parents=True, exist_ok=True)
    target = root / 'mfinstseg-verified.sqlite'
    db = sqlite3.connect(target)
    db.execute('CREATE TABLE IF NOT EXISTS parts(id TEXT PRIMARY KEY,split TEXT,group_id TEXT,graph BLOB,audit TEXT,error TEXT)')
    done = {r[0] for r in db.execute('SELECT id FROM parts')}
    source = sqlite3.connect(f'file:{(ROOT.parent / "study/external-training-2026-09-30/mfinstseg-complete.sqlite").as_posix()}?mode=ro', uri=True)
    archive = ROOT.parent / 'study/external-training-2026-09-30/archives/MFInstSeg-data2.zip'
    started = time.monotonic()
    attempted = 0
    skipped = 0
    def commit(jobs, pool):
        for result in pool.map(worker, jobs):
            db.execute('INSERT INTO parts VALUES (?,?,?,?,?,?)', result)
        db.commit()
        counts = list(db.execute('SELECT split,COUNT(*) FROM parts GROUP BY split'))
        print(json.dumps(dict(attempted_this_run=attempted, counts=counts, seconds=time.monotonic()-started)), flush=True)
    with zipfile.ZipFile(archive) as zip_source, concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        jobs = []
        with zip_source.open('aag/graphs.json') as stream:
            for identifier, original in ijson.items(stream, 'item', use_float=True):
                if identifier in done:
                    continue
                row = source.execute('SELECT step,labels,split FROM parts WHERE id=?', (identifier,)).fetchone()
                if row is None or row[2] in ('quarantine', 'unassigned'):
                    skipped += 1
                    continue
                compact = {k: original[k] for k in ('graph', 'graph_face_attr')}
                jobs.append((identifier, row[0], row[1], compact))
                attempted += 1
                if len(jobs) >= workers * 16 or (limit and attempted >= limit):
                    commit(jobs, pool)
                    jobs = []
                if limit and attempted >= limit:
                    break
        if jobs:
            commit(jobs, pool)
    counts = list(db.execute('SELECT split,COUNT(*) FROM parts GROUP BY split'))
    summary = dict(audited=sum(c for _, c in counts), accepted=sum(c for s, c in counts if s), counts=counts,
        skipped_source_quarantine_or_missing=skipped, complete_stream=not bool(limit),
        failures=list(db.execute('SELECT error,COUNT(*) FROM parts WHERE error IS NOT NULL GROUP BY error ORDER BY COUNT(*) DESC LIMIT 30')),
        ordinal_policy='Every admitted CAD matches ordered analytic surface types, centroids, areas and all directed adjacency edges',
        targets='Author semantic, instance membership and bottom-face labels; no optimal design or manufacturing success labels',
        split_policy='SHA256 non-stock semantic label multiset; all members of a feature-multiset family share one split',
        graph_source_sha256=hashlib.sha256((ROOT / 'dfm/cad_graph.py').read_bytes()).hexdigest(),
        seconds=time.monotonic()-started)
    (root / 'mfinstseg-verified-audit.json').write_text(json.dumps(summary, indent=2), encoding='utf8')
    print(json.dumps(summary), flush=True)
    source.close()
    db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--limit', type=int, default=0)
    args = parser.parse_args()
    main(args.root.resolve(), args.workers, args.limit)
