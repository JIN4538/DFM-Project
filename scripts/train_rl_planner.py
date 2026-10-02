"""Reproducible Double-DQN learning in an explicit CNC dimension environment.

No labels from a teacher's chosen actions: targets use reward + discounted
target-network estimates after transitions. Validation selects checkpoints;
test families/seeds are read once after that selection.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from dfm.rl_planner import (SCHEMA, FEATURE_COUNT, MAX_STEPS, _source_hash, make_problem, action_space, transition,
    action_vectors, network_predict, rollout, quality, plan_from_state, evaluate_changes, conflicts)


class Network:
    """Two ReLU hidden layers, Adam, Huber TD loss, clipped gradient norm."""
    def __init__(self, rng, widths=(64, 32)):
        dims = [FEATURE_COUNT, *widths, 1]
        self.layers = [dict(weights=rng.normal(0, np.sqrt(2/a), (a,b)), bias=np.zeros(b)) for a,b in zip(dims, dims[1:])]
        self.m = [[np.zeros_like(layer[k]) for k in ("weights", "bias")] for layer in self.layers]
        self.v = deepcopy(self.m)
        self.t = 0

    def predict(self, x):
        return network_predict(dict(layers=self.layers), x)

    def train(self, x, target, learning_rate=.0007):
        activations = [x]
        pre = []
        for i, layer in enumerate(self.layers):
            z = activations[-1] @ layer["weights"] + layer["bias"]
            pre.append(z)
            activations.append(np.maximum(z, 0) if i < len(self.layers)-1 else z)
        diff = activations[-1].reshape(-1) - target
        grad = (np.clip(diff, -1., 1.) / len(x)).reshape(-1, 1)
        grads = []
        for i in range(len(self.layers)-1, -1, -1):
            grads.append([activations[i].T @ grad, grad.sum(axis=0)])
            grad = grad @ self.layers[i]["weights"].T
            if i > 0:
                grad *= pre[i-1] > 0
        grads.reverse()
        norm = np.sqrt(sum(float(np.sum(g*g)) for pair in grads for g in pair))
        if norm > 10:
            grads = [[g * 10/norm for g in pair] for pair in grads]
        self.t += 1
        for i, pair in enumerate(grads):
            for j, key in enumerate(("weights", "bias")):
                g = pair[j]
                self.m[i][j] = .9 * self.m[i][j] + .1 * g
                self.v[i][j] = .999 * self.v[i][j] + .001 * g*g
                mh = self.m[i][j] / (1-.9**self.t)
                vh = self.v[i][j] / (1-.999**self.t)
                self.layers[i][key] -= learning_rate * mh / (np.sqrt(vh) + 1e-8)
        return float(np.mean(np.where(np.abs(diff) <= 1., .5*diff*diff, np.abs(diff)-.5)))

    def export(self):
        return [dict(weights=l["weights"].tolist(), bias=l["bias"].tolist()) for l in self.layers]


def scenario(seed, family, index):
    rng = np.random.default_rng(seed + family*100003 + index*997)
    scale = 10**rng.uniform(-.5, 1.5)
    counts = ((2,0,0), (0,3,0), (0,0,2), (2,1,1), (3,2,2), (5,3,3), (1,4,5))[family]
    holes = [dict(face_id=i+10, diameter_mm=scale*rng.uniform(.4,2), cylindrical_length_mm=scale*rng.uniform(.3,10), axis_aligned=True) for i in range(counts[0])]
    corners = [dict(face_id=i+30, radius_mm=scale*rng.uniform(.12,1.1)) for i in range(counts[1])]
    pockets = [dict(floor_face_id=i+50, width_mm=scale*rng.uniform(.4,2.5), wall_height_mm=scale*rng.uniform(.3,8)) for i in range(counts[2])]
    flute = scale*rng.uniform(.5,3)
    profile = dict(tool_diameter_mm=scale*rng.uniform(.4,2.8), flute_length_mm=flute, reach_mm=flute*rng.uniform(1,2), hole_depth_ratio_limit=[None,2.,4.,8.][index%4])
    report = dict(process="MILLING_3AXIS", profile=profile, review_context={"priority": ("balanced","accuracy","tool_access")[index%3]}, findings=[
        dict(id="cnc_input", status="observed", measurements={"cad_feature_dimensions_available":True}),
        dict(id="cnc_holes", status="attention" if holes else "not_detected", measurements={"cylindrical_faces":holes}),
        dict(id="cnc_curved_corners", status="attention" if corners else "not_detected", measurements={"cylindrical_faces":corners}),
        dict(id="cnc_rectangular_pockets", status="attention" if pockets else "not_detected", measurements={"pockets":pockets})])
    # All nine priority/permission pairs appear; locks do not encode priority.
    prefs = ({}, {"preserve_geometry":True}, {"allow_tool_change":False})[(index//3)%3]
    return dict(id=f"{seed}-{family}-{index}", family=family, report=report, preferences=prefs, seed=seed)


def legacy_quality(item):
    from dfm.plan_learning import candidate_plans
    plans, _, _ = candidate_plans(item["report"], item["preferences"])
    values=[]
    for p in plans:
        try:
            result = evaluate_changes(item["report"], p["changes"], preferences=item["preferences"])
            values.append(((result["conflicts"],round(result["cost"],12)),p))
        except ValueError:
            continue
    return min(values,key=lambda p:p[0]) if values else (None,None)


def external_scenarios(cases):
    """One reproducible counterfactual per exact external CAD measurement.

    Tool settings are generated review conditions, not source metadata. All
    feature-multiset family splits are retained, including for every revisit.
    """
    result = {'train': [], 'val': [], 'test': []}
    for case in cases:
        pockets = case['pockets']
        if not pockets:
            continue
        width = min(p.get('entry_circle_diameter_mm', p['width_mm']) for p in pockets)
        depth = max(p['wall_height_mm'] for p in pockets)
        token = int(hashlib.sha256(case['id'].encode()).hexdigest()[:8], 16)
        tool = width*(.6 if token % 2 else 1.2)
        flute = depth*(.65 if token % 3 else 1.1)
        reach = max(flute, depth*(.8 if token % 5 else 1.2))
        report = dict(process='MILLING_3AXIS', profile=dict(tool_diameter_mm=tool, flute_length_mm=flute, reach_mm=reach, hole_depth_ratio_limit=None),
            review_context={'priority': ('balanced', 'accuracy', 'tool_access')[token % 3]}, findings=[
                dict(id='cnc_input', status='observed', measurements={'cad_feature_dimensions_available': True}),
                dict(id='cnc_rectangular_pockets', status='attention', measurements={'pockets': [p for p in pockets if p['feature'] == 'rectangular_pocket']}),
                dict(id='cnc_learned_pockets', status='attention', measurements={'pockets': [p for p in pockets if p['feature'] != 'rectangular_pocket']})])
        prefs = ({}, {'preserve_geometry': True}, {'allow_tool_change': False})[(token//3) % 3]
        item = dict(id='external-'+case['id'], family=token % 7, report=report, preferences=prefs, seed=token,
            original_group=case.get('group_id'), source='Exact MFInstSeg CAD prism remeasurement')
        make_problem(report, prefs)
        result[case['split']].append(item)
    return result


def evaluate(items, model, *, comparisons=False, random_model=None):
    records=[]
    started=time.perf_counter()
    for item in items:
        problem=make_problem(item["report"],item["preferences"])
        state,steps=rollout(problem,model)
        q=quality(problem,state)
        record=dict(id=item["id"],family=item["family"],rl_quality=list(q),steps=len(steps),initial_conflicts=len(conflicts(problem,problem["initial"])))
        if comparisons:
            greedy,_=rollout(problem,policy="greedy")
            random,_=rollout(problem,policy="random",rng=np.random.default_rng(item["seed"]+item["family"]))
            legacy, legacy_plan=legacy_quality(item)
            record.update(greedy_quality=list(quality(problem,greedy)), random_quality=list(quality(problem,random)), legacy_quality=list(legacy) if legacy else None,
                          rl_changes=plan_from_state(problem,state,steps)["changes"],legacy_changes=legacy_plan["changes"] if legacy_plan else None)
            if random_model:
                untrained,_=rollout(problem,random_model)
                record["untrained_quality"]=list(quality(problem,untrained))
        records.append(record)
    summary=dict(count=len(records),mean_conflicts=float(np.mean([r["rl_quality"][0] for r in records])),mean_cost=float(np.mean([r["rl_quality"][1] for r in records])),
                 zero_conflict=sum(r["rl_quality"][0]==0 for r in records),mean_steps=float(np.mean([r["steps"] for r in records])),elapsed_seconds=time.perf_counter()-started)
    if comparisons:
        for name in ("greedy","random","legacy","untrained"):
            pairs=[(tuple(r["rl_quality"]),tuple(r[name+"_quality"])) for r in records if r.get(name+"_quality") is not None]
            summary[name]=dict(count=len(pairs),rl_better=sum(a<b for a,b in pairs),rl_worse=sum(a>b for a,b in pairs),equal=sum(a==b for a,b in pairs),
                               baseline_mean_conflicts=float(np.mean([b[0] for a,b in pairs])) if pairs else None,
                               baseline_mean_cost=float(np.mean([b[1] for a,b in pairs])) if pairs else None)
        guarded=[(min(tuple(r["rl_quality"]),tuple(r["legacy_quality"])),tuple(r["legacy_quality"])) for r in records if r.get("legacy_quality")]
        summary["theoretical_exact_min_guard"]=dict(worse=sum(a>b for a,b in guarded),selected_rl=sum(a<b for a,b in guarded),
            scope="pointwise minimum of stored raw qualities; not a runtime arbitration test")
    return dict(summary=summary,records=records)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--episodes",type=int,default=4000)
    parser.add_argument("--seed",type=int,default=2026092917)
    parser.add_argument("--test-count",type=int,default=80)
    parser.add_argument("--initialize-from",type=Path)
    parser.add_argument("--external-cases", type=Path)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    source_at_start=_source_hash()
    script_at_start=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    source_files=(Path(__file__),ROOT/"dfm/rl_planner.py",ROOT/"dfm/machining.py",ROOT/"dfm/plan_learning.py")
    file_hashes_at_start={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
    def verify_frozen_sources():
        current={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
        if current != file_hashes_at_start or _source_hash()!=source_at_start:
            raise RuntimeError("Training sources changed; do not publish this run")
    rng=np.random.default_rng(args.seed)
    train=[scenario(args.seed, f, i) for f in range(5) for i in range(120)]
    validation=[scenario(args.seed+1700000, f, i) for f in range(5) for i in range(16)]
    test=[scenario(args.seed+7100000, f, i) for f in range(7) for i in range(args.test_count)]
    external_counts = None
    if args.external_cases:
        external = external_scenarios(json.loads(args.external_cases.read_text(encoding='utf8')))
        external_counts = {s: len(v) for s, v in external.items()}
        train.extend(external['train'])
        # Deterministic validation subset bounds checkpoint-evaluation cost;
        # every external test part is retained for the final frozen check.
        validation.extend(sorted(external['val'], key=lambda r: hashlib.sha256(r['id'].encode()).hexdigest())[:1000])
        test.extend(external['test'])
        args.episodes = max(args.episodes, len(train)+8000)
    with gzip.open(args.output/"scenario-split.json.gz","wt",encoding="utf-8") as f:
        json.dump(dict(train=train,validation=validation,test=test,heldout_families=[5,6]),f,ensure_ascii=False)
    net=Network(rng)
    untrained=dict(layers=deepcopy(net.layers))
    initialization=None
    if args.initialize_from:
        initial_raw=args.initialize_from.read_bytes()
        initial=json.loads(initial_raw)
        if initial.get("schema")!=SCHEMA or initial.get("feature_count")!=FEATURE_COUNT:
            raise ValueError("초기 학습망의 특징 계약이 다릅니다")
        for trained,new in zip(initial["layers"],net.layers):
            if np.asarray(trained["weights"]).shape != new["weights"].shape:
                raise ValueError("초기 학습망의 층 크기가 다릅니다")
        net.layers=[dict(weights=np.asarray(l["weights"],dtype=float),bias=np.asarray(l["bias"],dtype=float)) for l in initial["layers"]]
        initialization=dict(model_sha256=hashlib.sha256(initial_raw).hexdigest(),path=args.initialize_from.as_posix(),
                            previous_training=initial["training"],note="continued network weights; fresh Adam, replay and scenario groups")
    target=dict(layers=deepcopy(net.layers))
    replay=[]
    capacity=20000
    cursor=0
    updates=0
    steps_seen=0
    history=[]
    visited = set()
    visit_order = rng.permutation(len(train))
    best_key=(float("inf"),float("inf"))
    best_layers=None
    best_episode=0
    started=time.perf_counter()
    (args.output/"preregistered-run.json").write_text(json.dumps(dict(seed=args.seed,episodes=args.episodes,test_count=args.test_count,source_files=file_hashes_at_start,
        source_sha256=source_at_start,initialization=initialization,selection="validation mean conflicts then mean cost; no test checkpoint selection",heldout_families=[5,6]),indent=2),encoding="utf-8")
    for episode in range(args.episodes):
        if episode % len(train) == 0:
            visit_order = rng.permutation(len(train))
        item=train[int(visit_order[episode % len(train)])]
        visited.add(item['id'])
        problem=make_problem(item["report"],item["preferences"])
        state=deepcopy(problem["initial"])
        epsilon=max(.08,(.35 if initialization else 1.)*(1-episode/(args.episodes*.7)))
        for step in range(MAX_STEPS):
            choices=action_space(problem,state)
            if len(choices)<=1: break
            features=action_vectors(problem,state,choices,MAX_STEPS-step)
            action_index=int(rng.integers(len(choices))) if rng.random()<epsilon else int(np.argmax(net.predict(features)))
            after,reward,done=transition(problem,state,choices[action_index])
            next_choices=action_space(problem,after)
            done=done or step==MAX_STEPS-1 or len(next_choices)<=1
            next_features=np.zeros((0,FEATURE_COUNT)) if done else action_vectors(problem,after,next_choices,MAX_STEPS-step-1)
            row=(features[action_index],reward,next_features)
            if len(replay)<capacity: replay.append(row)
            else:
                replay[cursor]=row
                cursor=(cursor+1)%capacity
            steps_seen+=1
            if len(replay)>=128 and steps_seen%4==0:
                batch=[replay[i] for i in rng.integers(len(replay),size=96)]
                x=np.stack([b[0] for b in batch])
                y=np.asarray([b[1] for b in batch])
                active=[i for i,b in enumerate(batch) if len(b[2])]
                if active:
                    all_next=np.concatenate([batch[i][2] for i in active])
                    online=net.predict(all_next)
                    frozen=network_predict(target,all_next)
                    offset=0
                    for i in active:
                        n=len(batch[i][2])
                        selected=int(np.argmax(online[offset:offset+n]))
                        y[i]+=frozen[offset+selected]
                        offset+=n
                loss=net.train(x,y)
                updates+=1
                if updates%100==0: target=dict(layers=deepcopy(net.layers))
            state=after
            if done: break
        if (episode+1)%(2000 if args.external_cases else 500)==0 or episode==args.episodes-1:
            verify_frozen_sources()
            score=evaluate(validation,dict(layers=net.layers))["summary"]
            score.update(episode=episode+1,updates=updates,transitions=steps_seen,epsilon=epsilon)
            history.append(score)
            key=(score["mean_conflicts"],score["mean_cost"])
            if key<best_key:
                best_key=key
                best_layers=deepcopy(net.layers)
                best_episode=episode+1
            print(json.dumps(score),flush=True)
            (args.output/"training-progress.json").write_text(json.dumps(history,indent=2),encoding="utf-8")
    net.layers=best_layers
    verify_frozen_sources()
    model=dict(schema=SCHEMA,feature_count=FEATURE_COUNT,source_sha256=source_at_start,layers=net.export(),
               training=dict(method="Double DQN",hidden_layers=[64,32],seed=args.seed,episodes=args.episodes,transitions=steps_seen,gradient_updates=updates,
                             experience_replay_capacity=capacity,batch_size=96,target_sync_updates=100,gamma=1.,best_validation_episode=best_episode,
                             training_scenarios=len(train),validation_scenarios=len(validation),heldout_families=[5,6],
                             external_counts=external_counts, actually_visited_training_scenarios=len(visited),
                             external_training_visited=sum(identifier.startswith('external-') for identifier in visited),
                             initialization=initialization,
                             reward="2*(conflicts_before-conflicts_after) - (policy_cost_after-policy_cost_before); finite-horizon undiscounted return",action_labels=False))
    result=evaluate(test,model,comparisons=True,random_model=untrained)
    verify_frozen_sources()
    model["validation"]={"kind":"Exact external CAD dimension counterfactuals plus procedural feature scenarios" if args.external_cases else "fresh procedural feature-dimension scenarios; not imported CAD",**result["summary"]}
    model["created_utc"]=datetime.now(timezone.utc).isoformat()
    model["training"]["elapsed_seconds"]=time.perf_counter()-started
    raw=json.dumps(model,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
    (args.output/"rl_planner_v1.json").write_bytes(raw)
    (args.output/"test-evaluation.json").write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False),encoding="utf-8")
    manifest=dict(model_sha256=hashlib.sha256(raw).hexdigest(),source_sha256=source_at_start,training_script_sha256=script_at_start,source_files=file_hashes_at_start,
                  frozen_sources_verified=True,
                  scenario_sha256=hashlib.sha256((args.output/"scenario-split.json.gz").read_bytes()).hexdigest(),**model["training"])
    (args.output/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    (args.output/"rl_planner_v1.manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print(json.dumps(result["summary"]),flush=True)


if __name__=="__main__":
    main()
