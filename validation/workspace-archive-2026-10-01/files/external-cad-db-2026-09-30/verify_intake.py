"""Independent, read-only verification of the actual two-sample database."""
from pathlib import Path
import hashlib
import json
import sqlite3

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1] / 'DFM-Project'
SOURCE = HERE.parent / 'public-cad-data-2026-09-29' / 'mfcad'
DATABASE = HERE / 'external_cad.sqlite'
baseline = json.loads((HERE / 'model-baseline.json').read_text())
for name, digest in baseline.items():
    assert hashlib.sha256((REPO / name).read_bytes()).hexdigest() == digest

with sqlite3.connect(DATABASE.as_uri() + '?mode=ro', uri=True) as db:
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    raw_rows = db.execute('SELECT filename, sha256, bytes, content FROM raw_files').fetchall()
    for name, digest, size, raw in raw_rows:
        assert raw == (SOURCE / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == digest
        assert len(raw) == size
    assert len(raw_rows) == 12
    manifest = db.execute('SELECT source_manifest_blob FROM import_runs').fetchone()[0]
    assert manifest == (SOURCE / 'source_manifest.json').read_bytes()
    samples = []
    for identifier, ready, geo_raw in db.execute('SELECT id, training_ready, geometry_json FROM samples'):
        geo = json.loads(geo_raw)
        assert ready == 0 and geo['valid'] is True and geo['solid_count'] == 1
        count = db.execute('SELECT count(*) FROM face_labels WHERE sample_id=?', (identifier,)).fetchone()[0]
        assert count == geo['face_count']
        samples.append({'sample': identifier, 'faces': count, 'dimensions_mm': geo['dimensions_mm'],
                        'volume_mm3': geo['volume_mm3'], 'cad_valid': geo['valid'], 'training_ready': False})
    assert [item['faces'] for item in samples] == [11, 27]
    source_labels = json.loads((SOURCE / 'mfinstseg_sample.json').read_text())[0][1]['seg']
    for index, label, entity, status in db.execute(
            "SELECT label_index,semantic_label,step_entity_id,mapping_status FROM face_labels WHERE sample_id='mfinstseg_sample'"):
        assert source_labels[str(index)] == label
        assert entity is None and status == 'provisional_ocp_ordinal_not_upstream_verified'
    summary = json.loads(db.execute('SELECT summary_json FROM import_runs').fetchone()[0])
    summary['database'] = str(DATABASE)
    summary['verification'] = {'sqlite_integrity': 'ok', 'foreign_keys': 'ok',
        'raw_files_byte_identical': 12, 'source_manifest_byte_identical': True,
        'unchanged_model_files': len(baseline), 'targeted_tests_passed': 12, 'samples': samples}
    summary['database_sha256'] = hashlib.sha256(DATABASE.read_bytes()).hexdigest()
    output = REPO / 'validation' / 'external-cad-intake-2026-09-30' / 'summary.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
