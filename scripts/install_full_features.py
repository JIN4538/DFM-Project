"""Install a validation-gated checkpoint with current, truthful metadata."""
import argparse,hashlib,json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dfm.feature_localization import load_model


def main(root):
    folder=root/'feature-models';evaluation=json.loads((folder/'calibrated-evaluation.json').read_text())
    if evaluation['chosen_validation']['instance_precision']<.97 or evaluation['portable_max_error']>1e-4:
        raise ValueError('Feature checkpoint has not passed validation gates')
    path=folder/'external_feature_mfinstseg_v2.json';model=json.loads(path.read_text())
    model.update(model_id='mfinstseg-full-corpus-multitask-v2-2026-09-30',
        counts=dict(train=43730,val=9424,test=9241),mixed_external_counts=dict(train=54570,val=11763,test=11550),
        construction_stock_counts=dict(train=1200,val=150,test=150),
        evaluation=evaluation['test'],validation=evaluation['validation'],
        evaluation_note='Semantic metrics include semantic correction head; use localization inference, not backbone-only scores',
        localization_evaluation=evaluation['test_panoptic'],export_max_abs_error=evaluation['portable_max_error'],
        checkpoint_sha256=evaluation['checkpoint_sha256'],training_width=evaluation['width'],
        mfcad_auxiliary_geometry_in_training=json.loads((folder/'evaluation.json').read_text()).get('actual_mfcad_aux_geometry',False),
        runtime_planar_specialist='Separate MFCAD 16-class model; joint calibration metrics apply to MFInstSeg analytic CAD only',
        domain='Analytic surface CAD feature proposals; class-specific validation gates; exact dimensions require independent CAD verification')
    raw=json.dumps(model,separators=(',',':')).encode();path.write_bytes(raw)
    path.with_suffix('.manifest.json').write_text(json.dumps(dict(schema=model['schema'],sha256=hashlib.sha256(raw).hexdigest())))
    local=folder/'external_feature_localization_v1.json';heads=json.loads(local.read_text())
    heads['semantic_sha256']=hashlib.sha256(raw).hexdigest()
    raw=json.dumps(heads,separators=(',',':')).encode();local.write_bytes(raw)
    local.with_suffix('.manifest.json').write_text(json.dumps(dict(schema=heads['schema'],sha256=hashlib.sha256(raw).hexdigest())))
    load_model(local)
    saved=ROOT.parent/'study/ai-full-corpus-2026-09-30/repo-models-before';saved.mkdir(exist_ok=True)
    records=[]
    for p in (path,path.with_suffix('.manifest.json'),local,local.with_suffix('.manifest.json')):
        destination=ROOT/'data/models'/p.name
        if destination.exists() and not (saved/p.name).exists():shutil.copy2(destination,saved/p.name)
        shutil.copy2(p,destination);records.append(dict(file=p.name,sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    (root/'feature-installation.json').write_text(json.dumps(records,indent=2));print(json.dumps(records))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);main(p.parse_args().root)
