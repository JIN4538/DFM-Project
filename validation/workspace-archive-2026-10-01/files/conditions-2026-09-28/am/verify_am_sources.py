from pathlib import Path
import hashlib,json,re
ROOT=Path(__file__).parent
REPO=ROOT.parents[2]/'DFM-Project'
data=json.loads((REPO/'data/conditions/am.json').read_text(encoding='utf8'))
sources={s['id']:s for s in data['sources']}
ini=(ROOT/'PrusaResearch-1.14.2.ini').read_text(encoding='utf8').splitlines()
checked=0
for profile in data['profiles']:
    for key,p in profile['parameters'].items():
        assert p['source_ids'] and p['locator']
        assert set(p['source_ids']) <= set(profile['source_ids'])
        if p['source_ids']==['AM-PRUSA-SETTINGS-1142']:
            lineno=int(re.search(r'; L(\d+)$',p['locator']).group(1))
            literal=ini[lineno-1].split('=',1)[1].strip()
            assert float(literal)==p['value'],(profile['id'],key,literal,p['value'])
            checked+=1
        if key.startswith(('supported_wall','unsupported_wall','vertical_wall','horizontal_wall','minimum_wall')):
            assert p['application']=='reference_only'
        if key.startswith('nominal_build_volume'):
            assert p['application']=='reference_only'
        assert p['value'] is not None
for sid,file in [('AM-PRUSA-SETTINGS-1142','PrusaResearch-1.14.2.ini'),('AM-EOS-316L-202207','eos-316l.pdf'),('AM-EOS-ALSI10MG-PDF','eos-alsi10mg.pdf'),('AM-FORMLABS-NYLON12-TDS-REV01','formlabs-nylon12-rev01.pdf')]:
    assert hashlib.sha256((ROOT/file).read_bytes()).hexdigest()==sources[sid]['sha256']
result={'record_count':len(data['profiles']),'source_count':len(sources),'ini_parameter_values_rechecked_against_original_line':checked,'source_file_sha256_rechecked':4,'result':'pass'}
(ROOT/'am-source-verification.json').write_text(json.dumps(result,indent=2),encoding='utf8')
print(json.dumps(result,indent=2))
