"""Reproduce event-section checks from a frozen random-corpus geometry cache.

Run with --corpus PATH --out NEW_PATH. Originals are only hashed, never loaded
into an external service or changed. The whole selection is intentionally kept
alongside every CAD body; whole/single-body duplicates are explicitly counted.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import shutil
import sys
import time

import numpy as np


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def engine_manifest(engine):
    return {p.relative_to(engine).as_posix(): sha(p)
            for package in ('amdfm', 'src') for p in sorted((engine/package).rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}


def worker(args):
    sys.path.insert(0, str(args.engine_root.resolve()))
    import trimesh
    from amdfm.detail import run_detail
    from amdfm.models import Model, plain
    from amdfm.profiles import Profile
    from src.core.mesh_diagnostics import mesh_digest

    started = time.perf_counter()
    cache = args.corpus/args.file_id
    payload = read(cache/'model.json')
    with np.load(cache/'model.npz', allow_pickle=False) as arrays:
        source = Model(trimesh.Trimesh(arrays['vertices'], arrays['faces'], process=False),
            payload['metadata'], payload.get('cad_features', []),
            arrays['face_ids'] if 'face_ids' in arrays else None,
            arrays['body_ids'] if 'body_ids' in arrays else None)
    body = None if args.selection == 'whole' else int(args.selection.split('_')[1])
    model = source.select_body(body)
    fingerprint = model.fingerprint
    original_report_path = cache/(args.selection+'_MEX.json')
    original_report = read(original_report_path) if original_report_path.exists() else None
    result = run_detail(model, Profile(process='MEX', build_volume_mm=None), (0,0,1),
        mode='sections', sampling='events', max_event_samples=args.max_samples, timeout_s=args.timeout)
    # Preserve all measured rows/diagnostics; no full contour coordinates are
    # needed for this reproducible numeric audit of already-cached geometry.
    for row in result.get('rows', []):
        contours = row.pop('outlines', [])
        row['outline_point_count'] = sum(len(ring) for ring in contours)
        row['outlines_sha256'] = hashlib.sha256(json.dumps(contours, separators=(',', ':')).encode()).hexdigest()
    mesh = model.mesh
    points = mesh.triangles - mesh.bounds.mean(axis=0)
    tetra = math.fsum((np.einsum('ij,ij->i', points[:,0], np.cross(points[:,1], points[:,2]))/6).tolist())
    volume = result.get('volume_quadrature_estimate_mm3')
    uniform_path = cache/(args.selection+'_MEX_sections.json')
    uniform = read(uniform_path) if uniform_path.exists() else {}
    record = dict(file_id=args.file_id, selection=args.selection,
        source_filename=source.metadata.get('filename'), source_sha256=source.metadata.get('source_sha256'),
        source_model_fingerprint=source.fingerprint, selected_model_fingerprint=fingerprint,
        selected_body=body, selected_mesh_sha256=mesh_digest(mesh),
        selected_triangles=len(mesh.faces), selected_vertices=len(mesh.vertices),
        cad_geometry_kind=model.metadata.get('cad_geometry_kind'),
        solid_count=model.metadata.get('solid_count'),
        original_report_fingerprint_matches=(original_report['model_fingerprint']==fingerprint) if original_report else None,
        placement_matches_original_report=bool(np.array_equal(result['placement_transform'],
            original_report['current_orientation']['transform'])) if original_report else None,
        reference_tetra_volume_mm3=tetra,
        reference_scope='Signed tetrahedral integral around the mesh bounding-box centre, separate from section construction; ambiguous overlaps are not certified material union.',
        selected_exact_cad_volume_mm3=model.metadata.get('exact_volume_mm3') if model.metadata.get('solid_count') == 1 else None,
        event_relative_difference_from_tetra=volume/tetra-1 if volume is not None and tetra else None,
        uniform64_status=uniform.get('status'),
        uniform64_volume_mm3=uniform.get('volume_midpoint_estimate_mm3'),
        elapsed_wall_seconds=time.perf_counter()-started, detail=result)
    if model.face_ids is not None:
        record['selected_cad_face_ids_sha256'] = hashlib.sha256(np.asarray(model.face_ids, dtype='<i8').tobytes()).hexdigest()
        record['selected_cad_face_id_count'] = len(np.unique(model.face_ids))
    if model.body_ids is not None:
        record['selected_cad_body_ids_sha256'] = hashlib.sha256(np.asarray(model.body_ids, dtype='<i8').tobytes()).hexdigest()
    write(args.out, plain(record))


def main(args):
    args.out = args.out.resolve()
    args.corpus = args.corpus.resolve()
    if args.out.exists():
        raise ValueError('The output path must be new; existing audit evidence is not overwritten.')
    args.out.mkdir(parents=True)
    source_engine = args.engine_root.resolve()
    frozen = args.out/'engine-source'
    for package in ('amdfm', 'src'):
        shutil.copytree(source_engine/package, frozen/package,
            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    before = engine_manifest(frozen)
    sys.path.insert(0, str(frozen))
    from amdfm.processes import run_bounded
    corpus_manifest = read(args.corpus/'manifest.json')
    inventory = {item['id']: item for item in corpus_manifest['inventory']}
    targets, caches = [], {}
    unique_keys = set()
    for cache in sorted(args.corpus.glob('file_*')):
        if not (cache/'model.npz').exists():
            continue
        metadata = read(cache/'model.json')['metadata']
        with np.load(cache/'model.npz', allow_pickle=False) as arrays:
            ids = np.unique(arrays['body_ids']) if 'body_ids' in arrays else []
        selections = ['whole']+[f'body_{int(i):03d}' for i in ids if i > 0]
        caches[cache.name] = dict(npz_sha256=sha(cache/'model.npz'), json_sha256=sha(cache/'model.json'),
            source_sha256=inventory[cache.name]['sha256'], source_relative_path=inventory[cache.name]['relative_path'])
        for selection in selections:
            key = (cache.name, 'body_001' if selection == 'whole' and metadata.get('solid_count') == 1 else selection)
            unique_keys.add(key)
            targets.append(dict(file_id=cache.name, selection=selection, unique_geometry_key=list(key)))
    manifest = dict(created_utc=datetime.now(timezone.utc).isoformat(),
        source_engine=str(source_engine), frozen_engine=str(frozen), corpus=str(args.corpus.resolve()),
        script_sha256=sha(__file__), engine_files_sha256=before,
        python=sys.version, platform=platform.platform(), numpy=np.__version__,
        settings=dict(direction=[0,0,1], process='MEX', process_scope='Process-neutral section geometry; all four process routes covered by integration tests.',
            build_volume_mm=None, sampling='events', max_samples=args.max_samples,
            max_total_segments=1_500_000, timeout_seconds=args.timeout, jobs=args.jobs),
        target_count=len(targets), unique_geometry_count=len(unique_keys),
        whole_single_body_duplicates=len(targets)-len(unique_keys),
        counting_note='Whole selections for single-solid CAD duplicate that individual body. 195 selections correspond to 186 unique geometry selections in this corpus.',
        cache_provenance=caches, targets=targets)
    write(args.out/'manifest.json', manifest)
    (args.out/'records').mkdir()
    def dispatch(target):
        destination = args.out/'records'/(target['file_id']+'_'+target['selection']+'.json')
        command = [sys.executable, str(Path(__file__).resolve()), '--worker', '--engine-root', str(frozen),
            '--corpus', str(args.corpus.resolve()), '--out', str(destination.resolve()),
            '--file-id', target['file_id'], '--selection', target['selection'],
            '--timeout', str(args.timeout), '--max-samples', str(args.max_samples)]
        started = time.perf_counter()
        try:
            process = run_bounded(command, cwd=frozen, timeout=args.timeout+120)
            if process.returncode or not destination.exists():
                raise RuntimeError(f'Worker return code {process.returncode}: {process.stderr}')
            record = read(destination)
            return dict(**target, status=record['detail']['status'],
                reason=record['detail'].get('reason'), requested_samples=record['detail'].get('requested_samples'),
                complete_samples=record['detail'].get('complete_samples'),
                budget_exceeded=record['detail'].get('budget_exceeded', False),
                volume_quadrature_estimate_mm3=record['detail'].get('volume_quadrature_estimate_mm3'),
                relative_difference_from_tetra=record['event_relative_difference_from_tetra'],
                elapsed_wall_seconds=record['elapsed_wall_seconds'], record_sha256=sha(destination))
        except Exception as exc:
            record = dict(**target, status='unknown', reason='audit_worker_failure', exception=str(exc),
                elapsed_wall_seconds=time.perf_counter()-started)
            write(destination, record)
            return record
    completed = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(dispatch, target) for target in targets]
        for future in as_completed(futures):
            record = future.result()
            completed.append(record)
            write(args.out/'progress.json', sorted(completed, key=lambda r:(r['file_id'], r['selection'])))
            print(record['file_id'], record['selection'], record['status'],
                record.get('complete_samples'), record.get('requested_samples'), flush=True)
    completed.sort(key=lambda r:(r['file_id'], r['selection']))
    original_sources_unchanged = all(sha(item['absolute_path']) == item['sha256']
        for item in inventory.values() if item['id'] in caches)
    cache_unchanged = all(sha(args.corpus/key/'model.npz') == val['npz_sha256'] and
        sha(args.corpus/key/'model.json') == val['json_sha256'] for key, val in caches.items())
    status_counts = {status:sum(r['status'] == status for r in completed) for status in ('complete', 'partial', 'unknown')}
    summary = dict(completed_utc=datetime.now(timezone.utc).isoformat(),
        target_count=len(completed), unique_geometry_count=len(unique_keys),
        whole_single_body_duplicates=len(completed)-len(unique_keys), status_counts=status_counts,
        original_sources_unchanged=original_sources_unchanged, cache_unchanged=cache_unchanged,
        frozen_engine_unchanged=before == engine_manifest(frozen), results=completed)
    write(args.out/'summary.json', summary)
    print(json.dumps({k:v for k,v in summary.items() if k != 'results'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--engine-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--timeout', type=float, default=90)
    parser.add_argument('--max-samples', type=int, default=8192)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--file-id')
    parser.add_argument('--selection')
    arguments = parser.parse_args()
    if arguments.worker:
        worker(arguments)
    else:
        main(arguments)
