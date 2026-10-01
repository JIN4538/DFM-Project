"""Offline integrity audit of condition records and optional original literature."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from amdfm.analysis import code_digest
from dfm.conditions import DATA_DIR, load_library, load_literature


def audit(verify_literature=False):
    library = load_library()
    literature = load_literature()
    profiles = list(library.profiles.values())
    checks = []
    for record in profiles:
        identifier, process = record["id"], record["process"]
        resolved = library.resolve(identifier, process)
        model = library.machining_profile(identifier) if process == "CNC" else library.am_profile(identifier)
        model.validate()
        context = model.condition_evidence
        checks.append({"id": identifier, "process": process,
                       "automatic_fields": [k for k, p in record["parameters"].items() if p["application"] == "automatic"],
                       "reference_fields": [k for k, p in record["parameters"].items() if p["application"] == "reference_only"],
                       "resolved_values": resolved["values"],
                       "profile_valid": True, "sources_preserved": bool(context["sources"]),
                       "physical_validation": context["physical_validation"]})
    hashes = []
    if verify_literature:
        for record in literature:
            path = ROOT / record["repository_path"]
            with path.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != record["sha256"]:
                raise ValueError(f"문헌 파일과 검토 기록의 해시가 다릅니다: {path}")
            hashes.append({"id": record["id"], "path": record["repository_path"], "sha256": actual, "matched": True})
    parameter_counts = Counter(p["application"] for r in profiles for p in r["parameters"].values())
    return {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
            "platform": platform.platform(), "database_sha256": library.digest, "code_sha256": code_digest(),
            "status": "passed", "source_records": len(library.sources),
            "distinct_source_urls": len({s["url"] for s in library.sources.values()}),
            "profiles": len(profiles), "by_process": dict(Counter(p["process"] for p in profiles)),
            "by_category": dict(Counter(p["category"] for p in profiles)),
            "parameters": dict(parameter_counts),
            "applicable_profiles": sum(bool(r["automatic_fields"]) for r in checks),
            "literature_records": len(literature), "literature_pages": sum(r["pages"] for r in literature),
            "checks": checks, "verified_literature": hashes,
            "files": [{"path": p.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                      for p in sorted(DATA_DIR.glob("*.json"))],
            "scope": "오프라인 구조·출처 연결·단위·프로필 검증. 원문 수치의 독립 대조와 실물 제조 검증은 별도이며 본 검사로 대체하지 않음."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True, help="새 JSON 파일; 기존 결과는 덮어쓰지 않음")
    parser.add_argument("--verify-literature", action="store_true")
    args = parser.parse_args()
    result = audit(args.verify_literature)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k not in {"checks", "verified_literature", "files"}}, ensure_ascii=False, indent=2))
