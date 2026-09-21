"""Use the skill's DOCX rasterizer with Word PDF export on Windows.

The selected runtime has no bundled LibreOffice on Windows. No installed
desktop LibreOffice is used. Only the converter function is adapted; page
rasterization remains the packaged render_docx.py implementation.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
manifest=json.loads((HERE/'build_manifest.json').read_text(encoding='utf-8'))
source=Path(manifest['output'])
qa=Path('C:/Users/JIN/Documents/ChatGPT/DFM/study/machining-literature-2026-09-20')/('report-qa-'+manifest['sha256'][:12])
qa.mkdir(parents=True,exist_ok=True)
runtime=Path('C:/Users/JIN/.cache/codex-runtimes/codex-primary-runtime/dependencies')
os.environ['PATH']=str(runtime/'native/poppler/Library/bin')+os.pathsep+os.environ.get('PATH','')
script=Path('C:/Users/JIN/.codex/plugins/cache/openai-primary-runtime/documents/26.904.11930/skills/documents/render_docx.py')
spec=importlib.util.spec_from_file_location('skill_render_docx',script)
renderer=importlib.util.module_from_spec(spec); spec.loader.exec_module(renderer)

def word_to_pdf(doc_path,user_profile,convert_tmp_dir,stem,verbose=False):
    output=Path(convert_tmp_dir)/(stem+'.pdf')
    command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(HERE/'render_word.ps1'),'-InputDocx',str(doc_path),'-OutputPdf',str(output)]
    completed=subprocess.run(command,capture_output=True,text=True,timeout=180)
    if completed.returncode:
        raise RuntimeError(completed.stdout+'\n'+completed.stderr)
    print(completed.stdout,flush=True)
    return str(output),'Microsoft Word read-only ExportAsFixedFormat; no LibreOffice used'

renderer.convert_to_pdf=word_to_pdf
sys.argv=[str(script),str(source),'--output_dir',str(qa),'--emit_pdf','--dpi','120']
renderer.main()
print(json.dumps({'renderer':'packaged render_docx.py with explicit Word COM PDF converter on Windows','qa':str(qa)},ensure_ascii=False))
