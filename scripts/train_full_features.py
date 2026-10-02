"""Full certified corpus: semantic, instance-boundary and bottom-face learning."""
import argparse, copy, hashlib, io, json, sqlite3, sys, time
from pathlib import Path
import numpy as np
import torch
from torch import nn
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.train_external_features import GNN
from scripts.train_mfinstseg_features import NAMES
from dfm.cad_graph import FEATURES, SCHEMA
from dfm.feature_learning import CLASS_NAMES, load_model, predict_graph
from dfm.feature_localization import edge_geometry, node_geometry, components, contract_hash, predict_localization


class MultiTask(nn.Module):
    def __init__(self, original, width=64):
        super().__init__()
        self.backbone = GNN(np.array(original['mean'], dtype='float32'), np.array(original['std'], dtype='float32'))
        self.backbone.layers[-1] = nn.Linear(48, 25)
        if width != 64:
            self.backbone.layers[0] = nn.Linear(44, width)
            self.backbone.layers[1] = nn.Linear(width*2, width)
            self.backbone.layers[2] = nn.Linear(width*2, 48)
        for layer, source in zip(self.backbone.layers, original['layers']):
            weight = torch.tensor(source['weight'])
            bias = torch.tensor(source['bias'])
            if layer.weight.shape == weight.shape:
                layer.weight.data.copy_(weight)
            elif weight.shape[1] == 44:
                layer.weight.data[:len(bias)].copy_(weight)
            else:
                old_in = weight.shape[1]//2
                new_in = layer.weight.shape[1]//2
                layer.weight.data[:len(bias)].zero_()
                layer.weight.data[:len(bias), :old_in].copy_(weight[:, :old_in])
                layer.weight.data[:len(bias), new_in:new_in+old_in].copy_(weight[:, old_in:])
            layer.bias.data[:len(bias)].copy_(bias)
        self.bottom = nn.Sequential(nn.Linear(63, 32), nn.ReLU(), nn.Linear(32, 1))
        self.edge = nn.Sequential(nn.Linear(101, 64), nn.ReLU(), nn.Linear(64, 1))
        self.semantic = nn.Sequential(nn.Linear(63, 64), nn.ReLU(), nn.Linear(64, 25))
        nn.init.zeros_(self.semantic[-1].weight)
        nn.init.zeros_(self.semantic[-1].bias)

    def forward(self, x, e, geo, node_geo):
        h = (x-self.backbone.mean)/self.backbone.std
        for layer in self.backbone.layers[:3]:
            aggregate = torch.zeros_like(h)
            count = torch.zeros((len(h), 1))
            aggregate.index_add_(0, e[:, 0], h[e[:, 1]])
            count.index_add_(0, e[:, 0], torch.ones((len(e), 1)))
            h = torch.relu(layer(torch.cat([h, aggregate/count.clamp(min=1)], dim=1)))
        pair = torch.cat([(h[e[:, 0]]+h[e[:, 1]])*.5, torch.abs(h[e[:, 0]]-h[e[:, 1]]), geo], dim=1)
        enriched = torch.cat([h, node_geo], dim=1)
        return self.backbone.layers[-1](h)+self.semantic(enriched), self.bottom(enriched)[:, 0], self.edge(pair)[:, 0]


def pack(graphs):
    values = {k: [] for k in ('x', 'edges', 'y', 'geo', 'node_geo', 'bottom', 'edge_y', 'face_mask', 'edge_mask')}
    offset = 0
    for g in graphs:
        for k in values:
            values[k].append(g[k]+offset if k == 'edges' else g[k])
        offset += len(g['x'])
    return {k: torch.from_numpy(np.concatenate(v)) for k, v in values.items()}


def binary_metrics(truth, pred):
    t = np.asarray(truth, dtype=bool)
    p = np.asarray(pred, dtype=bool)
    tp, fp, fn = int((t&p).sum()), int((~t&p).sum()), int((t&~p).sum())
    return dict(precision=tp/max(tp+fp, 1), recall=tp/max(tp+fn, 1), f1=2*tp/max(2*tp+fp+fn, 1), samples=len(t))


def evaluate(model, graphs, raw=False):
    cm = np.zeros((25, 25), dtype=np.int64)
    bottoms, edges = [[], []], [[], []]
    probabilities, predictions = [], []
    model.eval()
    with torch.no_grad():
        for start in range(0, len(graphs), 128):
            subset = graphs[start:start+128]
            v = pack(subset)
            semantic, bottom, edge = model(v['x'], v['edges'], v['geo'], v['node_geo'])
            p = torch.softmax(semantic, 1).numpy()
            np.add.at(cm, (v['y'].numpy(), p.argmax(1)), 1)
            if raw:
                a, b = 0, 0
                for g in subset:
                    n, m = len(g['x']), len(g['edges'])
                    probabilities.append(p[a:a+n])
                    predictions.append(dict(bottom=torch.sigmoid(bottom[a:a+n]).numpy(), edge=torch.sigmoid(edge[b:b+m]).numpy()))
                    a += n
                    b += m
            fm, em = v['face_mask'].bool(), v['edge_mask'].bool()
            bottoms[0].extend(v['bottom'][fm].numpy())
            bottoms[1].extend(torch.sigmoid(bottom[fm]).numpy())
            edges[0].extend(v['edge_y'][em].numpy())
            edges[1].extend(torch.sigmoid(edge[em]).numpy())
    tp = cm.diagonal()
    precision = tp/np.maximum(cm.sum(0), 1)
    recall = tp/np.maximum(cm.sum(1), 1)
    f1 = 2*precision*recall/np.maximum(precision+recall, 1e-20)
    result = dict(accuracy=float(tp.sum()/max(cm.sum(), 1)), macro_f1=float(f1.mean()),
        mean_iou=float(np.mean(tp/np.maximum(cm.sum(0)+cm.sum(1)-tp, 1))), parts=len(graphs), faces=int(cm.sum()),
        per_class={n: dict(precision=float(precision[i]), recall=float(recall[i]), f1=float(f1[i]), faces=int(cm[i].sum())) for i, n in enumerate(NAMES)},
        bottom=binary_metrics(bottoms[0], np.array(bottoms[1]) >= .5), edge=binary_metrics(edges[0], np.array(edges[1]) >= .5))
    return result, probabilities, predictions, bottoms, edges


def panoptic(graphs, probabilities, predictions, edge_threshold=.5, confidence=0., legacy=False):
    tp, fp, fn, iou_sum, exact, ground_count = 0, 0, 0, 0., 0, 0
    for g, p, pred in zip(graphs, probabilities, predictions):
        truth = []
        seen = set()
        for i, label in enumerate(g['y']):
            if i in seen or label == 24:
                continue
            group = set(np.flatnonzero(g['instance_rows'][i]))
            if not group:
                group = {i}
            seen.update(group)
            truth.append((group, int(label)))
        predicted = []
        for group in components(g['edges'], pred['edge'] >= edge_threshold, len(g['x'])):
            if legacy and (np.any(p[group].max(1) < confidence) or len(set(p[group].argmax(1))) != 1):
                continue
            scores = np.log(np.maximum(p[group], 1e-12)).mean(0)
            q = np.exp(scores-scores.max())
            q /= q.sum()
            c = int(q.argmax())
            if c != 24 and q[c] >= confidence:
                predicted.append((set(group), c))
        matched = set()
        for group, c in predicted:
            options = [(len(group & t)/len(group | t), j) for j, (t, label) in enumerate(truth) if label == c and j not in matched]
            score, index = max(options, default=(0., -1))
            if score > .5:
                matched.add(index)
                tp += 1
                iou_sum += score
                exact += score == 1.
            else:
                fp += 1
        fn += len(truth)-len(matched)
        ground_count += len(truth)
    return dict(pq=iou_sum/max(tp+.5*fp+.5*fn, 1), recognition=tp/max(tp+.5*fp+.5*fn, 1),
        exact_instance_recall=exact/max(ground_count, 1), instance_precision=tp/max(tp+fp, 1),
        instance_recall=tp/max(tp+fn, 1), tp=tp, fp=fp, fn=fn, ground_truth_instances=ground_count)


def load_data(root):
    sets = {s: [] for s in ('train', 'val', 'test')}
    mf = {s: [] for s in sets}
    counts = {}
    for filename, mapping in ((root/'mfinstseg-verified.sqlite', None), (ROOT.parent/'study/external-training-2026-09-30/training.sqlite', [NAMES.index(n) for n in CLASS_NAMES])):
        db = sqlite3.connect(f'file:{filename.as_posix()}?mode=ro', uri=True)
        columns='id,split,graph'+(',measurement' if mapping is not None else '')
        for row in db.execute('SELECT '+columns+' FROM parts WHERE graph IS NOT NULL ORDER BY id'):
            identifier,split,raw=row[:3]
            with np.load(io.BytesIO(raw), allow_pickle=False) as z:
                g = {k: z[k].copy() for k in ('x', 'edges', 'y')}
                n, m = len(g['x']), len(g['edges'])
                if mapping is None:
                    geo = {k: z[k] for k in ('centroids', 'normals', 'areas', 'scale')}
                    g['geo'] = edge_geometry(dict(g, **geo))
                    g['node_geo'] = node_geometry(g['edges'], g['geo'], n)
                    g['bottom'] = z['bottom'].astype('float32')
                    inst = z['inst']
                    g['edge_y'] = inst[g['edges'][:, 0], g['edges'][:, 1]].astype('float32')
                    if split != 'train':
                        g['instance_rows'] = inst.copy()
                    g['face_mask'], g['edge_mask'] = np.ones(n, dtype=bool), np.ones(m, dtype=bool)
                    mf[split].append(g)
                else:
                    g['y'] = np.asarray(mapping, dtype=np.int64)[g['y']]
                    measurements=json.loads(row[3])
                    geometry=edge_geometry(dict(g,**measurements))
                    g.update(geo=geometry, node_geo=node_geometry(g['edges'],geometry,n), bottom=np.zeros(n, dtype='float32'), edge_y=np.zeros(m, dtype='float32'),
                        face_mask=np.zeros(n, dtype=bool), edge_mask=np.zeros(m, dtype=bool))
            g['id'] = identifier
            sets[split].append(g)
        db.close()
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeSphere
    from dfm.cad_graph import extract_graph
    negative = {s: [] for s in sets}
    rng = np.random.default_rng(20260930)
    for split, count in (('train', 1200), ('val', 150), ('test', 150)):
        for i in range(count):
            d = 10**rng.uniform(-1, 2, 3)
            shape = (BRepPrimAPI_MakeBox(*map(float, d)).Shape() if i % 3 == 0 else BRepPrimAPI_MakeCylinder(float(d[0]), float(d[1])).Shape() if i % 3 == 1 else BRepPrimAPI_MakeSphere(float(d[0])).Shape())
            graph = extract_graph(shape)
            n, m = len(graph['x']), len(graph['edges'])
            g = dict(x=graph['x'], edges=graph['edges'], y=np.full(n, 24, dtype=np.int64), geo=edge_geometry(graph), bottom=np.zeros(n, dtype='float32'),
                edge_y=np.zeros(m, dtype='float32'), face_mask=np.ones(n, dtype=bool), edge_mask=np.ones(m, dtype=bool))
            g['node_geo'] = node_geometry(g['edges'], g['geo'], n)
            negative[split].append(g)
            if split != 'test':
                sets[split].append(g)
    return sets, mf, negative


def export(model, root, base, threshold):
    out = root/'feature-models'
    out.mkdir(exist_ok=True)
    semantic = dict(base)
    semantic.update(model_id='full-corpus-multitask-features-2026-09-30', candidate_threshold=threshold,
        layers=[dict(kind='graph' if i < 3 else 'dense', weight=l.weight.detach().numpy().tolist(), bias=l.bias.detach().numpy().tolist(), activation='relu' if i < 3 else 'linear') for i, l in enumerate(model.backbone.layers)],
        target='External author face classes jointly learned with instance boundaries and bottom faces')
    path = out/'external_feature_mfinstseg_v2.json'
    raw = json.dumps(semantic, separators=(',', ':')).encode()
    path.write_bytes(raw)
    path.with_suffix('.manifest.json').write_text(json.dumps(dict(schema=semantic['schema'], sha256=hashlib.sha256(raw).hexdigest())))
    local = dict(schema='dfm-feature-localization-1', model_id='full-corpus-instance-bottom-2026-09-30',
        semantic_filename=path.name, semantic_sha256=hashlib.sha256(raw).hexdigest(), contract_sha256=contract_hash(),
        edge_threshold=.5, bottom_threshold=.5, instance_threshold=threshold,
        **{name: [dict(weight=l.weight.detach().numpy().tolist(), bias=l.bias.detach().numpy().tolist()) for l in getattr(model, name) if isinstance(l, nn.Linear)] for name in ('bottom', 'edge', 'semantic')})
    local_path = out/'external_feature_localization_v1.json'
    raw = json.dumps(local, separators=(',', ':')).encode()
    local_path.write_bytes(raw)
    local_path.with_suffix('.manifest.json').write_text(json.dumps(dict(schema=local['schema'], sha256=hashlib.sha256(raw).hexdigest())))
    return semantic, local


def main(root, epochs, width=64, initialize=None, learning_rate=.001):
    while not (root/'mfinstseg-verified-audit.json').exists() or not json.loads((root/'mfinstseg-verified-audit.json').read_text())['complete_stream']:
        time.sleep(10)
    torch.set_num_threads(3)
    torch.manual_seed(300926)
    rng = np.random.default_rng(300926)
    started = time.monotonic()
    sets, mf, negative = load_data(root)
    base = load_model(ROOT/'data/models/external_feature_mfinstseg_v1.json')
    model = MultiTask(base, width)
    if initialize is not None:
        model.load_state_dict(torch.load(initialize,weights_only=True))
    counts = np.bincount(np.concatenate([g['y'] for g in sets['train']]), minlength=25)
    criterion = nn.CrossEntropyLoss(weight=torch.tensor(np.sqrt(counts.max()/np.maximum(counts, 1)), dtype=torch.float32))
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=.0002)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='max', patience=4, factor=.5, min_lr=.00005)
    best, chosen, checkpoint = -1., 0, None
    history = []
    for epoch in range(epochs):
        model.train()
        order = rng.permutation(len(sets['train']))
        losses = []
        for start in range(0, len(order), 128):
            v = pack([sets['train'][j] for j in order[start:start+128]])
            semantic, bottom, edge = model(v['x'], v['edges'], v['geo'], v['node_geo'])
            loss = criterion(semantic, v['y'])
            fm, em = v['face_mask'].bool(), v['edge_mask'].bool()
            if fm.any():
                loss += .3*nn.functional.binary_cross_entropy_with_logits(bottom[fm], v['bottom'][fm], pos_weight=torch.tensor(3.))
            if em.any():
                loss += .3*nn.functional.binary_cross_entropy_with_logits(edge[em], v['edge_y'][em])
            optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 5.)
            optimizer.step()
            losses.append(float(loss.detach()))
        validation = evaluate(model, mf['val'])[0]
        score = validation['macro_f1']*.8 + validation['edge']['f1']*.1 + validation['bottom']['f1']*.1
        scheduler.step(score)
        row = dict(epoch=epoch+1, loss=float(np.mean(losses)), validation_score=score, validation=validation, seconds=time.monotonic()-started)
        history.append(row)
        print(json.dumps({k: v for k, v in row.items() if k != 'validation'} | dict(macro_f1=validation['macro_f1'], edge_f1=validation['edge']['f1'], bottom_f1=validation['bottom']['f1'])), flush=True)
        if score > best+1e-5:
            best, chosen, checkpoint = score, epoch+1, copy.deepcopy(model.state_dict())
            (root/'feature-models').mkdir(exist_ok=True)
            torch.save(checkpoint, root/'feature-models/best-training-state.pt')
        if epoch+1-chosen >= 15:
            break
    model.load_state_dict(checkpoint)
    validation, vp, vl, bottoms, edges = evaluate(model, mf['val'], raw=True)
    calibration = []
    # Threshold is chosen using validation only. Held-out testing comes later.
    for threshold in (.5, .6, .7, .8, .9, .95, .98, .99):
        q = panoptic(mf['val'], vp, vl, confidence=threshold)
        calibration.append(dict(threshold=threshold, **q))
    admissible = [q for q in calibration if q['instance_precision'] >= .97 and q['tp'] >= 100]
    # Preserve diagnostic outputs even if the global cutoff fails. Deployment
    # additionally requires the separate validation class/boundary calibration.
    selected = max(admissible or calibration, key=lambda q: q['pq'])
    threshold = selected['threshold']
    semantic, local = export(model, root, base, threshold)
    test, tp, tl, _, _ = evaluate(model, mf['test'], raw=True)
    parity = []
    for g in mf['test'][:25]:
        with torch.no_grad():
            a, b, c = model(torch.from_numpy(g['x']), torch.from_numpy(g['edges']), torch.from_numpy(g['geo']), torch.from_numpy(g['node_geo']))
            expected = torch.softmax(a, 1).numpy()
        with sqlite3.connect(f'file:{(root/"mfinstseg-verified.sqlite").as_posix()}?mode=ro', uri=True) as db:
            blob = db.execute('SELECT graph FROM parts WHERE id=?', (g['id'],)).fetchone()[0]
        with np.load(io.BytesIO(blob), allow_pickle=False) as z:
            original = {k: z[k].copy() for k in z.files}
        portable = predict_localization(original, local, semantic)
        parity.extend([float(np.max(np.abs(portable['semantic']-expected))),
            float(np.max(np.abs(portable['bottom']-torch.sigmoid(b).numpy()))),
            float(np.max(np.abs(portable['edge']-torch.sigmoid(c).numpy())))])
        # Stored exact CAD descriptors provide the same head feature geometry.
        # Reconstruct the normalized coordinates for portable parity separately
        # using the original certified DB instead of fabricated coordinates.
    if max(parity) > 1e-4:
        raise ValueError('Semantic portable export mismatch')
    # Previous semantic + same-class adjacency is the actual old localization.
    old_p = [predict_graph(g, base) for g in mf['test']]
    old_l = [dict(edge=((p.argmax(1)[g['edges'][:, 0]] == p.argmax(1)[g['edges'][:, 1]])
        & (p.max(1)[g['edges'][:, 0]] >= base['candidate_threshold'])
        & (p.max(1)[g['edges'][:, 1]] >= base['candidate_threshold'])).astype(float)) for g, p in zip(mf['test'], old_p)]
    summary = dict(counts={s: len(mf[s]) for s in mf}, mixed_counts={s: len(sets[s]) for s in sets},
        validation=validation, calibration=calibration, chosen_threshold=threshold, selected_epoch=chosen,
        test=test, new_panoptic=panoptic(mf['test'], tp, tl, confidence=threshold),
        old_panoptic=panoptic(mf['test'], old_p, old_l, confidence=base['candidate_threshold'], legacy=True),
        stock_negative_test=evaluate(model, negative['test'])[0], mixed_test=evaluate(model, sets['test'])[0],
        portable_max_error=max(parity), history=history, seconds=time.monotonic()-started,
        split='Same feature-multiset hash family holdouts as previous corpus; no random view leakage',
        targets='External feature semantic, instance membership and bottom labels; construction stock negatives separate')
    summary.update(global_precision_gate=bool(admissible),initialization=str(initialize) if initialize else None,
        actual_mfcad_aux_geometry=True,learning_rate=learning_rate)
    (root/'feature-models/evaluation.json').write_text(json.dumps(summary, indent=2), encoding='utf8')
    print(json.dumps({k: v for k, v in summary.items() if k not in ('history', 'validation', 'test', 'mixed_test', 'stock_negative_test')}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--epochs', type=int, default=100)
    parser.add_argument('--width', type=int, choices=[64, 128], default=64)
    parser.add_argument('--initialize',type=Path)
    parser.add_argument('--learning-rate',type=float,default=.001)
    args = parser.parse_args()
    main(args.root.resolve(), args.epochs, args.width,args.initialize,args.learning_rate)
