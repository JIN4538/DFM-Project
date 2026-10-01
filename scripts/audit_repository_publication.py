"""Audit publishable bytes, archive references and original source preservation."""
from pathlib import Path
import hashlib
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'validation/publication-2026-10-01/file-integrity.json'
SECRET = re.compile(rb'(?:sk-(?:proj-)?[A-Za-z0-9_-]{32,}|gh[pousr]_[A-Za-z0-9]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    names = set(subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT).decode('utf8').split('\0')) - {''}
    files = []
    suspicious = []
    large = []
    for name in sorted(names):
        path = ROOT / name
        if not path.is_file() or path == OUTPUT:
            continue
        size = path.stat().st_size
        if size >= 100 * 1024 * 1024:
            large.append(name)
        if path.suffix.lower() in ('.py', '.json', '.yaml', '.yml', '.toml', '.md', '.txt', '.html', '.log'):
            if SECRET.search(path.read_bytes()):
                suspicious.append(name)
        files.append({'file': name, 'bytes': size, 'sha256': sha(path)})
    # Baseline includes the original source ZIPs/PDFs/docs, not just code.
    initial = subprocess.check_output(['git', 'ls-tree', '-rz', '--full-tree', '1706eacf03ca30a59f83805dd0c46753e8852a24'], cwd=ROOT)
    baseline = []
    for entry in initial.split(b'\0'):
        if not entry:
            continue
        meta, name = entry.split(b'\t', 1)
        blob = meta.split()[-1].decode()
        name = name.decode('utf8')
        path = ROOT / name
        preserved = path.is_file() and subprocess.check_output(['git', 'hash-object', '--no-filters', '--', name], cwd=ROOT).decode().strip() == blob
        baseline.append({'file': name, 'original_git_blob': blob, 'preserved': preserved})
    # Some baseline standards were explicitly replaced in September. Keep
    # their original Git blobs and identify replacements instead of claiming
    # every working file still has its initial bytes.
    replacements = [r['file'] for r in baseline if not r['preserved']]
    archive = json.loads((ROOT / 'validation/workspace-archive-2026-10-01/manifest.json').read_text(encoding='utf8'))
    references = [r for r in archive['files'] if r['status'] != 'local_only']
    bad = [r['study_file'] for r in references if not (ROOT / r['repository_file']).is_file() or sha(ROOT / r['repository_file']) != r['sha256']]
    result = {'schema': 'dfm-publication-audit-1', 'repository_files': len(files),
              'files': files, 'original_baseline': baseline, 'explicit_replaced_baseline_paths': replacements,
              'oversize_files': large, 'credential_pattern_files': suspicious,
              'workspace_references_checked': len(references), 'workspace_reference_failures': bad,
              'models': [r for r in files if r['file'].startswith('data/models/')],
              'note': 'Excluded external DB/environment/cache are listed in workspace archive manifest; original blobs remain in Git history'}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k: v for k, v in result.items() if k not in ('files', 'original_baseline', 'models')}, ensure_ascii=False))
    if large or suspicious or bad:
        raise ValueError('Publication audit requires review')


if __name__ == '__main__':
    main()
