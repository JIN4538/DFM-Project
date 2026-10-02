"""Intake is byte-preserving storage, never evidence of model training."""
from pathlib import Path
import hashlib
import json
import pickle
import sqlite3

import pytest

from scripts.import_external_cad_data import import_corpus


def write_manifest(source):
    rows = []
    for path in sorted(source.iterdir()):
        if path.name == "source_manifest.json":
            continue
        raw = path.read_bytes()
        rows.append({
            "file": path.name,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "upstream_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
            "blob_verified": True,
            "upstream_commit": "a" * 40,
            "url": "https://example.org/" + path.name,
            "immutable_url": "https://example.org/" + "a" * 40 + "/" + path.name,
            "accessed": "2026-09-30",
        })
    (source / "source_manifest.json").write_text(json.dumps(rows), encoding="utf-8")


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    files = {
        "mfcad_sample.step": b"#1 = ADVANCED_FACE('1',(),#3,.T.);\n#2 = ADVANCED_FACE('0',(),#4,.T.);",
        "mfcad_sample.face_truth": pickle.dumps([15, 0]),
        "mfcad_LICENSE.txt": b"MIT License\nCopyright (c) fixture MFCAD\n",
        "mfcad_train_list": pickle.dumps(["train-item"]),
        "mfcad_valid_list": pickle.dumps(["val-item"]),
        "mfcad_test_list": pickle.dumps(["test-item"]),
        "mfinstseg_sample.step": b"#1 = ADVANCED_FACE('',(),#3,.T.);\n#2 = ADVANCED_FACE('',(),#4,.T.);",
        "mfinstseg_sample.json": json.dumps([["test", {
            "seg": {"0": 24, "1": 1}, "inst": [[0, 0], [0, 1]],
            "bottom": {"0": 0, "1": 1},
        }]]).encode(),
        "aagnet_LICENSE.txt": b"MIT License\nCopyright (c) fixture AAGNet\n",
        "mfinstseg_train.txt": b"shared\nshared\ntrain-only\n",
        "mfinstseg_val.txt": b"shared\nval-only\n",
        "mfinstseg_test.txt": b"test-only\n",
    }
    for name, raw in files.items():
        (root / name).write_bytes(raw)
    write_manifest(root)
    return root


def test_import_stores_two_samples_without_claiming_training(source, tmp_path):
    target = tmp_path / "cad.sqlite"
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    result = import_corpus(source, target)
    assert result["loaded_models"] == 2
    assert result["mfcadpp_models"] == 0
    assert result["raw_files"] == 12
    assert result["face_labels"] == 4
    assert result["training_ready"] is False
    assert result["training_performed"] is False
    assert result["weights_changed"] is False
    assert result["geometry_checked"] is False
    with sqlite3.connect(target) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT count(*) FROM samples").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM raw_files").fetchone()[0] == 12
        assert db.execute("SELECT count(*) FROM face_labels").fetchone()[0] == 4
    assert {p.name: p.read_bytes() for p in source.iterdir()} == before


def test_public_split_findings_are_preserved(source, tmp_path):
    result = import_corpus(source, tmp_path / "cad.sqlite")
    findings = json.dumps(result["findings"])
    assert "duplicate" in findings
    assert "shared" in findings


def test_labels_use_mfcad_names_not_step_text_order(source, tmp_path):
    target = tmp_path / "cad.sqlite"
    import_corpus(source, target)
    with sqlite3.connect(target) as db:
        rows = db.execute(
            "SELECT label_index, semantic_label, step_name, step_file_order "
            "FROM face_labels WHERE sample_id='mfcad_sample' ORDER BY label_index"
        ).fetchall()
        assert rows == [(0, 15, "0", 1), (1, 0, "1", 0)]
        raw = db.execute(
            "SELECT content FROM raw_files WHERE filename='mfcad_sample.face_truth'"
        ).fetchone()[0]
        assert raw == (source / "mfcad_sample.face_truth").read_bytes()


def test_mfinstseg_does_not_invent_face_mapping_without_cad_check(source, tmp_path):
    target = tmp_path / "cad.sqlite"
    import_corpus(source, target)
    with sqlite3.connect(target) as db:
        rows = db.execute(
            "SELECT step_entity_id, step_name, step_file_order, ocp_face_index "
            "FROM face_labels WHERE sample_id='mfinstseg_sample'"
        ).fetchall()
        assert rows == [(None, None, None, None)] * 2


def test_malformed_label_structure_refuses_partial_database(source, tmp_path):
    path = source / "mfinstseg_sample.json"
    pairs = json.loads(path.read_text())
    pairs[0][1]["inst"] = [[0]]
    path.write_text(json.dumps(pairs), encoding="utf-8")
    write_manifest(source)
    target = tmp_path / "cad.sqlite"
    with pytest.raises(ValueError):
        import_corpus(source, target)
    assert not target.exists()


@pytest.mark.parametrize("field,wrong", [
    ("sha256", "0" * 64), ("bytes", 1), ("upstream_blob", "0" * 40),
])
def test_corrupt_provenance_refuses_import(source, tmp_path, field, wrong):
    manifest_path = source / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    row = next(x for x in manifest if x["file"] == "mfcad_sample.step")
    row[field] = wrong
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    target = tmp_path / "cad.sqlite"
    with pytest.raises(ValueError):
        import_corpus(source, target)
    assert not target.exists()


def test_changed_original_rejected(source, tmp_path):
    (source / "mfcad_sample.step").write_bytes(b"replaced original")
    target = tmp_path / "cad.sqlite"
    with pytest.raises(ValueError):
        import_corpus(source, target)
    assert not target.exists()


def test_missing_original_refuses_partial_database(source, tmp_path):
    (source / "mfcad_sample.step").unlink()
    target = tmp_path / "cad.sqlite"
    with pytest.raises((ValueError, FileNotFoundError)):
        import_corpus(source, target)
    assert not target.exists()


def test_existing_database_never_overwritten(source, tmp_path):
    target = tmp_path / "cad.sqlite"
    previous = b"existing content must remain"
    target.write_bytes(previous)
    with pytest.raises((ValueError, FileExistsError)):
        import_corpus(source, target)
    assert target.read_bytes() == previous


def test_pickle_globals_are_never_executed(source, tmp_path):
    # Merely resolving the harmless global is forbidden; no code payload needed.
    (source / "mfcad_sample.face_truth").write_bytes(pickle.dumps(eval))
    write_manifest(source)
    target = tmp_path / "cad.sqlite"
    with pytest.raises(ValueError):
        import_corpus(source, target)
    assert not target.exists()
