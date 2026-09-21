"""Check archived PDF bytes against the supplied-file manifest (no PDF edits)."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def stream_hash(stream):
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(65536):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--git-ref', help='Also check a Git tree, e.g. HEAD; INDEX checks staged blobs')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'references/manifest-2026-09-21.json').read_text(encoding='utf-8'))
    results = []
    for record in manifest['documents']:
        relative = record['repository_path']
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT) or path.suffix.lower() != '.pdf':
            raise ValueError(f'Invalid archive path: {relative}')
        with path.open('rb') as stream:
            sha, size = stream_hash(stream)
        entry = {'id': record['id'], 'path': relative, 'sha256': sha,
                 'working_tree_matches': sha == record['sha256'] and size == record['bytes']}
        if args.git_ref:
            revision = '' if args.git_ref == 'INDEX' else args.git_ref
            with subprocess.Popen(['git', 'cat-file', 'blob', f'{revision}:{relative}'],
                                  cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
                git_sha, git_size = stream_hash(process.stdout)
                error = process.stderr.read().decode('utf-8', errors='replace')
                if process.wait():
                    raise RuntimeError(error)
            entry['git_blob_matches'] = git_sha == record['sha256'] and git_size == record['bytes']
        results.append(entry)
    ok = all(r['working_tree_matches'] and r.get('git_blob_matches', True) for r in results)
    report = {'ok': ok, 'files': len(results), 'pages': sum(r['pages'] for r in manifest['documents']),
              'git_ref': args.git_ref, 'results': results}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(f"Reference archive: {len(results)} PDFs, {report['pages']} pages; bytes match: {ok}")
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
