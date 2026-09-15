"""Reproducible CAD fixtures with analytic oracles independent of the reviewer.

These are original geometric verification examples, not ISO certified artifacts.
"""
from pathlib import Path
import hashlib
import json
import math
import sys

from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeSphere
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRep import BRep_Builder
from OCP.TopoDS import TopoDS_Compound
from OCP.gp import gp_Pnt, gp_Dir, gp_Ax2
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static


def box(x,y,z,origin=(0,0,0)):
    return BRepPrimAPI_MakeBox(gp_Pnt(*origin),x,y,z).Shape()


def cylinder(r,h,origin=(0,0,0),direction=(0,0,1)):
    return BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*origin),gp_Dir(*direction)),r,h).Shape()


def cut(a,b):
    operation=BRepAlgoAPI_Cut(a,b)
    operation.Build()
    if not operation.IsDone():
        raise RuntimeError("CAD cut failed")
    return operation.Shape()


def fuse(a,b):
    operation=BRepAlgoAPI_Fuse(a,b)
    operation.Build()
    if not operation.IsDone():
        raise RuntimeError("CAD fuse failed")
    return operation.Shape()


def compound(shapes):
    result=TopoDS_Compound()
    builder=BRep_Builder()
    builder.MakeCompound(result)
    for shape in shapes:
        builder.Add(result,shape)
    return result


def export_step(shape,path,unit="MM"):
    writer=STEPControl_Writer()
    Interface_Static.SetCVal_s("write.step.unit",unit)
    Interface_Static.SetCVal_s("write.step.schema","AP214IS")
    if writer.Transfer(shape,STEPControl_AsIs)!=IFSelect_RetDone or writer.Write(str(path))!=IFSelect_RetDone:
        raise RuntimeError("STEP export failed")
    Interface_Static.SetCVal_s("write.step.unit","MM")


def generate(destination):
    if (destination/"manifest.json").exists():
        raise FileExistsError("기준형상을 보존합니다. 새 출력 폴더를 지정하세요.")
    destination.mkdir(parents=True,exist_ok=True)
    cases=[
        ("01_box", "직육면체 · 10×20×30 mm", box(10,20,30), {"volume_mm3":6000,"extents_mm":[10,20,30],"minimum_chord_mm":10}),
        ("02_thin_plate", "얇은 판 · 두께 0.3 mm", box(30,20,.3), {"volume_mm3":180,"extents_mm":[30,20,.3],"minimum_chord_mm":.3}),
        ("03_vertical_hole", "수직 관통홀 · 지름 4 mm", cut(box(20,20,10),cylinder(2,12,(10,10,-1))),
         {"volume_mm3":4000-40*math.pi,"hole_diameter_mm":4,"hole_axis":[0,0,1]}),
        ("04_horizontal_hole", "수평 관통홀 · 지름 6 mm", cut(box(30,20,20),cylinder(3,32,(-1,10,10),(1,0,0))),
         {"volume_mm3":12000-270*math.pi,"hole_diameter_mm":6,"hole_axis":[1,0,0]}),
        ("05_sealed_cavity", "밀폐 공동 · 외부 20 / 내부 16 mm",cut(box(20,20,20),box(16,16,16,(2,2,2))),
         {"volume_mm3":3904,"internal_shell_count":1}),
        ("06_open_cup", "열린 컵 · 벽과 바닥 2 mm",cut(box(20,20,20),box(16,16,20,(2,2,2))),
         {"volume_mm3":3392,"internal_shell_count":0}),
        ("07_bracket", "브래킷 · 두께 4 mm",fuse(box(40,30,4),box(4,30,36,(0,0,4))),
         {"volume_mm3":9120,"extents_mm":[40,30,40]}),
        ("08_bridge", "양끝 지지 브리지 · 지간 10 mm",fuse(fuse(box(10,5,10),box(10,5,10,(20,0,0))),box(30,5,3,(0,0,10))),
         {"volume_mm3":1450,"unsupported_horizontal_projection_mm2":50}),
        ("09_cantilever", "외팔보 · 돌출 15 mm",fuse(box(5,5,10),box(20,5,2,(0,0,10))),
         {"volume_mm3":450,"unsupported_horizontal_projection_mm2":75}),
        ("10_inch_box", "inch 선언 STEP · 실제 25.4 mm 정육면체",box(25.4,25.4,25.4),
         {"volume_mm3":25.4**3,"extents_mm":[25.4]*3,"export_unit":"INCH"}),
        ("11_two_bodies", "분리된 2개 솔리드",compound([box(10,10,10),box(10,10,10,(20,0,0))]),
         {"solid_count":2,"constituent_volume_sum_mm3":2000,"extents_mm":[30,10,10]}),
        ("12_sphere", "구 · 반지름 10 mm",BRepPrimAPI_MakeSphere(10).Shape(),
         {"volume_mm3":4/3*math.pi*1000,"exact_area_mm2":400*math.pi}),
        ("13_fine_pin", "작은 핀 · 지름 0.3 / 높이 5 mm",fuse(box(10,10,1),cylinder(.15,5,(5,5,1))),
         {"volume_mm3":100+.15**2*math.pi*5,"outer_diameter_mm":.3}),
        ("14_thin_plate_improved", "보강 판 · 두께 1.2 mm",box(30,20,1.2),
         {"volume_mm3":720,"minimum_chord_mm":1.2}),
    ]
    manifest=[]
    for name,title,shape,expected in cases:
        path=destination/(name+".step")
        export_step(shape,path,expected.get("export_unit","MM"))
        manifest.append(dict(id=name,title=title,file=path.name,source="original OCCT parametric construction",
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),expected=expected))
    (destination/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    return manifest


if __name__=="__main__":
    generate(Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[1]/"examples/cad")
