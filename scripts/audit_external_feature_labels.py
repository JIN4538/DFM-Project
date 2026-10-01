"""Whole-corpus semantic cross-checks and exact prismatic pocket remeasurement."""
import argparse,collections,hashlib,io,json,sqlite3,sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dfm.feature_learning import CLASS_NAMES
from dfm.external_features_review import pocket_dimensions

def audit(database,output):
    db=sqlite3.connect(f'file:{database.resolve()}?mode=ro',uri=True); counts=collections.Counter(); sizes={i:collections.Counter() for i in range(16)}
    axis_counts=collections.defaultdict(collections.Counter); cases=[]; signatures={}; conflicts=[]
    for identifier,split,blob,text in db.execute('SELECT id,split,graph,measurement FROM parts WHERE graph IS NOT NULL ORDER BY id'):
        with np.load(io.BytesIO(blob),allow_pickle=False) as z: y=z['y'];edges=z['edges'];x=z['x']
        g=json.loads(text);m=g['measurements'];counts.update(map(int,y));
        # Label-free geometry fingerprint sorted by invariant node attributes;
        # conservatively flags geometrically indistinguishable descriptors.
        sig=hashlib.sha256(np.array(sorted(map(tuple,np.round(x,6))),dtype='<f4').tobytes()).hexdigest()
        if sig in signatures and signatures[sig][1]!=split: conflicts.append((identifier,split,*signatures[sig]))
        else:signatures[sig]=(identifier,split)
        for i,label in enumerate(y):
            n=np.array(m[i]['normal']);axis_counts[int(label)]['axis_aligned' if np.max(np.abs(n))>1-1e-7 else 'slanted']+=1
        visited=set();verified=[]
        for i,label in enumerate(y):
            if i in visited:continue
            group={i};stack=[i];visited.add(i)
            while stack:
                k=stack.pop()
                for j in edges[edges[:,0]==k,1]:
                    j=int(j)
                    if j not in visited and y[j]==label:visited.add(j);group.add(j);stack.append(j)
            sizes[int(label)][len(group)]+=1
            if label not in (9,10,11):continue
            candidate=dict(feature=CLASS_NAMES[label],face_ids=[m[j]['face_id'] for j in sorted(group)],measured_faces=[m[j] for j in sorted(group)])
            for direction in ((0,0,1),(0,0,-1),(0,1,0),(0,-1,0),(1,0,0),(-1,0,0)):
                exact=pocket_dimensions(candidate,direction)
                if exact:verified.append(exact);break
        if verified:cases.append(dict(id=identifier,split=split,source_sha256=sig,pockets=verified))
    output.mkdir(parents=True,exist_ok=False)
    report=dict(classes=CLASS_NAMES,faces=sum(counts.values()),class_counts=dict(counts),component_sizes={i:dict(v) for i,v in sizes.items()},
        axis_orientation={i:dict(v) for i,v in axis_counts.items()},descriptor_cross_split_conflicts=conflicts,
        verified_pocket_parts=len(cases),verified_pockets=sum(len(c['pockets']) for c in cases),
        label_map_basis='Original colors.json planar-subset order + upstream issue #2 + full-corpus geometry checks; filenames excluded from model input')
    (output/'label-audit.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    (output/'pocket-cases.json').write_text(json.dumps(cases,separators=(',',':')),encoding='utf8')
    print(json.dumps(report),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--database',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();audit(a.database,a.output)
