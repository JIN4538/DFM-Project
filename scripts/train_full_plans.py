"""Bounded-memory learning of public CAD counterfactual change priorities."""
import argparse, hashlib, json, sqlite3, sys, time
from pathlib import Path
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dfm.plan_learning import FEATURES, SCHEMA, source_hashes, candidate_plans, _stable, predict_score
from scripts.train_plan_model import selection_objective, am_reports, cnc_reports
from scripts.train_external_plans import external_reports


def portable_predict(model, x):
    x = np.asarray(x, dtype='float32')
    values = np.full(len(x), model['intercept'], dtype=float)
    for tree in model['trees']:
        nodes = np.asarray(tree, dtype=float)
        current = np.zeros(len(x), dtype=int)
        for _ in range(len(nodes)):
            rows = nodes[current]
            active = rows[:, 0] != -2
            if not active.any():
                break
            r = rows[active]
            branch = x[active, r[:, 0].astype(int)] <= r[:, 1]
            current[active] = np.where(branch, r[:, 2], r[:, 3]).astype(int)
        values += model['learning_rate']*nodes[current, 4]
    return values


def score(db, split, prediction, external=False):
    totals = dict(queries=0, exact_objective_best=0, mean_objective_regret=0., maximum_objective_regret=0.,
        baseline_mean_objective_regret=0., different_from_fixed_baseline=0, better_than_fixed_objective=0,
        worse_than_fixed_objective=0)
    cursor = db.execute('SELECT payload FROM queries WHERE split=?'+(' AND external=1' if external else ''), (split,))
    while rows := cursor.fetchmany(512):
        queries = [json.loads(row[0]) for row in rows]
        x = np.asarray([f for q in queries for f in q['features']], dtype='float32')
        predicted = prediction(x)
        offset = 0
        for q in queries:
            values = predicted[offset:offset+len(q['features'])]
            offset += len(values)
            best = min(range(len(values)), key=lambda i: (-round(float(values[i]), 9), q['stable_keys'][i]))
            oracle = max(q['targets'])
            regret = oracle-q['targets'][best]
            old = oracle-q['targets'][q['baseline_index']]
            totals['queries'] += 1
            totals['exact_objective_best'] += regret <= 1e-7
            totals['mean_objective_regret'] += regret
            totals['maximum_objective_regret'] = max(totals['maximum_objective_regret'], regret)
            totals['baseline_mean_objective_regret'] += old
            totals['different_from_fixed_baseline'] += best != q['baseline_index']
            totals['better_than_fixed_objective'] += regret < old-1e-7
            totals['worse_than_fixed_objective'] += regret > old+1e-7
    for key in ('mean_objective_regret', 'baseline_mean_objective_regret'):
        totals[key] /= max(totals['queries'], 1)
    return totals


def export(fit, hashes):
    trees = []
    for stage in fit._predictors:
        rows = []
        for n in stage[0].nodes:
            if n['is_categorical']:
                raise ValueError('Categorical trees are outside portable contract')
            rows.append([-2, 0., -1, -1, float(n['value'])] if n['is_leaf'] else
                [int(n['feature_idx']), float(n['num_threshold']), int(n['left']), int(n['right']), float(n['value'])])
        trees.append(rows)
    return dict(schema=SCHEMA, id='external-cad-full-plan-ranker-v3', features=list(FEATURES), sources=hashes,
        training_scope='Independent CAD triangle/rectangle/hexagon prism dimensions; counterfactual targets are disclosed project trade-off policy, not external expert improvement labels.',
        intercept=float(fit._baseline_prediction[0, 0]), learning_rate=1., trees=trees)


def main(args):
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    hashes = source_hashes()
    db = sqlite3.connect(args.output/'queries.sqlite')
    db.execute('CREATE TABLE queries (split TEXT, group_id TEXT, external INTEGER, count INTEGER, payload TEXT)')
    counts = dict(train=0, validation=0, test=0)
    external_counts = dict(counts)
    groups = {s: set() for s in counts}
    query_counts = dict(counts)

    def add(iterator, external):
        for row in iterator:
            group, split, report = row[:3]
            plans, _, baseline = candidate_plans(report, report.get('_training_preferences'))
            if len(plans) < 2:
                continue
            features = [p['_features'] for p in plans]
            q = dict(features=features, targets=[selection_objective(x) for x in features],
                stable_keys=[_stable(p) for p in plans], baseline_index=next((i for i, p in enumerate(plans) if p['id']==baseline), 0))
            db.execute('INSERT INTO queries VALUES (?,?,?,?,?)', (split, group, int(external), len(plans), json.dumps(q, separators=(',', ':'))))
            counts[split] += len(plans)
            external_counts[split] += external*len(plans)
            query_counts[split] += 1
            groups[split].add(group)
            if sum(query_counts.values()) % 5000 == 0:
                db.commit()
                print('Prepared', query_counts, flush=True)

    for path in args.cases:
        cases = json.loads(path.read_text(encoding='utf8'))
        source = 'MFInstSeg' if 'full' in path.name else 'MFCAD'
        for c in cases:
            c['group_id'] = source+'-'+c.get('group_id', c['id'])
        add(external_reports(cases), True)
        del cases
    add(am_reports(300930), False)
    add(cnc_reports(300930), False)
    db.commit()
    if any(groups[a] & groups[b] for a, b in (('train','validation'),('train','test'),('validation','test'))):
        raise ValueError('Cross-split family group leakage')
    x = np.lib.format.open_memmap(args.output/'train-x.npy', mode='w+', dtype='float32', shape=(counts['train'], len(FEATURES)))
    y = np.lib.format.open_memmap(args.output/'train-y.npy', mode='w+', dtype='float32', shape=(counts['train'],))
    offset = 0
    for (raw,) in db.execute("SELECT payload FROM queries WHERE split='train'"):
        q = json.loads(raw)
        n = len(q['features'])
        x[offset:offset+n], y[offset:offset+n] = q['features'], q['targets']
        offset += n
    x.flush(); y.flush()
    selections, models = {}, {}
    for trees, leaves in ((180, 15), (300, 31)):
        fit = HistGradientBoostingRegressor(max_iter=trees, max_leaf_nodes=leaves, learning_rate=.06,
            min_samples_leaf=20, early_stopping=False, random_state=300930).fit(x, y)
        key = f'{trees}-leaves-{leaves}'
        selections[key] = score(db, 'validation', fit.predict)
        models[key] = fit
        print(key, selections[key], flush=True)
    chosen = min(selections, key=lambda k: selections[k]['mean_objective_regret'])
    fit = models[chosen]
    model = export(fit, hashes)
    error = float(np.max(np.abs(fit.predict(x[:8192])-portable_predict(model, x[:8192]))))
    scalar_error = max(abs(predict_score(model, row)-float(pred)) for row, pred in zip(x[:20], fit.predict(x[:20])))
    if max(error, scalar_error) > 1e-6:
        raise ValueError('Portable plan export mismatch')
    raw = args.baseline.read_bytes()
    old_meta = json.loads(args.baseline.with_suffix('.manifest.json').read_text(encoding='utf8'))
    if hashlib.sha256(raw).hexdigest() != old_meta['sha256']:
        raise ValueError('Frozen baseline checksum mismatch')
    old = json.loads(raw)
    summary = dict(selection=selections, selected=chosen, all_heldout=score(db, 'test', fit.predict),
        external_new=score(db, 'test', fit.predict, True), external_old=score(db, 'test', lambda z: portable_predict(old, z), True),
        candidate_rows=counts, query_counts=query_counts, external_candidate_rows=external_counts,
        groups={s: len(g) for s, g in groups.items()}, cross_split_group_overlap=0,
        portable_max_error=max(error, scalar_error), seconds=time.monotonic()-started,
        target_definition='Disclosed geometric change-priority policy; source datasets do not contain expert improvement labels')
    model.update(training_rows=counts['train'], training_groups=len(groups['train']), seed=300930,
        algorithm=chosen, training_pipeline_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        external_source=dict(cases=[dict(path=p.name, sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in args.cases],
            source='hducg/MFCAD MIT and whjdark/AAGNet MFInstSeg MIT', measurement='Exact CAD planes, vertices and independently solved entry circles'))
    if source_hashes() != hashes:
        raise ValueError('Source changed while training')
    raw = json.dumps(model, separators=(',', ':'), allow_nan=False).encode()
    path = args.output/'plan_ranker_external_v3.json'
    path.write_bytes(raw)
    path.with_suffix('.manifest.json').write_text(json.dumps(dict(schema=SCHEMA, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))))
    (args.output/'evaluation.json').write_text(json.dumps(summary, indent=2), encoding='utf8')
    print(json.dumps(summary), flush=True)
    db.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--cases', nargs='+', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--baseline', type=Path, required=True)
    main(p.parse_args())
