"""Published fixtures must work independently of the developer's Desktop."""
import hashlib
import json
from pathlib import Path

from streamlit.testing.v1 import AppTest
from scripts.verify_geometry_inventory import verify

ROOT=Path(__file__).resolve().parents[1]


def test_all_shipped_geometry_matches_published_inventory():
    result=verify(ROOT)
    assert result['verified'],result['errors']
    assert result['geometry_files']==2934
    assert result['unique_sha256']==1728


def test_archived_research_cad_has_original_source_and_exact_hash():
    inventory=json.loads((ROOT/'examples/geometry_manifest.json').read_text(encoding='utf8'))
    archive=json.loads((ROOT/'validation/workspace-archive-2026-10-01/manifest.json').read_text(encoding='utf8'))
    sources={r['repository_file']:r for r in archive['files'] if r['status']=='archived'}
    records=[r for r in inventory['files'] if r['group']=='existing/workspace-research-archive']
    assert len(records)==299
    for row in records:
        source=sources[row['path']]
        assert row['study_source']==source['study_file']
        assert row['sha256']==source['sha256']
        assert row['bytes']==source['bytes']


def test_public_step_demos_have_original_hashes_and_explicit_rights():
    directory=ROOT/'examples/public_demo'
    records=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    assert len(records)==14
    assert len(list(directory.glob('*.step')))==14
    for row in records:
        assert hashlib.sha256((directory/row['file']).read_bytes()).hexdigest()==row['sha256']
        assert row['source_url'].startswith('https://')
        assert row['license'] in ('CC0-1.0','U.S. Government public domain; acknowledge NIST')
        if row['solid_count']:
            assert row['cad_volume_mm3']>0 and row['cad_geometry_kind']=='solid'
        else:
            assert row['cad_volume_mm3'] is None and row['cad_geometry_kind']=='surface'
            assert '표면 모델' in row['title']


def test_corpus_including_supplier_metadata_matches_original_audit():
    directory=ROOT/'examples/corpus'
    corpus=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    audit=json.loads((ROOT/'validation/v3/random-corpus/independent/initial-manifest.json').read_text(encoding='utf-8'))
    hashes={r['relative_source']:r['sha256'] for r in audit['files']}
    assert corpus['geometry_count']==26 and corpus['metadata_count']==5
    for row in corpus['files']:
        assert hashlib.sha256((directory/row['path']).read_bytes()).hexdigest()==row['sha256']
        if row['kind']=='geometry':
            assert hashes[row['path']]==row['sha256']


def test_random_corpus_picker_works_without_a_desktop_folder(monkeypatch,tmp_path):
    monkeypatch.setattr(Path,'home',classmethod(lambda cls:tmp_path))
    app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=90).run()
    assert app.selectbox(key='source').options == ['적층 시연용 형상', '절삭 시연용 형상', '업로드']
    app.selectbox(key='demo_example').select('장착 브래킷 · STP').run()
    assert not app.exception
    assert len(app.selectbox(key='demo_example').options) >= 26
    assert app.selectbox(key='demo_example').value == '장착 브래킷 · STP'
