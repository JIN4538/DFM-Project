"""Record the interpreter, dependencies and repo source used in this test run."""
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path.cwd().resolve()
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from amdfm.analysis import code_digest
import amdfm

files = sorted((ROOT / "amdfm").glob("*.py")) + sorted((ROOT / "src/core").glob("*.py"))
files += [ROOT / "app.py"] + sorted((ROOT / "tests").glob("test*.py")) + sorted((ROOT / "tests_v3").glob("test*.py"))
hashes = {str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
          for path in files}
packages = {dist.metadata["Name"]: dist.version for dist in importlib.metadata.distributions() if dist.metadata["Name"]}
manifest = {
    "recorded_utc": datetime.now(timezone.utc).isoformat(), "python_version": sys.version,
    "python_executable": sys.executable, "python_prefix": sys.prefix, "python_base_prefix": sys.base_prefix,
    "platform": platform.platform(), "cwd": str(ROOT), "amdfm_import_path": str(Path(amdfm.__file__).resolve()),
    "engine_code_sha256": code_digest(), "source_sha256": hashes,
    "packages": dict(sorted(packages.items(), key=lambda item: item[0].lower())),
    "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
    "command": [sys.executable, "-X", "utf8", "-m", "pytest", "tests", "tests_v3", "-q",
                "--junitxml=validation/v3/random-corpus/checks-313-01/pytest.xml"],
    "scope": "Current repository code/tests executed by the existing Desktop deployment Python 3.13 virtual environment; Desktop source is unchanged.",
}
(OUT / "environment.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({key: manifest[key] for key in ("python_version", "python_executable", "amdfm_import_path", "engine_code_sha256")}, ensure_ascii=False))
