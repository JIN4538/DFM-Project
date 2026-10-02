"""Published labels, frozen families and actual exports retain their provenance."""
import csv
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'validation/verified-improvements-2026-10-02'


def test_frozen_families_and_edit_variant_splits_do_not_leak():
    manifest=json.loads((FOLDER/'cad/manifest.json').read_text(encoding='utf8'))
    records=manifest['records']
    assert manifest['created_before_labels']
    assert manifest['splits']==dict(train=120,validation=60,test=60)
    assert len({r['family'] for r in records})==48
    families={s:{r['family'] for r in records if r['split']==s} for s in manifest['splits']}
    assert not (families['train'] & families['validation'] or families['train'] & families['test'] or families['validation'] & families['test'])
    assert len({r['sha256'] for r in records})==240
    for row in records:
        assert hashlib.sha256((FOLDER/'cad'/row['file']).read_bytes()).hexdigest()==row['sha256']
    labels=json.loads((FOLDER/'cad/labels.json').read_text(encoding='utf8'))
    assert labels['manifest_sha256']==hashlib.sha256((FOLDER/'cad/manifest.json').read_bytes()).hexdigest()
    by_id={r['id']:r for r in records}
    rows=[r for c in labels['cases'] for r in c['rows']]
    assert len(rows)==1200 and sum(r['valid'] for r in rows)==960
    for row in rows:
        assert row['family']==by_id[row['case_id']]['family']
        assert row['split']==by_id[row['case_id']]['split']
        if row['valid']:
            assert not row['protected_violation']
            assert hashlib.sha256((FOLDER/'cad'/row['after_file']).read_bytes()).hexdigest()==row['after_sha256']


def test_cad_learning_comparison_is_preserved_and_no_expert_labels_are_fabricated():
    result=json.loads((FOLDER/'cad/cnc-comparison.json').read_text(encoding='utf8'))
    assert result['test_CAD']==60 and result['test_records']==300
    assert result['methods']['rules_1']['optimal']==60
    assert result['methods']['learned_verified_1']['optimal']==43
    assert result['methods']['rules_1']['queries']==result['methods']['learned_verified_1']['queries']==60
    with (FOLDER/'expert_pairs.csv').open(encoding='utf-8-sig',newline='') as file:
        rows=list(csv.DictReader(file))
    assert len(rows)==30
    assert all(not row['preferred_A_B_tie_neither'] and not row['annotator'] for row in rows)


def test_am_uses_product_v4_and_charges_all_baseline_directions():
    result=json.loads((FOLDER/'am-equal-budget-v4-03/result.json').read_text(encoding='utf8'))
    assert result['case_count']==120 and result['group_count']==24
    for row in result['results']:
        for name, values in row['methods'].items():
            assert values['queries']==int(name.rsplit('_',1)[1])
            assert len(values['extra_direction_indices'])==values['queries']-26
    for budget in (32,38,50):
        assert result['summary'][f'neural_verified_{budget}']['same_as_geometry']==120
        assert result['summary'][f'hybrid_verified_{budget}']['same_as_geometry']==120
