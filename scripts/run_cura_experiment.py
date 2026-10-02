"""Independent local Cura experiment with immutable inputs, settings and logs.

This synthetic profile does not represent the user's unselected printer. G-code
is an analysis artifact and is never transmitted to a printer.
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys
import time

import trimesh

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from amdfm.gcode import inspect_gcode
from amdfm.models import json_bytes


def flat_defaults(node):
    result={}
    for key,value in node.items():
        if value.get("type")!="category":
            result[key]={"label":value.get("label",key),"type":value.get("type","str"),
                "default_value":value.get("default_value",2. if key=="reset_flow_duration" else None)}
        result.update(flat_defaults(value.get("children",{})))
    return result


def experiment(cura_root,out):
    out.mkdir(parents=True,exist_ok=False)
    engine=cura_root/"CuraEngine.exe"
    source=cura_root/"share/cura/resources/definitions/fdmprinter.def.json"
    definitions=flat_defaults(json.loads(source.read_text(encoding="utf-8"))["settings"])
    extruder_source=source.with_name("fdmextruder.def.json")
    definitions.update(flat_defaults(json.loads(extruder_source.read_text(encoding="utf-8"))["settings"]))
    # Base definitions contain UI formulas. Freeze their published default values
    # and explicitly resolve a single extruder, rather than pretending to load a
    # named Cura GUI printer/material profile.
    for key,value in definitions.items():
        if value["type"]=="extruder":value["default_value"]=0
    settings={"machine_name":"AM-DFM synthetic CLI experiment", "machine_width":250.,"machine_depth":250.,"machine_height":250.,
        "machine_center_is_zero":True,"machine_gcode_flavor":"RepRap","material_diameter":1.75,
        "layer_height":.2,"layer_height_0":.2,"machine_nozzle_size":.4,"line_width":.4,
        "wall_line_width":.4,"wall_line_width_0":.4,"wall_line_width_x":.4,
        "min_wall_line_width":.34,"min_even_wall_line_width":.34,"min_odd_wall_line_width":.34,
        "min_bead_width":.34,"min_feature_size":.1,"wall_line_count":2,"fill_outline_gaps":True,
        "support_enable":False,"adhesion_type":"none","retraction_enable":False,"infill_sparse_density":100.,
        "machine_start_gcode":"G21\nG90\nM82\nG92 E0\nG0 X0 Y0 Z0",
        "machine_end_gcode":"","material_print_temp_prepend":False,"material_bed_temp_prepend":False,
        "roofing_layer_count":0,"flooring_layer_count":0,"speed_print":30.,"speed_wall":30.,"speed_wall_0":30.,
        "speed_wall_x":30.,"speed_topbottom":30.,"initial_layer_line_width_factor":100.,"xy_offset_layer_0":0.}
    for key,value in settings.items():definitions[key]={"label":key,"type":definitions.get(key,{}).get("type","str"),"default_value":value}
    config=out/"frozen.def.json"
    config.write_bytes(json_bytes({"version":2,"name":"AM-DFM frozen experiment","settings":definitions}))
    manifest={"engine":str(engine),"engine_sha256":hashlib.sha256(engine.read_bytes()).hexdigest(),
        "base_definition_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),"settings_sha256":hashlib.sha256(config.read_bytes()).hexdigest(),
        "extruder_definition_sha256":hashlib.sha256(extruder_source.read_bytes()).hexdigest(),
        "settings_policy":"Flattened published defaults, single extruder 0; listed overrides. Not Cura GUI resolved profile.",
        "overrides":settings,"cases":[],"physical_prints":0}
    for width in (.08,.15,.3,.6,1.2):
        case=out/f"rib_{width:g}"
        case.mkdir()
        mesh=trimesh.creation.box(extents=[20,width,10])
        mesh.apply_translation([0,0,5])
        stl=case/"input_mm.stl"
        stl.write_bytes(mesh.export(file_type="stl"))
        gcode=case/"toolpaths.gcode"
        cmd=[str(engine),"slice","-m2","-j",str(config),"-e0","-l",str(stl),"-o",str(gcode)]
        start=time.perf_counter()
        run=subprocess.run(cmd,capture_output=True,timeout=60)
        (case/"engine.log").write_bytes(run.stdout+run.stderr)
        item={"width_mm":width,"stl_sha256":hashlib.sha256(stl.read_bytes()).hexdigest(),"command":cmd,
            "exit_code":run.returncode,"seconds":time.perf_counter()-start}
        if run.returncode==0 and gcode.exists():
            parsed=inspect_gcode(gcode.read_bytes(),1.75)
            (case/"gcode_review.json").write_bytes(json_bytes(parsed))
            item.update(gcode_sha256=parsed["source_sha256"],gcode_status=parsed["status"],
                extrusion_segments=parsed["parsed_segments"],commanded_volume_mm3=parsed["total_commanded_volume_mm3"],
                geometric_volume_mm3=20*width*10)
        manifest["cases"].append(item)
        (out/"manifest.json").write_bytes(json_bytes(manifest))
        print(json.dumps(item,ensure_ascii=False),flush=True)
    manifest["complete"]=all(c["exit_code"]==0 for c in manifest["cases"])
    (out/"manifest.json").write_bytes(json_bytes(manifest))
    return manifest


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--cura",type=Path,default=Path("C:/Program Files/UltiMaker Cura 5.12.0"))
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    result=experiment(args.cura,args.out.resolve())
    raise SystemExit(0 if result["complete"] else 1)
