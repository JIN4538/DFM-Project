"""Build a local, geometry-free overview of a completed corpus audit."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import shutil
from urllib.parse import quote


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def build(audit, refreshed, out, events=None, refinement=None):
    raw, current = read(audit/"summary.json"), read(refreshed/"summary.json")
    if raw["completed_files"]!=raw["planned_files"] or current["completed_files"]!=current["planned_files"]:
        raise ValueError("전수 실행과 최신 결과 대조가 모두 끝난 뒤 요약하세요.")
    if out.exists():raise ValueError("이전 결과를 보존하도록 새 경로를 지정하세요.")
    event_summary=read(events/"summary.json") if events else None
    if event_summary:
        event_manifest=read(events/"manifest.json")
        if event_summary["target_count"]!=event_manifest["target_count"] or not all(event_summary[k] for k in (
                "original_sources_unchanged","cache_unchanged","frozen_engine_unchanged")):
            raise ValueError("형상 변화 단면의 완료·무결성 기록을 먼저 확인하세요.")
    out.mkdir(parents=True)
    fresh={r["file_id"]:r for r in current["results"]}
    if not all(r["status"]=="refreshed" for r in fresh.values()):raise ValueError("갱신 실패 사례를 먼저 검토하세요.")
    cases=[c for r in raw["results"] for c in r["cases"]]
    totals={p:{mode:dict(Counter(c.get(mode+"_status","unavailable") for c in cases if c["process"]==p))
        for mode in ("wall","section","layer")} for p in ("MEX","VPP","PBF_POLYMER","PBF_METAL")}
    files=[]
    for r in raw["results"]:
        if r["id"] not in fresh:raise ValueError("최신 대조에서 빠진 입력이 있습니다.")
        files.append(dict(id=r["id"],file=r["relative_path"],format=r["format"],source_sha256=r["source_sha256"],
            original_unchanged=r["original_unchanged"],input_status=r["status"],extents_mm=r.get("extents_mm"),
            unit_status=r.get("metadata",{}).get("unit_status"),solid_count=r.get("metadata",{}).get("solid_count"),
            cad_geometry_kind=r.get("metadata",{}).get("cad_geometry_kind"),cases=len(r["cases"]),
            section_statuses=dict(Counter(c.get("section_status","unavailable") for c in r["cases"]))))
    manifest=read(audit/"manifest.json")
    formats=Counter(f["suffix"] for f in manifest["inventory"])
    if not all(f["original_unchanged"] for f in files):raise ValueError("원본 변경 여부를 먼저 검토하세요.")
    result=dict(created_utc=datetime.now(timezone.utc).isoformat(),geometry_files=len(files),case_count=len(cases),
        process_totals=totals,files=files,raw_code_sha256=manifest["code_sha256"],
        current_code_sha256=read(refreshed/"manifest.json")["quick_code_sha256"],
        scope="Every listed geometry and selected CAD solid across four processes; numerical geometry audit, no physical print qualification.")
    if event_summary:
        result["event_sections"]={k:event_summary[k] for k in ("target_count","unique_geometry_count","whole_single_body_duplicates","status_counts")}
    (out/"summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    esc=lambda v:html.escape(str(v))
    link=lambda p:quote(Path(os.path.relpath(p,out)).as_posix(),safe="/._-")
    fmt=lambda d:" · ".join(f"{k}: {v}" for k,v in d.items())
    process_names={"MEX":"FFF/FDM","VPP":"SLA/DLP","PBF_POLYMER":"고분자 PBF/SLS","PBF_METAL":"금속 PBF/LPBF"}
    modes="".join(f"<tr><th>{process_names[p]}</th>"+"".join(f"<td>{esc(fmt(totals[p][m]))}</td>" for m in ("wall","section","layer"))+"</tr>" for p in totals)
    rows,groups=[],[]
    for f in files:
        dims=" × ".join(f"{v:.6g}" for v in f["extents_mm"]) if f["extents_mm"] else "미확정"
        kind="곡면 전용" if f["cad_geometry_kind"]=="surface" else f["solid_count"] if f["solid_count"] is not None else "메시"
        rows.append(f"<tr><td><a href='#{f['id']}'>{esc(f['file'])}</a></td><td>{esc(dims)}</td><td>{esc(kind)}</td><td>{f['cases']}</td><td>{esc(fmt(f['section_statuses']))}</td></tr>")
        reports=[]
        for c in fresh[f["id"]]["cases"]:
            if c["status"]!="refreshed":raise ValueError("미완료 사례가 있습니다.")
            target=refreshed/f["id"]/c["report_html"]
            reports.append(f"<li><a href='{link(target)}'>{esc(c['name'])}</a></li>")
        groups.append(f"<details id='{f['id']}'><summary>{esc(f['file'])} · {f['cases']}건</summary><p>SHA-256: <code>{f['source_sha256']}</code></p><ul>{''.join(reports)}</ul></details>")
    extra=""
    if event_summary:
        event_rows=[]
        names={f['id']:f['file'] for f in files}
        for e in event_summary['results']:
            relative=e.get('relative_difference_from_tetra')
            difference=f"{relative*100:.7g}%" if relative is not None else "미확정"
            record=events/'records'/f"{e['file_id']}_{e['selection']}.json"
            known=e.get('complete_samples')
            requested=e.get('requested_samples')
            event_rows.append(f"<tr><td><a href='{link(record)}'>{esc(names[e['file_id']])} · {esc(e['selection'])}</a></td><td>{esc(e['status'])}</td><td>{known if known is not None else '—'}/{requested if requested is not None else '—'}</td><td>{difference}</td><td>{esc(e.get('reason') or '')}</td></tr>")
        extra=f"<h2>형상 변화 기준의 추가 체적 검산</h2><p>고유 {event_summary['unique_geometry_count']}대상에 단일 솔리드 전체/개별 중복 {event_summary['whole_single_body_duplicates']}건을 포함한 {event_summary['target_count']}회입니다. 공정 중립인 단면 기하를 한 번씩 계산했으며 4공정 각각의 별도 물리해석이 아닙니다. 상태: {esc(fmt(event_summary['status_counts']))}.</p><p>고유 정점 높이 사이에 두 Gauss 단면을 배치했습니다. 부분 구간·예산 초과는 전체 체적 미확정이며 표본 최대는 전역 최대가 아닙니다.</p><details><summary>모든 추가 검산 결과 펼치기</summary><div class='table'><table><tr><th>형상·선택</th><th>상태</th><th>확정/요청 단면</th><th>사면체 체적 대비 상대차</th><th>미확정 이유</th></tr>{''.join(event_rows)}</table></div></details>"
    if refinement:
        extra+=f"<p><a href='{link(refinement/'index.html')}'>균등 단면 상위 5대상의 256/1,024개 재표본화 결과</a></p>"
    figure=Path(__file__).resolve().parents[1]/'validation/v3/random-corpus/fan-event-sampling.png'
    if figure.exists():
        shutil.copyfile(figure,out/figure.name)
        extra+=f"<figure><img src='{figure.name}' style='width:100%;height:auto' alt='냉각팬 끝판을 균등 표본이 놓치는 이유'><figcaption>냉각팬 솔리드2: 균등 64개는 끝판을 놓쳤지만 구간별 10개는 메시 체적과 약 0.0000000645% 차이를 보였습니다. 이 사례의 체적 검산값이며 모든 형상의 정확도 보증이 아닙니다.</figcaption></figure>"
    content=f"""<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AM-DFM 무작위 형상 전수 검토</title><style>
body{{font:16px/1.7 'Malgun Gothic',sans-serif;color:#202b31;max-width:1180px;margin:40px auto;padding:0 24px}}h1{{font-size:30px}}h2{{font-size:22px;margin-top:34px}}table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{padding:9px;border:1px solid #ddd;text-align:left;overflow-wrap:anywhere}}th{{background:#eff3f5}}a{{color:#245d87}}details{{border-bottom:1px solid #ddd;padding:12px 0}}summary{{cursor:pointer;font-weight:bold}}code{{overflow-wrap:anywhere}}.lead{{font-size:20px}}.table{{overflow-x:auto}}
</style><h1>무작위 형상 전수 검토</h1><p class="lead">형상 {len(files)}개 · 조립체·개별 솔리드와 4개 공정의 검토 {len(cases)}건</p>
<p>입력 폴더의 STEP {formats['.step']+formats['.stp']}개·STL {formats['.stl']}개·3MF {formats['.3mf']}개와 관련 TXT {formats['.txt']}개를 조사했습니다. 빌드 공간으로 제한하거나 형상을 축소하지 않았습니다. 아래 수치는 검토 실행과 기하 측정의 상태이며 출력 성공률이 아닙니다.</p>
<h2>확인한 개선</h2><ul><li>복잡 곡면의 CAD 적분 정밀도와 STEP 테셀레이션을 검산했습니다. Valve의 정확한 영면적·곡면 전용 입력·109솔리드 입력을 처리합니다.</li>
<li>3MF의 단위·객체 변환을 적용합니다. 공정별 문헌과 실험조건을 구분하고 모든 지원 공정에 단면 검토를 제공합니다.</li>
<li>단면 완료는 표본 사이 특징의 정확성을 보증하지 않습니다. 냉각팬의 균등 64표본은 얇은 끝판을 놓쳤으며, 별도 정밀 재검토와 표본 검산 결과를 함께 확인해야 합니다.</li>
<li>Pump의 남은 메시 결함, 곡면 입력의 재료 내부, 여러 객체의 합집합은 미확정으로 보존했습니다.</li></ul>
<h2>공정별 상세 실행</h2><p>complete: 요청한 단면/층 계산 완료 · measured: 법선 거리 표본 측정 · partial: 부분 결과 · unknown: 판정 보류 · unavailable: 계산 한도 때문에 실행 보류 · not_applicable: 해당 공정 미적용. 미확정은 결함 확정 또는 측정값 0을 뜻하지 않습니다. 층수 한도는 형상 크기·층 간격을 자동 변경해 맞추지 않으며 개별 결과에 이유를 남깁니다.</p>
<div class="table"><table><tr><th>공정</th><th>벽 표본</th><th>균등 단면 64개</th><th>MEX 층간</th></tr>{modes}</table></div>
<h2>모든 형상</h2><p>외곽은 입력 좌표축의 mm 값입니다. STL은 원래 단위가 없어 mm 가정이며, STEP·3MF는 파일 선언 단위를 사용했습니다. 솔리드 수가 여러 개인 파일은 전체 배치와 각 솔리드를 따로 검토했습니다.</p>
<div class="table"><table><tr><th>입력</th><th>외곽 (mm)</th><th>솔리드/입력 종류</th><th>검토 건수</th><th>단면 상태</th></tr>{''.join(rows)}</table></div>
{extra}<h2>파일별 전체 보고서</h2><p>항목을 펼쳐 공정과 솔리드를 선택하세요. whole은 전체 입력, body 번호는 STEP의 솔리드 번호입니다.</p>{''.join(groups)}
<h2>계산 출처</h2><p>최신 빠른 검토는 고정된 메시로 다시 실행하고 원감사와 수치·면 선택을 대조했습니다. 벽·균등 단면·MEX 층간의 상세 수치는 원감사 결과를 출처와 함께 재사용했습니다. 상세 계산을 최신 코드로 전부 재실행했다고 표현하지 않습니다.</p>
<p>원감사 코드: <code>{result['raw_code_sha256']}</code><br>최신 빠른 검토 코드: <code>{result['current_code_sha256']}</code></p>
<p><a href='{link(audit/'index.html')}'>보존한 원감사</a> · <a href='{link(refreshed/'index.html')}'>최신 수치 불변성 대조와 보고서</a> · <a href='summary.json'>집계 JSON</a></p></html>"""
    (out/"index.html").write_text(content,encoding="utf-8")
    print(json.dumps(dict(files=len(files),cases=len(cases),overview=str(out/"index.html"))))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--audit",type=Path,required=True)
    parser.add_argument("--refreshed",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--events",type=Path)
    parser.add_argument("--refinement",type=Path)
    args=parser.parse_args()
    build(args.audit.resolve(),args.refreshed.resolve(),args.out.resolve(),
        args.events.resolve() if args.events else None,args.refinement.resolve() if args.refinement else None)
