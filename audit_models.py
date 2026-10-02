"""Repeat an external-STL regression audit without modifying input files.

python audit_models.py GB.stl another.stl --out audit.json
Raw and conservative cleanup candidates are evaluated independently. No models
are silently repaired or downloaded; no result is an actual print experiment.
"""
import argparse
from pathlib import Path
import time

from src.core.mesh_diagnostics import cleanup_preview
from src.core.model_loader import load_model, UNIT_SCALE
from src.core.reproducibility import file_sha256, runtime_record, save_new_json
from src.processes.additive import AMRuleEngine


def audit(paths, unit='mm', printer=(250, 250, 250)):
    engine = AMRuleEngine()
    report = dict(runtime=runtime_record(), unit=unit, printer=list(printer),
                  build_direction=[0, 0, 1], models=[],
                  scope='Software behavior only; not a slicer or physical print experiment.')
    for path in paths:
        path = Path(path)
        started = time.monotonic()
        before_hash = file_sha256(path)
        mesh = load_model(str(path), unit=unit)['mesh']
        raw = engine.evaluate(mesh, printer_dims=printer)
        candidate, cleanup = cleanup_preview(mesh)
        cleaned = engine.evaluate(candidate, printer_dims=printer)
        after_hash = file_sha256(path)
        if after_hash != before_hash:
            raise RuntimeError(f'Input changed during audit: {path}')
        row = dict(file=path.name, source_sha256=before_hash, source_unchanged=True,
                   elapsed_seconds=round(time.monotonic()-started, 3),
                   raw=raw, cleanup=cleanup, cleaned=cleaned)
        report['models'].append(row)
        print(f'{path.name}: raw={raw.evaluation_status}/{raw.analysis_scope}/{raw.total_score}, '
              f'cleanup={cleaned.evaluation_status}/{cleaned.analysis_scope}/{cleaned.total_score}; '
              f"FDM layers raw={raw.layer_review.get('status')} "
              f"({raw.layer_review.get('complete_layers')}/{raw.layer_review.get('expected_layers')}), "
              f"cleanup={cleaned.layer_review.get('status')}", flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stl', nargs='+')
    parser.add_argument('--unit', choices=list(UNIT_SCALE), default='mm')
    parser.add_argument('--printer', type=float, nargs=3, default=[250, 250, 250])
    parser.add_argument('--out', required=True, help='New JSON path; existing files are never overwritten')
    args = parser.parse_args()
    if Path(args.out).exists():
        parser.error('Output already exists; choose a new path.')
    report = audit(args.stl, args.unit, tuple(args.printer))
    save_new_json(args.out, report)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
