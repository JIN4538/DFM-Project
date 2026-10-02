"""Small, authored Korean intent release evaluation, not proven model accuracy.

Default mode validates fixtures locally and NEVER invokes the AI client. Only
``--live`` enables provider calls, with OPENAI_API_KEY read from the environment
(no command-line key and no application secrets file). Each request uses the
production extractor and its strict schema/substring checks. Auth/rate-limit
failure stops further requests; the remaining cases are recorded as errors.

Exact enumerated process/priority values and explicitly listed name alternatives
are the semantic oracle. These 12 deliberately chosen prompts are not a random
sample, physical manufacturing evidence, or a general accuracy benchmark. A
successful offline run validates the corpus only; it does not evaluate a model.
Outputs contain the authored prompts, expected values, and safe extraction
results. Raw API responses, credentials, or exception payloads are not written.
Every output path must be new; existing evidence is never overwritten.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dfm.ai_client import AIClientError, DEFAULT_MODEL, MAX_TEXT_CHARS, PRIORITIES, PROCESSES, parse_intent

DEFAULT_CASES = ROOT / "validation/ai-advisor-2026-09-28/intent-cases.json"


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("평가 파일에 중복 JSON 키가 있습니다.")
        result[key] = value
    return result


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def load_cases(path):
    """Validate local semantic expectations without contacting any service."""
    raw = path.read_bytes()
    corpus = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_keys)
    _require(isinstance(corpus, dict) and corpus.get("schema_version") == 1, "평가 파일 버전이 다릅니다.")
    _require(set(corpus) == {"schema_version", "description", "cases"}, "평가 파일의 최상위 항목을 확인하세요.")
    _require(isinstance(corpus["description"], str) and corpus["description"].strip(), "평가 범위 설명이 필요합니다.")
    cases = corpus["cases"]
    _require(isinstance(cases, list) and 1 <= len(cases) <= 100, "평가 사례는 1~100개여야 합니다.")
    identifiers = set()
    for case in cases:
        _require(isinstance(case, dict) and set(case) == {"id", "category", "description", "input", "expected"}, "사례 필드가 올바르지 않습니다.")
        for key in ("id", "category", "description", "input"):
            _require(isinstance(case[key], str) and case[key].strip(), f"사례의 {key} 문자열이 필요합니다.")
        _require(case["id"] not in identifiers, "평가 사례 ID가 중복되었습니다.")
        identifiers.add(case["id"])
        _require(len(case["input"]) <= MAX_TEXT_CHARS, f"{case['id']}: 입력 문장이 너무 깁니다.")
        expected = case["expected"]
        _require(isinstance(expected, dict) and {"equipment", "material", "priority", "process"} <= set(expected)
                 <= {"equipment", "material", "priority", "process", "notes_contain", "notes_empty"},
                 f"{case['id']}: 기대값 필드를 확인하세요.")
        for field in ("equipment", "material"):
            values = expected[field]
            _require(isinstance(values, list) and values and all(isinstance(value, str) and len(value) <= 160
                     and value in case["input"] for value in values),
                     f"{case['id']}: 이름의 허용값은 입력에 있는 정확한 문자열이어야 합니다.")
            _require(len(values) == len(set(values)), f"{case['id']}: 이름 허용값이 중복되었습니다.")
        _require(expected["priority"] in PRIORITIES and expected["process"] in PROCESSES,
                 f"{case['id']}: 기대 분류가 지원하는 열거값이 아닙니다.")
        notes = expected.get("notes_contain", [])
        _require(isinstance(notes, list) and all(isinstance(note, str) and note.strip() and note in case["input"] for note in notes),
                 f"{case['id']}: 메모의 기대 문자열이 입력에 없습니다.")
        _require(isinstance(expected.get("notes_empty", False), bool), f"{case['id']}: notes_empty는 참/거짓이어야 합니다.")
        _require(not (notes and expected.get("notes_empty")), f"{case['id']}: 비어 있는 메모와 필수 메모를 동시에 기대할 수 없습니다.")
    return corpus, hashlib.sha256(raw).hexdigest()


def semantic_errors(intent, expected):
    """Compare meaningful extraction labels, with only authored aliases allowed."""
    errors = []
    for field in ("equipment", "material"):
        if intent[field] not in expected[field]:
            errors.append(dict(field=field, expected_any=expected[field], actual=intent[field]))
    for field in ("priority", "process"):
        if intent[field] != expected[field]:
            errors.append(dict(field=field, expected=expected[field], actual=intent[field]))
    for required in expected.get("notes_contain", []):
        if not any(required in note for note in intent["notes"]):
            errors.append(dict(field="notes", missing_user_text=required))
    if expected.get("notes_empty") and intent["notes"]:
        errors.append(dict(field="notes", expected=[], actual=intent["notes"]))
    return errors


def evaluate(corpus, *, live=False, model=DEFAULT_MODEL, api_key=None):
    """Offline fixture validation or one live extraction attempt per case."""
    rows, blocked, attempts = [], None, 0
    for case in corpus["cases"]:
        row = {key: case[key] for key in ("id", "category", "description", "input", "expected")}
        row.update(status="fixture_validated", result=None, semantic_errors=[])
        if live and blocked:
            row.update(status="error", error=dict(code="not_called_after_"+blocked,
                message="앞선 인증·한도 오류로 이 사례는 요청하지 않았습니다."))
        elif live:
            attempts += 1
            try:
                result = parse_intent(case["input"], api_key=api_key, model=model)
                errors = semantic_errors(result["intent"], case["expected"])
                row.update(status="failed" if errors else "passed", result=result, semantic_errors=errors)
            except AIClientError as exc:
                row.update(status="refused" if exc.code == "refusal" else "error",
                           error=dict(code=exc.code, message=str(exc)))
                if exc.code in ("auth", "rate_limit", "api_key", "model"):
                    blocked = exc.code
            except Exception:
                # Never print or serialize an arbitrary provider/local exception.
                row.update(status="error", error=dict(code="unexpected_error",
                           message="예상하지 못한 로컬 오류로 이 사례를 평가하지 못했습니다."))
        rows.append(row)
    counts = dict(Counter(row["status"] for row in rows))
    return dict(mode="live" if live else "offline", live_requested=live,
                model=model if live else None, extraction_attempts=attempts,
                status="fixtures_validated" if not live else "passed" if counts.get("passed", 0) == len(rows) else "attention",
                counts=counts, cases=rows,
                scope=("작성한 한국어 사례의 기대 분류와 실제 추출 결과를 비교한 소규모 출시 평가입니다. 일반 정확도·제조 성공·실물 검증을 입증하지 않습니다."
                       if live else "평가 사례의 형식·열거값·인용 가능한 기대 문자열만 오프라인 확인했습니다. API를 호출하지 않았고 모델 정확도를 측정하지 않았습니다."))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES, help="평가 사례 JSON 파일")
    parser.add_argument("--output", type=Path, required=True, help="새 결과 JSON 경로; 기존 파일 덮어쓰기 금지")
    parser.add_argument("--live", action="store_true", help="명시할 때만 실제 API 호출; 환경변수 OPENAI_API_KEY 사용")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="--live에서 사용할 모델 이름")
    args = parser.parse_args(argv)
    try:
        corpus, cases_sha = load_cases(args.cases)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(f"평가 사례를 읽거나 검증하지 못했습니다: {exc}")
    key = os.environ.get("OPENAI_API_KEY", "").strip() if args.live else None
    if args.live and not key:
        parser.error("--live에는 환경변수 OPENAI_API_KEY가 필요합니다. 키 값은 명령행 인자로 받지 않습니다.")
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # Reserve the output before any possible API request, including races.
        stream = args.output.open("x", encoding="utf-8")
    except FileExistsError:
        parser.error("결과 파일이 이미 있습니다. 이전 결과를 보존하고 새 --output 경로를 지정하세요.")
    except OSError:
        parser.error("새 결과 파일을 만들 수 없습니다. --output 경로를 확인하세요.")
    with stream:
        result = evaluate(corpus, live=args.live, model=args.model, api_key=key)
        result.update(timestamp_utc=datetime.now(timezone.utc).isoformat(), python=platform.python_version(),
                      corpus_sha256=cases_sha,
                      extractor_sha256=hashlib.sha256((ROOT/"dfm/ai_client.py").read_bytes()).hexdigest(),
                      evaluator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      corpus_description=corpus["description"])
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"mode": result["mode"], "status": result["status"], "counts": result["counts"],
                      "extraction_attempts": result["extraction_attempts"], "output": str(args.output)}, ensure_ascii=False))
    return 0 if result["status"] in ("fixtures_validated", "passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
