from pathlib import Path
p=Path(__file__).with_name('report_body.md')
s=p.read_text(encoding='utf-8-sig')
s=s.replace('‘가공할 수 있는 영역’으로 검토 수준이 올라간다','‘선택 공구가 닿는 후보 영역’으로 검토 범위가 구체화된다')
s=s.replace('주황색은 확인할 위치, 미입력은 필요한 정보, 비교 통과는 그 비교의 결과로 명시한다.', '주황색은 현재 조건에서 검출된 확인 항목, 파란색은 단순 선택 위치에 사용한다. 미입력은 필요한 정보로, 비교 통과는 그 비교의 결과로 명시한다.')
p.write_text(s,encoding='utf-8')
