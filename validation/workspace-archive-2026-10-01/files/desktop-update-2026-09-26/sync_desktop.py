"""Copy the current tracked app into the existing desktop installation.

Existing user files and environments are retained. Every replacement is copied
and hash-verified into a dated backup before any destination is overwritten.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(r"C:\Users\JIN\Documents\ChatGPT\DFM\DFM-Project").resolve()
DEST = Path(r"C:\Users\JIN\Desktop\AM-DFM_v3_0").resolve()
WORK = Path(__file__).resolve().parent
STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")
BACKUP = WORK / ("backup-" + STAMP)


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0")
dirs = {"amdfm", "dfm", "src", "scripts", "tests", "tests_v3", "examples", ".streamlit"}
root_files = {"app.py", "audit_models.py", "cura_check.py", "INSTALL.cmd", "START_REVIEW.cmd", "VERIFY.cmd", "requirements.txt", "run_app.py", "run_legacy.py", "verify_legacy.py", "README.md", "AGENTS.md", ".gitattributes", ".gitignore"}
selected = []
for rel in tracked:
    if not rel:
        continue
    path = Path(rel)
    if (path.parts[0] in dirs or rel in root_files
        or (path.parts[0] == "docs" and path.suffix.lower() in {".md", ".csv", ".json"} and "artifacts" not in path.parts)):
        selected.append(rel)

assert DEST.is_dir() and ROOT.is_dir()
BACKUP.mkdir(parents=True, exist_ok=False)
entries = []
for rel in selected:
    source, target = ROOT / rel, DEST / rel
    assert source.resolve().is_relative_to(ROOT) and target.resolve().is_relative_to(DEST)
    assert source.is_file()
    before = sha(target) if target.is_file() else None
    after = sha(source)
    operation = "unchanged" if before == after else ("replace" if before else "add")
    entries.append({"path": rel, "operation": operation, "before_sha256": before, "sha256": after, "bytes": source.stat().st_size})
    if operation == "replace":
        backup = BACKUP / rel
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
        assert sha(backup) == before

# Preserve the previous source-release provenance before writing current state.
old_release = DEST / "release_manifest.json"
if old_release.is_file():
    shutil.copy2(old_release, BACKUP / "release_manifest.json")
    assert sha(old_release) == sha(BACKUP / "release_manifest.json")

record = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "source": str(ROOT), "destination": str(DEST), "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(), "backup": str(BACKUP), "scope": "Tracked runtime, launchers, tests, examples and text documentation. Existing .venv, user files, historical validation and logs are preserved; reference PDFs and historical source ZIPs are not copied.", "counts": {op: sum(e["operation"] == op for e in entries) for op in ("add", "replace", "unchanged")}, "files": entries}
write(BACKUP / "before-and-plan.json", record)
for entry in entries:
    if entry["operation"] != "unchanged":
        target = DEST / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / entry["path"], target)
for entry in entries:
    assert sha(DEST / entry["path"]) == entry["sha256"], entry["path"]
record["verification"] = "All selected destination files match source SHA-256 after copy."
write(WORK / "sync-result.json", record)
write(DEST / "release_manifest.json", {**record, "version": "3.0.0", "release_kind": "in-place desktop update preserving existing local files"})
print(json.dumps({k: v for k, v in record.items() if k != "files"}, ensure_ascii=False, indent=2))
