# 절삭 제조성 검토 문헌 조사 · 2026-09-20

사용자 요청에 따라 현재 인용 자료를 수집하고, 절삭 제조성 검토 기능을 개발하는 데 필요한 표준·논문·정부 연구·공구 및 CAM 공급사 자료를 추가 조사했다. 이 작업은 문헌 조사와 문서 작성이며 애플리케이션 기능 변경이나 가공 검증을 새로 수행한 작업은 아니다. 사출·프레스는 제외한다.

## 사용자에게 전달하는 보고서

[절삭가공 제조성 검토 문헌 조사 보고서 — Word](../../../deliverables/machining-literature-2026-09-20/절삭가공_제조성검토_문헌조사_2026-09-20.docx)

보고서는 핵심 결론과 개발 우선순위, 현재 인용 목록, 상세 문헌 카드, 자료 확보 수준의 순서로 구성했다. 본문 문헌 번호에서 상세 카드로 이동할 수 있으며 각 카드에는 공식 출처·원문·DOI 링크를 제공한다. [REPORT.md](REPORT.md)는 본문과 상세 카드의 텍스트 사본이며, Word의 현재 인용 목록 전체와 모든 편집 요소를 복제한 파일은 아니다.

최종본은 38쪽이다. 전체 페이지를 렌더링해 시각 확인했으며, 55개 카드·29개 등록 항목·14개 기존 문헌의 누락 여부와 내부 링크 80개·외부 링크 105개의 구조를 검사했다. 외부 링크의 구문 검사와 실제 원문 열람은 별개의 기록이며, 후자의 제한은 문헌별로 명시했다.

## 집계와 범위

- 현재 코드 등록부 29개 항목: `amdfm/evidence.py`의 적층·공통 24개와 `dfm/machining.py`의 절삭 5개. 등록 항목 수이며 모든 결과에 매번 인용되는 자료 수는 아니다.
- 최초 보관 문헌 R01–R14: 14개. 현재 등록부와 일부 중복한다. 이번에 모두 원문을 다시 읽었다는 뜻은 아니다.
- 기존 절삭 코드 5개와 기존 재감사 E01–E09의 합집합: 10개 출처. 네 자료가 겹친다.
- 조사 원자료 F7 + S18 + G16 + P16 = 57레코드. `G08 → F01`, `P05 → G12`를 통합해 55개 카드로 정리했다. 기존 자료 재확인과 신규 조사를 포함하며, S07과 S10은 표준 여러 부를 묶는다. **55편의 신규 논문이 아니며 29+14+55를 총 문헌 수로 합산하지 않는다.**

현재 질문과 기능을 중심으로 조사한 문헌 검토다. 학술 데이터베이스 전체를 같은 검색식으로 전수 선별한 체계적 문헌고찰은 아니다. 원문 관련 절, 공식 카탈로그, 초록, 검색 색인, 코드 등록만 확인한 자료를 카드별로 구분했다. 유료 표준 본문 미열람, 직접 열기 실패, 판본 및 자료 수 불일치는 그대로 기록했다.

## 파일 안내

| 파일 | 내용 |
|---|---|
| [current_citations.json](current_citations.json) | 실제 코드 등록부, 기존 문헌과 연구 기록의 인용 재고. 등록 위치·소스 SHA 포함 |
| [catalog.json](catalog.json) | 중복 정리한 55개 카드와 별칭 |
| [foundations.json](foundations.json) | 제조성 평가의 정의, 검증, STEP 입력, 최근 AI 평가 |
| [standards.json](standards.json) / [조사 메모](standards_notes.md) | STEP PMI, ISO GPS, ASME 제품정의, 공구 정보, 계측·장비 검증 |
| [geometry.json](geometry.json) / [조사 메모](geometry_notes.md) | B-rep 특징 인식, 접근성, 제거 체적, 고정구와 공정 계획 |
| [process.json](process.json) / [조사 메모](process_notes.md) | 공구 치수, 코너·홀·얇은 벽, 절삭력·변형·진동·시간 |
| [report_body.md](report_body.md) | 사용자 관점의 해석과 다음 개발 순서 |
| [bibliography_crosscheck.md](bibliography_crosscheck.md) | 중복·판본·현재 인용 대응 검토 |
| [audit_notes.md](audit_notes.md) | 수치 정의·확률 해석·열람 범위 교차 검토 |
| [build_manifest.json](build_manifest.json) / [quality_check.json](quality_check.json) | 최종 산출물 해시와 문서 구조·렌더 검증 기록 |

## 다시 만들기

`collect_inventory.py`는 소스의 등록부를 AST로 읽는다. `build_report.py`는 JSON과 본문을 읽어 Word·통합 카탈로그·텍스트 사본을 작성한다. `render_report.py`는 Windows에서 Microsoft Word의 읽기 전용 PDF 내보내기를 변환 단계로 사용하고, 문서 스킬의 `render_docx.py`와 번들 Poppler로 페이지를 렌더링한다. 산출물 SHA별로 별도의 QA 디렉터리를 사용하므로 이전 페이지가 섞이지 않는다.

원문 PDF·렌더·개별 원문 읽기 자료와 최종 QA 이미지는 작업공간 `study/machining-literature-2026-09-20/`에 보관한다. 저작권 원문을 사용자 보고서에 통째로 복제하지 않는다. 애플리케이션 정확성 시험, 실제 CAM 대조, 실물 측정은 이 문서 QA와 별개다.
