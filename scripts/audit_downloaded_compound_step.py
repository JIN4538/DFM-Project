"""Audit the actual browser-downloaded example with analytic polygon volumes."""
from pathlib import Path
import sys
import hashlib
import json
import math
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dfm.cad_edit_pairs import read_shape,bounds,unique
from OCP.TopAbs import TopAbs_FACE
from OCP.TopoDS import TopoDS
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Cylinder
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp

path=Path(sys.argv[1]);output=Path(sys.argv[2])
if output.exists():raise ValueError('Preserve previous audit')
shape=read_shape(path)
sides_depths=((3,5),(4,7),(6,4))
before=90*60*20-sum(n*.5*9**2*math.sin(2*math.pi/n)*depth for n,depth in sides_depths)
addition=sum((n/math.tan(math.pi*(n-2)/(2*n))-math.pi)*3.6**2*depth for n,depth in sides_depths)
props=GProp_GProps();BRepGProp.VolumeProperties_s(shape,props)
radii=[]
for face in unique(shape,TopAbs_FACE):
    surface=BRepAdaptor_Surface(TopoDS.Face_s(face))
    if surface.GetType()==GeomAbs_Cylinder:radii.append(surface.Cylinder().Radius())
valid=(len(radii)==13 and all(math.isclose(r,3.6,abs_tol=1e-7) for r in radii)
    and math.isclose(props.Mass(),before+addition,abs_tol=1e-6)
    and np.allclose(bounds(shape),[0,0,0,90,60,20],atol=1e-7))
result=dict(file=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    cylindrical_corner_faces=len(radii),corner_radii_mm=radii,measured_volume_mm3=props.Mass(),
    expected_volume_mm3=before+addition,expected_material_addition_mm3=addition,
    bounds_mm=bounds(shape).tolist(),passed=valid,
    scope='Actual native-browser download; valid single solid; independent analytic three-polygon volume and fixed outer dimensions')
output.write_text(json.dumps(result,indent=2),encoding='utf8');print(json.dumps(result))
if not valid:raise ValueError('Downloaded shape failed independent verification')
