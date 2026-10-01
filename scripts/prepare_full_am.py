"""All eligible public meshes, bounded-memory exact labels, resumeable shards."""
import argparse, concurrent.futures, hashlib, io, json, os, sqlite3, sys, time
from pathlib import Path
import numpy as np
import trimesh
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from amdfm.orientation import candidates, measure_orientation, ANGLE_COSINE_TOLERANCE
from amdfm.neural_orientation import feature_arrays, fibonacci_directions
from amdfm.profiles import Profile
from scripts.import_thingi_training import ALLOWED
ANGLES = (25., 35., 45., 60., 75.)


def chunk_labels(mesh, directions, angles=ANGLES, block=4096):
    """Compute original-mesh projections without a faces x views allocation.

    Plane exclusion uses exactly the runtime's placed AABB tolerance. No
    decimation, interpolated surfaces, canonical-orientation labels or units
    inferred from the source are used.
    """
    directions = np.asarray(directions, dtype=float)
    directions = directions / np.linalg.norm(directions, axis=1)[:, None]
    matrices = np.array([trimesh.geometry.align_vectors(d, [0., 0., 1.])[:3, :3] for d in directions])
    axes = matrices.reshape(-1, 3).T
    lo = np.full(axes.shape[1], np.inf)
    hi = np.full(axes.shape[1], -np.inf)
    for start in range(0, len(mesh.vertices), block):
        projected = mesh.vertices[start:start+block] @ axes
        lo = np.minimum(lo, projected.min(0))
        hi = np.maximum(hi, projected.max(0))
    dims = (hi-lo).reshape(-1, 3)
    minima = lo.reshape(-1, 3)[:, 2]
    tolerance = np.maximum(1e-9, dims.max(1)*1e-10)
    overhang = np.zeros((len(angles), len(directions)))
    areas, normals = mesh.area_faces, mesh.face_normals
    for start in range(0, len(mesh.faces), block):
        face = mesh.faces[start:start+block]
        xyz = mesh.vertices[face]
        projected = xyz @ directions.T
        above_plate = projected.max(1)-minima > tolerance
        nz = normals[start:start+block] @ directions.T
        weighted = areas[start:start+block, None] * np.maximum(-nz, 0.)
        for j, angle in enumerate(angles):
            mask = above_plate & (nz < -np.cos(np.deg2rad(angle))-ANGLE_COSINE_TOLERANCE)
            overhang[j] += np.sum(weighted*mask, axis=0)
    diagonal = np.linalg.norm(mesh.extents)
    return dims[:, 2]/diagonal, overhang/mesh.area


def worker(job):
    identifier, dataset, family, group, split, raw, sha, kind, output = job
    record = dict(id=identifier, dataset=dataset, family=family, group=group, split=split, sha256=sha)
    try:
        if kind == 'stl':
            mesh = trimesh.load(io.BytesIO(raw), file_type='stl', force='mesh', process=True)
        else:
            with np.load(io.BytesIO(raw), allow_pickle=False) as z:
                mesh = trimesh.Trimesh(z['vertices'], z['facets'], process=False)
        record['faces'] = len(mesh.faces)
        if len(mesh.faces) < 4 or not np.isfinite(mesh.vertices).all():
            raise ValueError('Invalid finite mesh')
        if not mesh.is_volume or not mesh.is_watertight or not mesh.is_winding_consistent:
            raise ValueError('Not a closed, consistently wound positive volume')
        mesh.vertices = (mesh.vertices-mesh.vertices.mean(0))/max(mesh.extents)*100
        seed = int(hashlib.sha256(identifier.encode()).hexdigest()[:8], 16)
        rng = np.random.default_rng(seed)
        rotation = trimesh.transformations.euler_matrix(*rng.uniform(-np.pi, np.pi, 3))[:3, :3]
        mesh.vertices = mesh.vertices @ rotation.T
        base = np.array(list(candidates(None, dense=True).values()))
        queries = fibonacci_directions(48) @ rotation.T
        height, overhang = chunk_labels(mesh, np.concatenate([base, queries]))
        error = 0.
        # Every mesh has a separate runtime calculation for a selected query.
        k = seed % len(queries)
        j = seed % len(ANGLES)
        measured = measure_orientation(mesh, queries[k], Profile(process='MEX', overhang_angle_deg=ANGLES[j]))
        error = max(abs(measured['height_mm']/np.linalg.norm(mesh.extents)-height[26+k]),
                    abs(measured['overhang_projected_area_sum_mm2']/mesh.area-overhang[j, 26+k]))
        if error > 1e-7:
            raise ValueError(f'Independent runtime mismatch {error:g}')
        arrays = [feature_arrays(dict(height=height[:26], overhang=overhang[j, :26]), queries, angle) for j, angle in enumerate(ANGLES)]
        path = Path(output)/split/(hashlib.sha256((dataset+':'+identifier).encode()).hexdigest()+'.npz')
        np.savez_compressed(path, height_x=arrays[0]['height'].astype('float32'), height_y=height[26:].astype('float32'),
            overhang_x=np.concatenate([a['overhang'] for a in arrays]).astype('float32'),
            overhang_y=overhang[:, 26:].reshape(-1).astype('float32'))
        record.update(path=str(path.relative_to(output)), independent_error=error, accepted=True)
    except Exception as error:
        record.update(accepted=False, reason=str(error))
    return record


def eligible_thing(license, quality, reason):
    if license not in ALLOWED or reason == 'cross-split exact duplicate':
        return False
    q = json.loads(quality)
    return (q.get('solid') == 1 and q.get('num_self_intersections') == 0 and q.get('num_connected_components') == 1
        and q.get('oriented') == 1 and q.get('num_geometrical_degenerated_faces') == 0 and q.get('num_boundary_edges') == 0)


def main(root, workers, limit):
    out = root/'am-full'
    for split in ('train', 'validation', 'test'):
        (out/split).mkdir(parents=True, exist_ok=True)
    index = out/'index.sqlite'
    db = sqlite3.connect(index)
    db.execute('CREATE TABLE IF NOT EXISTS records(dataset TEXT,id TEXT,split TEXT,group_id TEXT,accepted INTEGER,record TEXT,PRIMARY KEY(dataset,id))')
    done = set(db.execute('SELECT dataset,id FROM records'))
    public = sqlite3.connect(f'file:{(ROOT.parent/"study/ai-expansion-2026-09-30/public-expansion.sqlite").as_posix()}?mode=ro', uri=True)
    things = sqlite3.connect(f'file:{(ROOT.parent/"study/external-training-2026-09-30/thingi.sqlite").as_posix()}?mode=ro', uri=True)
    started = time.monotonic()
    attempted = 0
    def jobs():
        for identifier, dataset, family, group, split, raw, sha in public.execute('SELECT id,dataset,family,group_id,split,stl,stl_sha256 FROM parts ORDER BY id'):
            if (dataset, identifier) not in done and split in ('train', 'validation', 'test'):
                yield identifier, dataset, family, group, split, raw, sha, 'stl', str(out)
        for identifier, thing, split, license, quality, reason, raw, sha in things.execute('SELECT id,thing_id,split,license,quality,reason,npz,sha256 FROM parts ORDER BY id'):
            if ('Thingi10K', str(identifier)) not in done and eligible_thing(license, quality, reason):
                yield str(identifier), 'Thingi10K', 'public_thing', 'thing:'+str(thing), split, raw, sha, 'npz', str(out)
    def commit(queue, pool):
        for record in pool.map(worker, queue):
            db.execute('INSERT INTO records VALUES (?,?,?,?,?,?)', (record['dataset'], record['id'], record['split'], record['group'], int(record['accepted']), json.dumps(record)))
        db.commit()
        print(json.dumps(dict(attempted=attempted, counts=list(db.execute('SELECT dataset,accepted,COUNT(*) FROM records GROUP BY dataset,accepted')), seconds=time.monotonic()-started)), flush=True)
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=1), concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        queue = []
        for job in jobs():
            queue.append(job)
            attempted += 1
            if len(queue) >= workers*4 or (limit and attempted >= limit):
                commit(queue, pool)
                queue = []
            if limit and attempted >= limit:
                break
        if queue:
            commit(queue, pool)
    leak = db.execute('SELECT COUNT(*) FROM (SELECT group_id FROM records WHERE accepted=1 GROUP BY group_id HAVING COUNT(DISTINCT split)>1)').fetchone()[0]
    if leak:
        raise ValueError('Geometry family crossed splits')
    summary = dict(counts=list(db.execute('SELECT dataset,split,accepted,COUNT(*),COUNT(DISTINCT group_id) FROM records GROUP BY dataset,split,accepted')),
        attempted_this_run=attempted, complete_stream=not bool(limit), seconds=time.monotonic()-started,
        rejected=list(db.execute('SELECT record FROM records WHERE accepted=0')),
        independent_max_error=max((json.loads(r[0]).get('independent_error', 0.) for r in db.execute('SELECT record FROM records WHERE accepted=1')), default=0.),
        cross_split_family_count=leak, query_views_per_mesh=48, angles=list(ANGLES), complexity_limit=None,
        labels='Exact original-mesh height and projected downward area. Every accepted mesh checked independently against runtime geometry engine.')
    (out/'audit.json').write_text(json.dumps(summary, indent=2), encoding='utf8')
    print(json.dumps({k:v for k,v in summary.items() if k != 'rejected'}), flush=True)
    db.close()
    public.close()
    things.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--limit', type=int, default=0)
    args = parser.parse_args()
    main(args.root.resolve(), args.workers, args.limit)
