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
    assert result['geometry_files']==106
    assert result['unique_sha256']==100


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
    assert '무작위 형상 테스트' in app.selectbox(key='source').options
    app.selectbox(key='source').select('무작위 형상 테스트').run()
    assert not app.exception
    assert len(app.selectbox(key='random_example').options)==26
    assert any('저장소에 포함된 26개 형상' in c.value for c in app.caption)
