"""Summarize the completed run without changing application sources."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path.cwd().resolve()
OUT = Path(__file__).resolve().parent
before = json.loads((OUT / "environment.json").read_text(encoding="utf-8"))
after = {relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
         for relative in before["source_sha256"]}
changes = [relative for relative, digest in before["source_sha256"].items() if digest != after[relative]]
suite = ET.parse(OUT / "pytest.xml").getroot().find("testsuite")
log = (OUT / "pytest.txt").read_text(encoding="utf-8-sig")
warnings = re.search(r"=+ warnings summary =+\n(.*?)\n-- Docs:", log, flags=re.S)
result = {
    "completed_record_utc": datetime.now(timezone.utc).isoformat(),
    "python_version": before["python_version"], "engine_code_sha256_at_start": before["engine_code_sha256"],
    "source_files_unchanged_at_end": not changes, "changed_files": changes,
    "test_counts": {key: int(suite.attrib[key]) for key in ("tests", "failures", "errors", "skipped")},
    "junit_elapsed_seconds": float(suite.attrib["time"]),
    "console_result": next((line for line in reversed(log.splitlines()) if "passed" in line or "failed" in line), None),
    "warnings_summary": warnings.group(1).strip() if warnings else None,
    "pip_check": (OUT / "pip-check.txt").read_text(encoding="utf-8-sig").strip(),
    "artifacts_sha256": {name: hashlib.sha256((OUT / name).read_bytes()).hexdigest()
                         for name in ("environment.json", "pytest.txt", "pytest.xml", "pip-check.txt")},
    "comparison": {"reported_python312": "458 passed, 1 known warning in 210.33s",
                   "scope": "Current repository tests on existing Desktop Python 3.13 dependencies; actual Desktop application sources were not the test target."},
}
(OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({key: result[key] for key in ("source_files_unchanged_at_end", "test_counts", "console_result", "warnings_summary", "pip_check")}, ensure_ascii=False))
