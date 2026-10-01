"""Index the existing reviewed literature without turning it into numeric limits.

Run from the repository; the 2026-09-21 reading record is historical evidence,
not a claim that this indexing operation reread all 928 pages.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def build():
    from amdfm.evidence import SOURCES as AM_SOURCES
    from dfm.machining import SOURCES as CNC_SOURCES
    manifest = json.loads((ROOT / "references/manifest-2026-09-21.json").read_text(encoding="utf-8"))
    coverage = json.loads((ROOT / "docs/research/literature-update-2026-09-21/reading-coverage.json").read_text(encoding="utf-8"))
    reads = {d["id"]: d for d in coverage["documents"]}
    records = []
    for doc in manifest["documents"]:
        read = reads[doc["id"]]
        path = ROOT / doc["repository_path"]
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != doc["sha256"] or digest != read["sha256"]:
            raise ValueError(f"Historical reading record is stale: {path}")
        title = path.stem
        is_am = "AM_PAPERS" in read["audit"] or "529" in title
        is_cnc = "CNC_PAPERS" in read["audit"] or ("STANDARDS" in read["audit"] and not is_am)
        if "52903" in title:
            processes = ["MEX"]
        elif is_am:
            processes = ["MEX", "VPP", "PBF_POLYMER", "PBF_METAL"]
        elif is_cnc:
            processes = ["CNC"]
        else:
            processes = ["MEX", "VPP", "PBF_POLYMER", "PBF_METAL", "CNC"]
        refs = []
        for family, sources in (("AM", AM_SOURCES), ("CNC", CNC_SOURCES)):
            for key, src in sources.items():
                if src.get("local_path") == doc["repository_path"]:
                    refs.append({"family": family, "id": key, **src})
        records.append({
            "id": "literature-" + doc["id"], "title": title,
            "repository_path": doc["repository_path"], "sha256": digest, "pages": doc["pages"],
            "discovery_processes": processes,
            "process_tag_scope": "검색용 주제 분류이며 수치 규칙의 적용 공정을 인증하지 않습니다.",
            "reading_record_date": coverage["date"], "indexed_date": "2026-09-28",
            "audit_path": read["audit"], "reading_method": read["method"],
            "source_limit": read.get("source_limit"), "current_code_references": refs,
            "application": "background_only", "automatic_parameters": {},
        })
    return {"schema_version": 1,
            "scope": "기존 전문 검토 기록과 현재 파일 해시를 연결한 문헌 색인; 신규 전문 재독해 또는 보편 수치 규칙이 아님",
            "records": records}


if __name__ == "__main__":
    target = ROOT / "data/conditions/literature.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    catalog = build()
    target.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(catalog['records'])} source files indexed; all SHA-256 matched historical reading record")
