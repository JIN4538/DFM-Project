"""Import the two previously acquired CAD samples into a NEW local SQLite DB.

This deliberately small adapter supports one MFCAD-original and one MFInstSeg
repository sample, their labels, licenses and published partition lists. It
does not download anything, import MFCAD++, train a model or change app weights.
The database is an evidence-preserving staging store, not a training-ready corpus.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from urllib.parse import urlparse

try:
    from scripts import audit_public_cad_data as audit
except ModuleNotFoundError:
    import audit_public_cad_data as audit


SCHEMA_VERSION = 1
DATASETS = {
    "mfcad": {
        "name": "MFCAD original: one repository sample",
        "step": "mfcad_sample.step", "labels": "mfcad_sample.face_truth",
        "license": "mfcad_LICENSE.txt", "split_format": "pickle",
        "splits": {"train": "mfcad_train_list", "val": "mfcad_valid_list",
                   "test": "mfcad_test_list"},
        "reasons": [
            "Only one source sample is imported; this is not the full corpus.",
            "Numeric labels are retained: upstream class-name vocabulary has an unresolved contradiction.",
            "No training feature tensors or independent evaluation split have been prepared.",
        ],
    },
    "mfinstseg": {
        "name": "MFInstSeg: one AAGNet repository sample",
        "step": "mfinstseg_sample.step", "labels": "mfinstseg_sample.json",
        "license": "aagnet_LICENSE.txt", "split_format": "text",
        "splits": {"train": "mfinstseg_train.txt", "val": "mfinstseg_val.txt",
                   "test": "mfinstseg_test.txt"},
        "reasons": [
            "Only one repository sample is imported; the external MFInstSeg distribution is not imported.",
            "Upstream pythonocc face traversal has not been reproduced; OCP ordinal correspondence is provisional.",
            "Generator and dataloader comments disagree on the chamfer/round class names; numeric labels are retained.",
            "Published split duplicates/overlaps must be resolved before a separate training corpus is prepared.",
        ],
    },
}
REQUIRED_FILES = tuple(
    filename
    for spec in DATASETS.values()
    for filename in (spec["step"], spec["labels"], spec["license"], *spec["splits"].values())
)


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _verified_inputs(source_dir: Path) -> tuple[bytes, dict, dict]:
    """Take a verified immutable-in-memory snapshot of the 12 required inputs."""
    manifest_raw = (source_dir / "source_manifest.json").read_bytes()
    manifest = json.loads(manifest_raw.decode("utf-8-sig"))
    if not isinstance(manifest, list):
        raise ValueError("Source manifest must be a list of provenance records")
    records = {}
    for row in manifest:
        if not isinstance(row, dict) or not isinstance(row.get("file"), str):
            raise ValueError("Invalid source manifest record")
        name = row["file"]
        if name in records:
            raise ValueError(f"Duplicate manifest filename: {name}")
        # The adapter intentionally never interprets arbitrary manifest paths.
        records[name] = row
    snapshots = {}
    for name in REQUIRED_FILES:
        if name not in records:
            raise ValueError(f"Missing required manifest record: {name}")
        row = records[name]
        path = source_dir / name
        if not path.is_file():
            raise ValueError(f"Missing required source file: {name}")
        if path.resolve().parent != source_dir:
            raise ValueError(f"Source file resolves outside source directory: {name}")
        raw = path.read_bytes()
        if type(row.get("bytes")) is not int or row["bytes"] != len(raw):
            raise ValueError(f"Integrity failure: bytes mismatch for {name}")
        if row.get("sha256") != _sha(raw):
            raise ValueError(f"Integrity failure: SHA-256 mismatch for {name}")
        blob = hashlib.sha1(f"blob {len(raw)}\0".encode("ascii") + raw).hexdigest()
        if row.get("blob_verified") is not True or row.get("upstream_blob") != blob:
            raise ValueError(f"Integrity failure: Git blob mismatch or unverified blob for {name}")
        for key in ("url", "immutable_url"):
            parsed = urlparse(row.get(key, ""))
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError(f"Missing HTTPS {key} provenance for {name}")
        if not re.fullmatch(r"[0-9a-f]{40}", row.get("upstream_commit", "")):
            raise ValueError(f"Missing upstream commit provenance for {name}")
        snapshots[name] = raw
    return manifest_raw, records, snapshots


def _sample_rows(step: Path, labels, kind: str, geometry: dict | None) -> list[dict]:
    """Preserve source indices; never equate MFInstSeg text order with labels."""
    if kind == "mfcad":
        text_faces = re.findall(r"#(\d+)\s*=\s*ADVANCED_FACE\s*\(\s*'([^']*)'",
                                step.read_text(encoding="utf-8-sig"))
        by_label = {int(name): (order, int(entity), name)
                    for order, (entity, name) in enumerate(text_faces)}
        ocp_by_label = {int(row["step_name"]): row
                        for row in (geometry or {}).get("face_rows", [])}
        result = []
        for index, label in enumerate(labels):
            order, entity, name = by_label[index]
            ocp_row = ocp_by_label.get(index, {})
            result.append({"label_index": index, "semantic_label": label,
                           "bottom_label": None, "step_entity_id": entity,
                           "step_name": name, "step_file_order": order,
                           "ocp_face_index": ocp_row.get("index"),
                           "mapping_status": "verified_step_name_label_index",
                           "surface": ocp_row.get("surface")})
        return result
    ocp_by_index = {row["index"]: row for row in (geometry or {}).get("face_rows", [])}
    return [{"label_index": index, "semantic_label": labels["seg"][str(index)],
             "bottom_label": labels["bottom"][str(index)],
             "step_entity_id": None, "step_file_order": None,
             "step_name": ocp_by_index.get(index, {}).get("step_name"),
             "ocp_face_index": ocp_by_index.get(index, {}).get("index"),
             "mapping_status": ("provisional_ocp_ordinal_not_upstream_verified"
                                if index in ocp_by_index else "source_label_ordinal_only"),
             "surface": ocp_by_index.get(index, {}).get("surface")}
            for index in range(len(labels["seg"]))]


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE datasets (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, scope TEXT NOT NULL,
 license_identifier TEXT NOT NULL, license_text TEXT NOT NULL,
 license_source_url TEXT NOT NULL, license_sha256 TEXT NOT NULL,
 provenance_json TEXT NOT NULL, training_ready INTEGER NOT NULL CHECK(training_ready = 0),
 readiness_reasons_json TEXT NOT NULL
);
CREATE TABLE raw_files (
 id INTEGER PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES datasets(id),
 filename TEXT NOT NULL UNIQUE, role TEXT NOT NULL, url TEXT NOT NULL,
 immutable_url TEXT NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL,
 upstream_commit TEXT NOT NULL, upstream_blob TEXT NOT NULL,
 blob_verified INTEGER NOT NULL, source_record_json TEXT NOT NULL, content BLOB NOT NULL
);
CREATE TABLE samples (
 id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES datasets(id),
 source_sample_id TEXT NOT NULL, step_file_id INTEGER NOT NULL REFERENCES raw_files(id),
 labels_file_id INTEGER NOT NULL REFERENCES raw_files(id),
 training_ready INTEGER NOT NULL CHECK(training_ready = 0), geometry_json TEXT,
 sample_audit_json TEXT NOT NULL, findings_json TEXT NOT NULL,
 readiness_reasons_json TEXT NOT NULL
);
CREATE TABLE face_labels (
 sample_id TEXT NOT NULL REFERENCES samples(id), label_index INTEGER NOT NULL,
 semantic_label INTEGER NOT NULL, bottom_label INTEGER, step_entity_id INTEGER,
 step_name TEXT, step_file_order INTEGER, ocp_face_index INTEGER,
 mapping_status TEXT NOT NULL, surface TEXT, PRIMARY KEY(sample_id, label_index)
);
CREATE TABLE split_audits (
 dataset_id TEXT PRIMARY KEY REFERENCES datasets(id), file_format TEXT NOT NULL,
 audit_json TEXT NOT NULL, findings_json TEXT NOT NULL
);
CREATE TABLE import_runs (
 id INTEGER PRIMARY KEY, schema_version INTEGER NOT NULL, imported_at TEXT NOT NULL,
 source_directory TEXT NOT NULL, source_manifest_sha256 TEXT NOT NULL,
 source_manifest_blob BLOB NOT NULL, summary_json TEXT NOT NULL
);
"""


def import_corpus(source_dir: Path, database: Path, *, ocp: bool = False) -> dict:
    """Import exactly two archived samples, refusing overwrite or bad inputs.

    Raises ValueError on integrity/structural failures and FileExistsError for an
    existing destination. Split findings remain in the DB; they are not a failed
    transfer. OCP is optional and records geometry, not verified upstream order.
    All parsing/auditing happens on byte-for-byte snapshots before DB creation.
    """
    source_dir, database = Path(source_dir).resolve(), Path(database).absolute()
    if database.exists() or database.is_symlink():
        raise FileExistsError(f"Database exists; choose a new path: {database}")
    manifest_raw, records, snapshots = _verified_inputs(source_dir)
    results = {}
    with tempfile.TemporaryDirectory(prefix="dfm-cad-import-") as temp:
        snapshot_dir = Path(temp)
        for name, raw in snapshots.items():
            (snapshot_dir / name).write_bytes(raw)
        for kind, spec in DATASETS.items():
            license_text = snapshots[spec["license"]].decode("utf-8-sig")
            if "MIT License" not in license_text or "Copyright" not in license_text:
                raise ValueError(f"Expected preserved MIT license and copyright for {kind}")
            step = snapshot_dir / spec["step"]
            labels = audit.load_labels(snapshot_dir / spec["labels"], kind)
            sample_audit, findings = audit.audit_sample(step, labels, kind)
            if findings:
                raise ValueError(f"Structural sample audit failed for {kind}: {'; '.join(findings)}")
            geometry = None
            if ocp:
                geometry, geometry_findings = audit.audit_ocp(step, labels, kind)
                findings.extend(geometry_findings)
            split_paths = {key: snapshot_dir / name for key, name in spec["splits"].items()}
            split_audit, split_findings = audit.audit_splits(split_paths, spec["split_format"])
            source_sample_id = (Path(urlparse(records[spec["step"]]["url"]).path).stem
                                if kind == "mfcad" else
                                json.loads(snapshots[spec["labels"]].decode("utf-8-sig"))[0][0])
            results[kind] = {"license": license_text, "sample": sample_audit,
                             "geometry": geometry, "findings": findings,
                             "splits": split_audit, "split_findings": split_findings,
                             "source_sample_id": str(source_sample_id),
                             "faces": _sample_rows(step, labels, kind, geometry)}
    summary = {
        "schema_version": SCHEMA_VERSION, "database": str(database),
        "loaded_models": 2, "loaded_datasets": list(DATASETS),
        "raw_files": len(snapshots),
        "face_labels": sum(len(result["faces"]) for result in results.values()),
        "mfcadpp_models": 0, "training_ready": False, "training_performed": False,
        "weights_changed": False, "geometry_checked": bool(ocp),
        "scope": "Two repository samples only; not MFCAD++, a bulk importer, or a full training corpus.",
        "split_scope": "Published ID lists are metadata: their rows are not imported CAD models.",
        "findings": {kind: result["findings"] + result["split_findings"]
                     for kind, result in results.items()},
    }
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(SCHEMA)
        for kind, spec in DATASETS.items():
            result = results[kind]
            license_record = records[spec["license"]]
            provenance = {
                "source_files": [spec["step"], spec["labels"]],
                "license_scope": "Captured repository license; retained with repository sample. Not a license assertion for an external full distribution.",
                "split_license_scope": ("MFCAD_GNN split source provenance retained; the MFCAD repository license does not automatically license that separate repository."
                                        if kind == "mfcad" else "AAGNet repository partition metadata."),
                "source_manifest_sha256": _sha(manifest_raw),
            }
            connection.execute("INSERT INTO datasets VALUES (?,?,?,?,?,?,?,?,?,?)", (
                kind, spec["name"], "One selected sample and published partition metadata",
                "MIT", result["license"], license_record["immutable_url"],
                license_record["sha256"], _json(provenance), 0, _json(spec["reasons"])))
            file_ids = {}
            roles = [(spec["step"], "step"), (spec["labels"], "labels"),
                     (spec["license"], "license")]
            roles.extend((name, f"split_{split}") for split, name in spec["splits"].items())
            for filename, role in roles:
                record = records[filename]
                cursor = connection.execute(
                    "INSERT INTO raw_files(dataset_id,filename,role,url,immutable_url,sha256,bytes,"
                    "upstream_commit,upstream_blob,blob_verified,source_record_json,content) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (kind, filename, role, record["url"], record["immutable_url"],
                     record["sha256"], record["bytes"], record["upstream_commit"],
                     record["upstream_blob"], 1, _json(record), snapshots[filename]))
                file_ids[filename] = cursor.lastrowid
            sample_id = f"{kind}_sample"
            connection.execute("INSERT INTO samples VALUES (?,?,?,?,?,?,?,?,?,?)", (
                sample_id, kind, result["source_sample_id"], file_ids[spec["step"]],
                file_ids[spec["labels"]], 0,
                _json(result["geometry"]) if result["geometry"] is not None else None,
                _json(result["sample"]), _json(result["findings"]), _json(spec["reasons"])))
            connection.executemany("INSERT INTO face_labels VALUES (?,?,?,?,?,?,?,?,?,?)", [
                (sample_id, row["label_index"], row["semantic_label"], row["bottom_label"],
                 row["step_entity_id"], row["step_name"], row["step_file_order"],
                 row["ocp_face_index"], row["mapping_status"], row["surface"])
                for row in result["faces"]])
            connection.execute("INSERT INTO split_audits VALUES (?,?,?,?)", (
                kind, spec["split_format"], _json(result["splits"]), _json(result["split_findings"])))
        connection.execute("INSERT INTO import_runs VALUES (?,?,?,?,?,?,?)", (
            1, SCHEMA_VERSION, datetime.now(timezone.utc).isoformat(), str(source_dir),
            _sha(manifest_raw), manifest_raw, _json(summary)))
        connection.commit()
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed before writing destination")
        database.parent.mkdir(parents=True, exist_ok=True)
        # O_EXCL closes the race between the initial existence check and write.
        descriptor = os.open(database, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        try:
            destination = sqlite3.connect(database)
            try:
                connection.backup(destination)
            finally:
                destination.close()
        except BaseException:
            database.unlink(missing_ok=True)  # Only this invocation's new file.
            raise
    finally:
        connection.close()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True,
                        help="New SQLite database path; existing files are never overwritten")
    parser.add_argument("--ocp", action="store_true", help="Also audit geometry with installed OCP")
    args = parser.parse_args()
    try:
        summary = import_corpus(args.source_dir, args.database, ocp=args.ocp)
    except Exception as exc:
        parser.exit(1, f"Import failed: {type(exc).__name__}: {exc}\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
