"""Manufacturer specifications with archived source evidence and exact scope."""
import argparse, concurrent.futures, hashlib, html, json, re
from pathlib import Path
import requests

ROWS=[
 ('Bambu Lab A1','MEX',[256,256,256],'https://us.store.bambulab.com/products/a1'),
 ('Bambu Lab A1 mini','MEX',[180,180,180],'https://asia.store.bambulab.com/products/a1-mini'),
 ('Bambu Lab P1S','MEX',[256,256,256],'https://ca.store.bambulab.com/products/p1s'),
 ('Bambu Lab P1P','MEX',[256,256,256],'https://ca.store.bambulab.com/products/p1s'),
 ('UltiMaker S7','MEX',[330,240,300],'https://store.ultimaker.com/ultimaker-s7-3d-printer'),
 ('UltiMaker S5','MEX',[330,240,300],'https://store.ultimaker.com/ultimaker-s5-3d-printer'),
 ('UltiMaker S3','MEX',[230,190,200],'https://store.ultimaker.com/ultimaker-s3-3d-printer'),
 ('UltiMaker 2+ Connect','MEX',[223,220,205],'https://store.ultimaker.com/ultimaker-2-connect'),
 ('Creality Ender-3 V3','MEX',[220,220,250],'https://www.creality.com/compare/compare-ender-3-v3-series'),
 ('Creality Ender-3 V3 SE','MEX',[220,220,250],'https://www.creality.com/compare/compare-ender-3-v3-series'),
 ('Creality Ender-3 V3 KE','MEX',[220,220,240],'https://www.creality.com/compare/compare-ender-3-v3-series'),
 ('ELEGOO Saturn 4 Ultra (12K)','VPP',[218.88,122.88,220],'https://www.elegoo.com/pages/elegoo-saturn-4-ultra'),
 ('Anycubic Photon Mono M7 Pro','VPP',[223,126,230],'https://store.anycubic.com/products/photon-mono-m7-pro'),
 ('EOS P 396','PBF_POLYMER',[340,340,600],'https://www.eos.info/polymer-solutions/polymer-printers/data-sheets/sds-eos-p-396'),
 ('EOS M 400-4','PBF_METAL',[400,400,400],'https://www.eos.info/metal-solutions/metal-printers/data-sheets/sds-eos-m-400-4'),
 ('3D Systems DMP Flex 350 Dual','PBF_METAL',[275,275,420],'https://www.3dsystems.com/index.php/3d-printers/dmp-flex-350-dual'),
 ('Haas Mini Mill (신형)','CNC',[406,356,381],'https://www.haascnc.com/machines/vertical-mills/mini-mills/models/minimill.html'),
 ('Haas VF-4','CNC',[1270,508,635],'https://www.haascnc.com/it/machines/vertical-mills/vf-series/models/medium/vf-4.html'),
 ('Tormach 1100M','CNC',[457,279,413],'https://knowledgebase.tormach.com/1100m/machine-specifications'),
 ('Tormach 770M','CNC',[356,191,337],'https://knowledgebase.tormach.com/770m/machine-specifications'),
 ('Tormach 1100MX','CNC',[457,279,413],'https://knowledgebase.tormach.com/1100mx/machine-specifications'),
 ('Tormach 770MX','CNC',[356,191,337],'https://knowledgebase.tormach.com/770mx/machine-specifications'),
 ('Tormach PCNC 440','CNC',[254,159,254],'https://knowledgebase.tormach.com/pcnc440/machine-specifications'),
]

def main(root):
    folder=root/'machine-sources';folder.mkdir(exist_ok=True);urls=list(dict.fromkeys(r[3] for r in ROWS))
    def fetch(url):
        try:
            r=requests.get(url,timeout=60);r.raise_for_status();name=hashlib.sha256(url.encode()).hexdigest()[:16]+'-'+hashlib.sha256(r.content).hexdigest()[:16]+'.html'
            if not (folder/name).exists():(folder/name).write_bytes(r.content)
            text=html.unescape(re.sub('<[^>]+>',' ',r.text));text=re.sub(r'\s+',' ',text)
            return url,dict(status=r.status_code,file=name,sha256=hashlib.sha256(r.content).hexdigest(),text=text)
        except requests.RequestException as e:return url,dict(error=str(e))
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:evidence=dict(pool.map(fetch,urls))
    bundle=dict(schema_version=1,sources=[],profiles=[]);audit=[]
    for number,(name,process,dims,url) in enumerate(ROWS):
        e=evidence[url]
        if 'error' in e:audit.append(dict(machine=name,accepted=False,reason=e['error']));continue
        # Exact numeric triplets, or manufacturer separate X/Y/Z table rows.
        pattern=r'\s*[x×*]\s*'.join(re.escape(str(v))+r'(?:\.0+)?' for v in dims)
        match=re.search(pattern,e['text'],re.I)
        if match is None and process=='CNC':
            matches=[re.search(r'(?:'+axis+r'[- ]?Axis|Asse '+axis+r').{0,120}?\b'+re.escape(str(v))+r'\s*mm',e['text'],re.I) for axis,v in zip('XYZ',dims)]
            if all(matches):match=matches[0]
        if match is None:
            audit.append(dict(machine=name,accepted=False,reason='Dimension sequence not verified in fetched primary HTML'));continue
        sid='EXP_MACHINE_'+str(number+1);locator=('Manufacturer '+('Travels X/Y/Z' if process=='CNC' else 'Build volume XYZ')+' table; '+name)
        limits=['재료·공구·고정 및 세부 프로파일은 별도 조건']
        if process=='CNC':limits.append('축 이동량은 참고값이며 부품 크기·고정 공간으로 자동 적용하지 않음')
        if process=='PBF_METAL':limits.append('명목 높이는 빌드판 포함; 판 두께·사용 여유를 별도 지정')
        source=dict(id=sid,title=name+' official specifications',publisher=name.split()[0],url=url,accessed='2026-09-30',
            locator=locator,revision='Page checked 2026-09-30',verification='primary_source_checked',limitations=limits,source_sha256=e['sha256'])
        field='axis_travel_mm' if process=='CNC' else 'build_volume_mm'
        bundle['sources'].append(source);bundle['profiles'].append(dict(id=sid+'_PROFILE',label=name,process=process,category='machine',machine=name,material='미확정',
            conditions=['명시한 모델과 구성의 제조사 명목 치수'],limitations=limits,source_ids=[sid],physical_validation='not_validated_by_project',
            parameters={field:dict(value=dims,unit='mm',kind='machine_specification',source_ids=[sid],locator=locator,conditions=['제조사 명목 XYZ 치수'],application='reference_only' if process=='CNC' else 'automatic')}))
        audit.append(dict(machine=name,accepted=True,source_sha256=e['sha256'],evidence_excerpt=e['text'][max(0,match.start()-100):match.end()+100]))
    Path('data/conditions/expanded_machines.json').write_text(json.dumps(bundle,ensure_ascii=False,indent=2),encoding='utf8')
    (root/'machine-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(added=len(bundle['profiles']),audit=audit),ensure_ascii=False),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);main(p.parse_args().root)
