# 외부 형상 전수 검토 입력

사용자가 제공한 바탕화면 `무작위 형상 테스트`의 **형상 26개(STEP 21, STL 4, 3MF 1)와 동반 TXT 5개**를 원래 이름·하위 폴더·파일 바이트 그대로 보관한다. [manifest.json](manifest.json)의 SHA-256은 [독립 감사의 입력 SHA](../../validation/v3/random-corpus/independent/initial-manifest.json)와 일치한다.

다른 컴퓨터에서 저장소를 복제한 뒤에도 앱의 **무작위 형상 테스트** 입력에서 이 폴더를 사용할 수 있다. 사용자 바탕화면에 같은 이름의 폴더가 있으면 기존 동작대로 해당 폴더를 우선한다.

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\audit_random_models.py --input examples/corpus --out validation/v3/runs/new-corpus-audit --jobs 2 --cad-timeout 180 --file-timeout 7200 --detail-timeout 90 --section-samples 64
```

출력 폴더는 매번 새 경로를 지정한다. [검토 방법과 과거 결과](../../docs/VALIDATION_CORPUS.md)의 확정·부분·미확정 범위를 구분한다. 형상을 저장소에 포함한 것은 새 제조 적합성 판정이 아니다. STEP 곡면 입력과 조립체, STL 단위 미확정 사례도 원본 그대로 포함한다.

이 파일들은 외부에서 입수해 사용자가 제공한 테스트 자료다. 동반 TXT에는 일부 TraceParts 공급사·부품 번호가 있다. 각 형상의 원저자·다운로드 URL·라이선스가 모두 확인된 것은 아니며, 이 저장소가 원저작권이나 일괄 재배포 허가를 주장하지 않는다. 확인되지 않은 출처·치수를 임의로 보충하지 않았다.
