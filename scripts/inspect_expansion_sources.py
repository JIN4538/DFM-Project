"""Read author metadata and links; external source code is never executed."""
import json, zipfile
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urljoin
import requests
class Links(HTMLParser):
    def __init__(self):super().__init__();self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag=='a':self.links.extend(v for k,v in attrs if k=='href')
root=Path('../study/ai-expansion-2026-09-30')
urls={
 'nist_am':'https://www.nist.gov/el/intelligent-systems-division-73500/production-systems-group/nist-additive-manufacturing-test',
 'nist_step':'https://www.nist.gov/ctl/smart-connected-systems-division/smart-connected-manufacturing-systems-group/mbe-pmi-0',
 'aag_attributes':'https://raw.githubusercontent.com/whjdark/AAGNet/main/dataset/feature_lists/all.json',
 'aag_extractor':'https://raw.githubusercontent.com/whjdark/AAGNet/main/dataset/AAGExtractor.py',
 'pbf_paper':'https://link.springer.com/article/10.1007/s40964-025-00960-6',
}
out={}
for key,url in urls.items():
    r=requests.get(url,timeout=35); (root/(key+'.source')).write_text(r.text,encoding='utf8')
    parser=Links();parser.feed(r.text)
    out[key]=dict(status=r.status_code,url=url,links=[urljoin(url,a) for a in parser.links
        if any(t in a.lower() for t in ('.step','.stp','.zip','download'))])
    print(key,json.dumps(out[key])[:3500],flush=True)
(root/'source-links.json').write_text(json.dumps(out,indent=2),encoding='utf8')
z=zipfile.ZipFile('../study/external-training-2026-09-30/archives/MFInstSeg-data2.zip')
names=[x for x in z.namelist() if 'aag' in x.lower() and x.endswith('.json')]
print('AAG files',names)
preview=z.open(names[0]).read(6500).decode()
(root/'mfinstseg-aag-preview.txt').write_text(preview,encoding='utf8');print(preview[:6500])
