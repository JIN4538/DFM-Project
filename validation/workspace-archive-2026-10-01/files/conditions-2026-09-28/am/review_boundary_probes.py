import sys, json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'DFM-Project'))
from tests_v3.test_conditions import bundle
from dfm.conditions import ConditionLibrary

results=[]
for process,field,value in [('CNC','slicer','A'),('MEX','machine',['a']),('MEX','material',{'name':'a'}),('MEX','slicer',45)]:
    b=bundle(process); b['profiles'][0][field]=value
    out={'process':process,'field':field,'value':value}
    try:
        lib=ConditionLibrary([b]); out['validation']='accepted'
        try:
            p=lib.machining_profile('test-profile') if process=='CNC' else lib.am_profile('test-profile')
            out['profile']='accepted'; out['stored']=getattr(p,field)
        except Exception as exc: out['profile_error']=type(exc).__name__+': '+str(exc)
    except Exception as exc: out['validation_error']=type(exc).__name__+': '+str(exc)
    results.append(out)
for bad in [[],None,1,'not-a-record']:
    b=bundle(); b['profiles']=[bad]
    out={'bad_profile':bad}
    try: ConditionLibrary([b]); out['result']='accepted'
    except Exception as exc: out['error']=type(exc).__name__+': '+str(exc)
    results.append(out)
print(json.dumps(results,ensure_ascii=False,indent=2))
