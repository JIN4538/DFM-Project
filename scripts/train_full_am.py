"""Memory-mapped full AM learning; per-source validation, frozen test groups."""
import argparse, hashlib, json, sqlite3, sys, time
from pathlib import Path
import numpy as np
import torch
from torch import nn
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from amdfm.neural_orientation import SCHEMA, BASE_NAMES, feature_contract_sha256, load_model
SOURCES = ('PBF-orientation', 'CadQuarry', 'Thingi10K')


def consolidate(root, name):
    folder = root/'am-full'
    target = folder/'arrays'
    target.mkdir(exist_ok=True)
    db = sqlite3.connect(f'file:{(folder/"index.sqlite").as_posix()}?mode=ro', uri=True)
    width, views = (35, 48) if name == 'height' else (62, 240)
    result = {}
    for split in ('train', 'validation', 'test'):
        rows = [(dataset, json.loads(raw)['path']) for dataset, raw in db.execute('SELECT dataset,record FROM records WHERE accepted=1 AND split=? ORDER BY dataset,id', (split,))]
        size = len(rows)*views
        paths = {k: target/f'{split}-{name}-{k}.npy' for k in ('x', 'y', 'source')}
        complete = target/f'{split}-{name}-complete.json'
        if not complete.exists():
            x = np.lib.format.open_memmap(paths['x'], mode='w+', dtype='float32', shape=(size, width))
            y = np.lib.format.open_memmap(paths['y'], mode='w+', dtype='float32', shape=(size,))
            source = np.lib.format.open_memmap(paths['source'], mode='w+', dtype='uint8', shape=(size,))
            for i, (dataset, path) in enumerate(rows):
                with np.load(folder/path, allow_pickle=False) as z:
                    x[i*views:(i+1)*views] = z[name+'_x']
                    y[i*views:(i+1)*views] = z[name+'_y']
                    source[i*views:(i+1)*views] = SOURCES.index(dataset)
            x.flush(); y.flush(); source.flush()
            complete.write_text(json.dumps(dict(rows=size, meshes=len(rows), sources=SOURCES)))
            del x, y, source
        result[split] = {k: np.load(path, mmap_mode='r', allow_pickle=False) for k, path in paths.items()}
    db.close()
    return result


def evaluate(net, rows, mean, scale):
    sums = np.zeros((3, 3))
    net.eval()
    with torch.no_grad():
        for start in range(0, len(rows['y']), 8192):
            x = torch.from_numpy(((rows['x'][start:start+8192]-mean)/scale).astype('float32'))
            y = rows['y'][start:start+8192]
            p = np.clip(net(x).numpy()[:, 0], 0, 1)
            s = rows['source'][start:start+8192]
            for ds in range(3):
                delta = p[s == ds]-y[s == ds]
                sums[ds] += [np.abs(delta).sum(), (delta**2).sum(), len(delta)]
    return {ds: dict(mae=float(row[0]/max(row[2], 1)), mse=float(row[1]/max(row[2], 1)), queries=int(row[2])) for ds, row in zip(SOURCES, sums)}


def fit(data, name, previous, epochs, root):
    mean = np.array(previous['mean'], dtype='float32')
    scale = np.array(previous['scale'], dtype='float32')
    layers = []
    for weight, bias in zip(previous['weights'], previous['biases']):
        w = np.asarray(weight)
        layer = nn.Linear(w.shape[0], w.shape[1])
        layer.weight.data.copy_(torch.tensor(w.T, dtype=torch.float32))
        layer.bias.data.copy_(torch.tensor(bias, dtype=torch.float32))
        layers.extend([layer, nn.ReLU()])
    net = nn.Sequential(*layers[:-1])
    optimizer = torch.optim.AdamW(net.parameters(), lr=.0005, weight_decay=.0001)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=3, factor=.5, min_lr=.000025)
    training = data['train']
    count = np.bincount(training['source'], minlength=3)
    weight = (1/np.maximum(count, 1)); weight /= (weight*count).sum()/count.sum()
    rng = np.random.default_rng(20260930)
    history = []
    best, chosen, checkpoint = float('inf'), 0, None
    started = time.monotonic()
    initial = evaluate(net, data['validation'], mean, scale)
    best = np.mean([v['mse'] for v in initial.values()])
    checkpoint = {k: v.clone() for k, v in net.state_dict().items()}
    for epoch in range(epochs):
        net.train()
        order = rng.permutation(len(training['y']))
        losses = []
        for start in range(0, len(order), 8192):
            idx = order[start:start+8192]
            x = torch.from_numpy(((training['x'][idx]-mean)/scale).astype('float32'))
            y = torch.from_numpy(np.array(training['y'][idx]))
            w = torch.from_numpy(weight[training['source'][idx]].astype('float32'))
            optimizer.zero_grad()
            loss = (((net(x)[:, 0]-y)**2)*w).mean()
            loss.backward()
            nn.utils.clip_grad_norm_(net.parameters(), 5.)
            optimizer.step()
            losses.append(float(loss.detach()))
        validation = evaluate(net, data['validation'], mean, scale)
        objective = float(np.mean([v['mse'] for v in validation.values()]))
        scheduler.step(objective)
        row = dict(epoch=epoch+1, loss=float(np.mean(losses)), objective=objective, validation=validation, seconds=time.monotonic()-started)
        history.append(row)
        print(json.dumps(dict(network=name, **row)), flush=True)
        if objective < best-1e-7:
            best, chosen = objective, epoch+1
            checkpoint = {k: v.clone() for k, v in net.state_dict().items()}
            torch.save(checkpoint, root/'am-full'/f'{name}-best-state.pt')
        if epoch+1-chosen >= 12:
            break
    net.load_state_dict(checkpoint)
    dense = [l for l in net if isinstance(l, nn.Linear)]
    artifact = dict(mean=mean.tolist(), scale=scale.tolist(), weights=[l.weight.detach().numpy().T.tolist() for l in dense],
        biases=[l.bias.detach().numpy().tolist() for l in dense], selected_epoch=chosen, validation_mse=best)
    return artifact, history, evaluate(net, data['test'], mean, scale), initial


def evaluate_portable(net, rows):
    sums = np.zeros((3, 3))
    for start in range(0, len(rows['y']), 8192):
        h = (rows['x'][start:start+8192]-net['mean'])/net['scale']
        for i, (w, b) in enumerate(zip(net['weights'], net['biases'])):
            h = h@w+b
            if i < len(net['weights'])-1:
                h = np.maximum(h, 0)
        pred = np.clip(h[:, 0], 0, 1)
        truth = rows['y'][start:start+8192]
        source = rows['source'][start:start+8192]
        for ds in range(3):
            delta = pred[source == ds]-truth[source == ds]
            sums[ds] += [np.abs(delta).sum(), (delta**2).sum(), len(delta)]
    return {ds: dict(mae=float(r[0]/max(r[2], 1)), mse=float(r[1]/max(r[2], 1)), queries=int(r[2])) for ds, r in zip(SOURCES, sums)}


def main(root, epochs):
    while not (root/'am-full/audit.json').exists() or not json.loads((root/'am-full/audit.json').read_text())['complete_stream']:
        time.sleep(10)
    torch.set_num_threads(2)
    torch.manual_seed(20260930)
    previous = load_model(ROOT/'data/models/neural_orientation_external_v3.json')
    networks, histories, metrics = {}, {}, {}
    for name in ('height', 'overhang'):
        data = consolidate(root, name)
        networks[name], histories[name], new, initial = fit(data, name, previous['networks'][name], epochs, root)
        metrics[name] = dict(previous=evaluate_portable(previous['networks'][name], data['test']), expanded=new, initial_validation=initial)
        (root/'am-full'/f'{name}-fit.json').write_text(json.dumps(dict(network=networks[name], history=histories[name], metrics=metrics[name]), indent=2))
        del data
    model = dict(schema=SCHEMA, model_id='public-am-full-corpus-2026-09-30', base_names=list(BASE_NAMES), networks=networks,
        measurement_source_sha256=hashlib.sha256((ROOT/'amdfm/orientation.py').read_bytes()).hexdigest(),
        feature_contract_sha256=feature_contract_sha256(), angle_range_deg=[25, 75],
        sources=list(SOURCES), target_definition='Exact original-mesh direction measurements; every mesh independently checked; per-source balanced validation',
        full_corpus_audit_sha256=hashlib.sha256((root/'am-full/audit.json').read_bytes()).hexdigest())
    path = root/'am-full/neural_orientation_external_v4.json'
    raw = json.dumps(model, separators=(',', ':')).encode()
    path.write_bytes(raw)
    path.with_suffix('.manifest.json').write_text(json.dumps(dict(schema=SCHEMA, sha256=hashlib.sha256(raw).hexdigest())))
    summary = dict(metrics=metrics, histories=histories, source_balance='Equal dataset aggregate loss; equal-source validation MSE',
        sufficient_scope='Learned query proposal scores, independently remeasured before recommendation; not externally annotated optimal design choices')
    (root/'am-full/evaluation.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(metrics), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--epochs', type=int, default=80)
    args = parser.parse_args()
    main(args.root.resolve(), args.epochs)
