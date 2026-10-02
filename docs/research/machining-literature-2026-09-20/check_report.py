"""Check the generated document's coverage and links; visual QA is separate."""
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse
from zipfile import ZipFile

from lxml import etree
from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
manifest = json.loads((HERE / 'build_manifest.json').read_text(encoding='utf-8'))
catalog = json.loads((HERE / 'catalog.json').read_text(encoding='utf-8'))
inventory = json.loads((HERE / 'current_citations.json').read_text(encoding='utf-8'))
source = Path(manifest['output'])
sha = hashlib.sha256(source.read_bytes()).hexdigest()
assert sha == manifest['sha256']
qa = HERE.parents[3] / 'study' / 'machining-literature-2026-09-20' / ('report-qa-' + sha[:12])
pdfs = list(qa.glob('*.pdf'))
assert len(pdfs) == 1, pdfs
pdf = PdfReader(pdfs[0])
ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
      'r': 'http://schemas.openxmlformats.org/package/2006/relationships'}
with ZipFile(source) as z:
    xml = etree.fromstring(z.read('word/document.xml'))
    rels = etree.fromstring(z.read('word/_rels/document.xml.rels'))
text = '\n'.join(''.join(p.itertext()) for p in xml.xpath('//w:p', namespaces=ns))
bookmarks = xml.xpath('//w:bookmarkStart/@w:name', namespaces=ns)
anchors = xml.xpath('//w:hyperlink/@w:anchor', namespaces=ns)
ids = [r['id'] for r in catalog['records']]
assert len(ids) == len(set(ids)) == 55
assert all('ref_' + key in bookmarks for key in ids)
assert not set(anchors) - set(bookmarks)
assert len(inventory['runtime_registry']) == 29
assert len(inventory['original_literature']) == 14
assert all(r['id'] in text for r in inventory['runtime_registry'])
assert all(r['id'] in text for r in inventory['original_literature'])
assert all(r['title'] in text for r in catalog['records'])
links = [r.get('Target') for r in rels if r.get('Type', '').endswith('/hyperlink')]
assert links and all(urlparse(url).scheme in {'http', 'https'} and urlparse(url).netloc for url in links)
assert not re.search(r'turn\d+(?:search|view|fetch)\d+|\ue200|\ue202|TODO|TBD', text)
assert 'full_text_sections' not in text and 'official_full_page' not in text
assert len(pdf.pages) == len(list(qa.glob('page-*.png')))
assert all(len((p.extract_text() or '').strip()) > 100 for p in pdf.pages)
assert all(len(p.get('/Annots', [])) >= 0 for p in pdf.pages)
required = ['id', 'title', 'authors', 'year', 'url', 'kind', 'access_level',
            'reviewed_sections', 'findings', 'supports', 'inputs',
            'does_not_support', 'implementation_priority', 'status_notes', 'checked_date']
assert all(all(k in r for k in required) for r in catalog['records'])
inputs = ['current_citations.json', 'foundations.json', 'standards.json',
          'geometry.json', 'process.json', 'report_body.md', 'build_report.py']
result = {
    'checked_date': '2026-09-20',
    'output': str(source), 'sha256': sha, 'page_count': len(pdf.pages),
    'structural_checks': 'passed', 'catalog_cards': len(ids),
    'runtime_registry_entries': 29, 'legacy_records': 14,
    'internal_links': len(anchors), 'external_links': len(links),
    'source_titles_and_ids_present': True,
    'internal_link_targets_resolve': True,
    'external_link_syntax_valid': True,
    'external_link_live_recheck': 'Not repeated by this script; literature reading records state access limits.',
    'all_pages_rendered': True,
    'qa_directory': str(qa),
    'renderer': 'Packaged render_docx.py and bundled Poppler, with Microsoft Word read-only PDF export on Windows',
    'visual_review': {'status': 'pending', 'pages': []},
    'input_sha256': {n: hashlib.sha256((HERE / n).read_bytes()).hexdigest() for n in inputs},
    'scope': 'Document and bibliography QA only. No application or physical manufacturing validation in this task.'
}
(HERE / 'quality_check.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({k: result[k] for k in ['sha256', 'page_count', 'structural_checks', 'catalog_cards', 'internal_links', 'external_links']}, ensure_ascii=False))
