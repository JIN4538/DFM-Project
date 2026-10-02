"""Choose by calibrated validation localization quality, never held-out scores."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.install_full_features import main as install

def main():
    run=ROOT.parent/'study/ai-full-corpus-2026-09-30'
    choices=[]
    for name in ('feature-models','feature-geometric/feature-models','feature-geometric64/feature-models'):
        evaluation=json.loads((run/name/'calibrated-evaluation.json').read_text())
        q=evaluation['chosen_validation']
        choices.append(dict(folder=name,width=evaluation['width'],validation=q,
            admissible=q['instance_precision']>=.97 and evaluation['portable_max_error']<1e-4))
    selected=max((r for r in choices if r['admissible']),key=lambda r:r['validation']['pq'])
    record=dict(criterion='Validation instance precision >=.97, then highest validation panoptic quality; held-out test excluded from model selection',
        candidates=choices,selected=selected)
    (run/'feature-selection.json').write_text(json.dumps(record,indent=2),encoding='utf8')
    folder=run/selected['folder']
    install(folder.parent)
    print(json.dumps(dict(selected=selected)))

if __name__=='__main__':main()
