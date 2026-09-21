"""Process-neutral cross-section measurements. No force/thermal/support model."""
from __future__ import annotations

import numpy as np
import shapely as sh

from src.core.mesh_diagnostics import inspect_mesh
from src.core.section_index import FaceZIndex
from src.core.sections import section_mesh


def inspect_cross_sections(mesh, sample_count=64, *, max_total_segments=1_500_000):
    if isinstance(sample_count,bool) or not np.isfinite(sample_count) or int(sample_count)!=sample_count or not 2<=sample_count<=1024:
        raise ValueError("단면 표본 수는 2~1,024의 정수여야 합니다.")
    result=dict(status="unknown",method="uniform_midpoint_sections/1",rows=[],
        requested_samples=int(sample_count),examined_samples=0,complete_samples=0,
        sampled_max_area_mm2=None,sampled_max_perimeter_mm=None,sampled_max_area_per_perimeter_mm=None,
        sampled_max_symmetric_change_mm2=None,volume_midpoint_estimate_mm3=None,
        scope="Finite midpoint samples of placed mesh; extrema between samples are not bounded; not layer toolpaths, peel force, suction certification or thermal simulation.")
    if not inspect_mesh(mesh)["topology_ready"]:
        result["reason"]="입력 폐곡면·면 방향이 확정되지 않아 재료 단면 집계를 보류했습니다."
        return result
    bottom,top=mesh.bounds[:,2]
    height=float(top-bottom)
    if not np.isfinite(height) or height<=0:
        result["reason"]="양의 유한한 빌드 높이가 필요합니다."
        return result
    spacing=height/sample_count
    result.update(sample_spacing_mm=spacing,covered_height_mm=[float(bottom),float(top)],
                  sample_policy="height / requested_samples, midpoint; independent of physical layer height")
    index=FaceZIndex(mesh)
    previous=None
    total_segments=0
    for i in range(int(sample_count)):
        z=float(bottom+(i+.5)*spacing)
        section=section_mesh(mesh,[0,0,z],[0,0,1],axes=np.eye(3)[:2],
            local_faces=index.sweep(z),vertex_projection=index.projection,mesh_scale_mm=index.scale_mm)
        diag=section.diagnostics
        total_segments+=diag["segment_count"]
        if total_segments>max_total_segments:
            result["reason"]="단면 선분 총량 한도에 도달했습니다. 나머지 표본은 미검토입니다."
            break
        complete=bool(diag["complete"])
        current=section.material if complete else None
        row=dict(index=i,z_mm=z,complete=complete,area_mm2=None,perimeter_mm=None,
            area_per_perimeter_mm=None,material_regions=None,internal_loops=None,
            area_change_from_previous_mm2=None,symmetric_change_from_previous_mm2=None,
            added_area_from_previous_mm2=None,removed_area_from_previous_mm2=None,
            outlines=[],outlines_complete=False,diagnostics=diag)
        if complete:
            area,perimeter=float(current.area),float(current.length)
            polygons=[p for p in sh.get_parts(current) if p.geom_type=="Polygon"]
            row.update(area_mm2=area,perimeter_mm=perimeter,
                area_per_perimeter_mm=area/perimeter if perimeter>0 else None,
                material_regions=len(polygons),internal_loops=sum(len(p.interiors) for p in polygons))
            rings=[np.asarray(r.coords).tolist() for p in polygons for r in (p.exterior,*p.interiors)]
            if sum(len(r) for r in rings)<=4096:
                row.update(outlines=rings,outlines_complete=True)
            if previous is not None:
                row.update(area_change_from_previous_mm2=area-float(previous.area),
                    symmetric_change_from_previous_mm2=float(current.symmetric_difference(previous).area),
                    added_area_from_previous_mm2=float(current.difference(previous).area),
                    removed_area_from_previous_mm2=float(previous.difference(current).area))
        previous=current
        result["rows"].append(row)
    rows=result["rows"]
    complete=[r for r in rows if r["complete"]]
    all_complete=len(rows)==sample_count and len(complete)==sample_count
    result.update(status="complete" if all_complete else "partial" if complete else "unknown",
        examined_samples=len(rows),complete_samples=len(complete),total_segments=total_segments)
    for key,source in (("sampled_max_area_mm2","area_mm2"),("sampled_max_perimeter_mm","perimeter_mm"),
        ("sampled_max_area_per_perimeter_mm","area_per_perimeter_mm"),
        ("sampled_max_symmetric_change_mm2","symmetric_change_from_previous_mm2")):
        values=[r[source] for r in rows if r[source] is not None]
        result[key]=max(values) if values else None
    if all_complete:
        result["volume_midpoint_estimate_mm3"]=sum(r["area_mm2"] for r in rows)*spacing
    if not all_complete and "reason" not in result:
        result["reason"]="닫힘·수치 정밀도 조건을 만족하지 않은 단면이 있습니다. 부분 최대값은 확정 표본에 한정됩니다."
    return result
