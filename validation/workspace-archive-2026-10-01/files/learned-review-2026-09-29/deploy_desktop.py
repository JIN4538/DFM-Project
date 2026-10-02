"""Checked source-to-Desktop sync; existing user edits abort before copying.

No model training, dependency install, credential copy, or deletion. Run only
after source/model freeze and tests. Every replaced byte is backed up first.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil


ROOT = Path("C:/Users/JIN/Documents/ChatGPT/DFM/DFM-Project").resolve()
TARGET = Path("C:/Users/JIN/Desktop/AM-DFM_v3_0").resolve()
WORK = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def runtime_files(base):
    # Mirrors amdfm.analysis.code_digest; models are part of the result identity.
    return (sorted((base / "amdfm").glob("*.py")) + sorted((base / "dfm").glob("*.py"))
            + sorted((base / "src/core").glob("*.py"))
            + sorted((base / "data/conditions").glob("*.json"))
            + sorted((base / "data/models").rglob("*.json")))


def code_sha(base):
    digest = hashlib.sha256()
    for path in runtime_files(base):
        digest.update(path.relative_to(base).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def allowed_files():
    names = {"app.py", "AGENTS.md", "requirements-training.txt",
             "scripts/train_rule_model.py", "scripts/audit_learned_cad.py",
             "scripts/replay_learned_cad.py",
             "docs/LOCAL_AI_GUIDE.md", "docs/AI_ADVISOR_GUIDE.md",
             "docs/project-knowledge/README.md", "docs/project-knowledge/LEARNED_REVIEW_2026-09-29.md"}
    names.update(path.relative_to(ROOT).as_posix() for path in runtime_files(ROOT))
    names.update(path.relative_to(ROOT).as_posix() for path in (ROOT / "tests_v3").glob("test_*.py"))
    # Validation artifacts are optional and copied as records, never as model
    # dependencies. Do not copy full synthetic training datasets or log folders.
    validation = ROOT / "validation/learned-review-2026-09-29"
    if validation.is_dir():
        for path in validation.rglob("*"):
            if path.is_file() and (path.name in ("README.md", "MODEL_REPORT.md", "summary.json", "evaluation.json",
                                                 "training-evaluation.json", "numeric-nextafter-stress.json",
                                                 "adapter-recheck-provenance.json", "warm-inference.json")
                                   or path.suffix in (".txt", ".xml", ".png", ".log")):
                names.add(path.relative_to(ROOT).as_posix())
    return sorted(names)


def deploy():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = WORK / ("desktop-backup-" + stamp)
    record_path = WORK / ("desktop-sync-" + stamp + ".json")
    manifest = TARGET / "release_manifest.json"
    old_manifest_sha = sha(manifest)
    old_manifest = json.loads(manifest.read_text(encoding="utf-8"))
    old_files = {item["path"]: item for item in old_manifest["files"]}
    source_revision = code_sha(ROOT)
    plan = []
    for name in allowed_files():
        source, destination = (ROOT / name).resolve(), (TARGET / name).resolve()
        if not source.is_relative_to(ROOT) or not destination.is_relative_to(TARGET) or not source.is_file():
            raise RuntimeError("Invalid allowlist file: " + name)
        if destination.exists() and not destination.is_file():
            raise RuntimeError("Destination is not a file: " + str(destination))
        before = sha(destination) if destination.is_file() else None
        after = sha(source)
        if before is not None and before != after and old_files.get(name, {}).get("sha256") != before:
            raise RuntimeError("Unexpected Desktop edit; preserved for inspection: " + str(destination))
        plan.append(dict(path=name, before_sha256=before, sha256=after, bytes=source.stat().st_size,
                         operation="unchanged" if before == after else "replace" if before is not None else "add"))
    # Preflight the union. An obsolete extra runtime module would make Desktop
    # result identities differ; report it rather than deleting files silently.
    source_names = {path.relative_to(ROOT).as_posix() for path in runtime_files(ROOT)}
    extra_runtime = [path.relative_to(TARGET).as_posix() for path in runtime_files(TARGET)
                     if path.relative_to(TARGET).as_posix() not in source_names]
    if extra_runtime:
        raise RuntimeError("Unmatched Desktop runtime files were preserved: " + ", ".join(extra_runtime))
    if sha(manifest) != old_manifest_sha or code_sha(ROOT) != source_revision:
        raise RuntimeError("Source or release manifest changed during preflight")
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(manifest, backup / "release_manifest.json")
    for item in plan:
        source, destination = ROOT / item["path"], TARGET / item["path"]
        if sha(source) != item["sha256"]:
            raise RuntimeError("Source changed after preflight: " + str(source))
        actual_before = sha(destination) if destination.is_file() else None
        if actual_before != item["before_sha256"]:
            raise RuntimeError("Desktop changed after preflight: " + str(destination))
        if item["operation"] == "replace":
            saved = backup / item["path"]
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, saved)
            if sha(saved) != item["before_sha256"]:
                raise RuntimeError("Backup checksum mismatch: " + str(saved))
        if item["operation"] != "unchanged":
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        if sha(destination) != item["sha256"]:
            raise RuntimeError("Copied file checksum mismatch: " + str(destination))
        old_files[item["path"]] = item
    if code_sha(ROOT) != source_revision or code_sha(TARGET) != source_revision:
        raise RuntimeError("Source/Desktop runtime identity mismatch after copy; backup retained")
    if sha(manifest) != old_manifest_sha:
        raise RuntimeError("Release manifest changed during copy; backup retained")
    record = dict(timestamp_utc=datetime.now(timezone.utc).isoformat(), source=str(ROOT), destination=str(TARGET),
                  backup=str(backup), source_code_sha256=source_revision, desktop_code_sha256=code_sha(TARGET),
                  scope="Local rule-trained AI and compact novice UI; source/model/docs/tests only", files=plan, verified=True)
    with record_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    updated = {**old_manifest, "files": [old_files[key] for key in sorted(old_files)],
               "learned_review_update": dict(timestamp_utc=record["timestamp_utc"], working_tree_changes=True,
                                             code_sha256=source_revision, backup=str(backup), manifest=str(record_path))}
    temporary_manifest = TARGET / ("release_manifest." + stamp + ".tmp")
    with temporary_manifest.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(updated, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    temporary_manifest.replace(manifest)
    print(json.dumps(dict(added=sum(item["operation"] == "add" for item in plan),
                          replaced=sum(item["operation"] == "replace" for item in plan),
                          verified=True, code_sha256=source_revision, backup=str(backup),
                          manifest=str(record_path)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    deploy()
