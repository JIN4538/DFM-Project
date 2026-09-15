"""Read-only, bounded G0/G1 extrusion inspection; never executes machine code.

Amounts are commanded filament movement, not measured deposition or print success.
Unsupported motion/extrusion modes invalidate totals instead of understating them.
"""
from __future__ import annotations
from collections import defaultdict
import hashlib
import math
import re

WORDS=re.compile(r"([A-Za-z])([-+]?(?:\d+\.?\d*|\.\d+))")


def inspect_gcode(data:bytes,filament_diameter_mm:float,*,max_segments=300_000):
    if not 0 < filament_diameter_mm < 10 or not math.isfinite(filament_diameter_mm):
        raise ValueError("필라멘트 지름을 유한한 mm 값으로 입력하세요.")
    if len(data)>60*1024*1024:
        raise ValueError("G-code는 60 MiB까지 읽을 수 있습니다.")
    lines=data.decode("utf-8-sig",errors="replace").splitlines()
    position={k:None for k in "XYZ"}
    extrusion=0.
    absolute_xyz=True
    absolute_e=True
    unit=1.
    debt=0.
    feature="UNSPECIFIED"
    segments=[]
    issues=[]
    unsupported=set()
    totals=defaultdict(lambda:{"filament_mm":0.,"path_mm":0.,"segments":0})
    declared_time=None
    def invalidate(message):
        if message not in issues:issues.append(message)
    for number,line in enumerate(lines,1):
        if line.startswith(";TYPE:"):feature=line[6:].strip()
        if line.startswith(";TIME:"):
            try:declared_time=float(line[6:].strip())
            except ValueError:pass
        code=line.partition(";")[0].strip()
        code=re.sub(r"\([^)]*\)","",code)
        if not code:continue
        words=WORDS.findall(code.upper())
        if not words:continue
        if words[0][0]=="N":words=words[1:]
        if not words:continue
        letter,command=words[0]
        if not math.isfinite(float(command)) or float(command)!=int(float(command)):
            invalidate("지원하지 않는 소수 하위 명령: "+letter+command)
            unsupported.add(letter+command)
            continue
        cmd=letter+str(int(float(command)))
        if any(k in ("G","M","T") for k,v in words[1:]):
            invalidate("한 줄에 여러 명령이 있어 해석하지 않았습니다.")
            continue
        args={k:float(v) for k,v in words[1:]}
        if not all(math.isfinite(v) for v in args.values()):
            invalidate("비유한 수치");break
        if cmd=="G20":unit=25.4;continue
        if cmd=="G21":unit=1.;continue
        if cmd=="G90":absolute_xyz=True;absolute_e=True;continue
        if cmd=="G91":absolute_xyz=False;absolute_e=False;continue
        if cmd=="M82":absolute_e=True;continue
        if cmd=="M83":absolute_e=False;continue
        if cmd=="G92":
            for k in "XYZ":
                if k in args:position[k]=args[k]*unit
            if "E" in args:extrusion=args["E"]*unit
            continue
        if cmd=="G28":
            position={k:None for k in "XYZ"}
            continue
        if cmd in ("G2","G3","G5","G10","G11","M200","M221") or (letter=="T" and float(command)!=0):
            unsupported.add(cmd)
            invalidate("지원하지 않는 동작·압출 모드: "+cmd)
            continue
        if cmd not in ("G0","G1"):
            if letter=="G" and cmd not in ("G4","G29"):
                unsupported.add(cmd);invalidate("지원하지 않는 좌표/동작 명령: "+cmd)
            continue
        before=position.copy()
        for k in "XYZ":
            if k in args:
                position[k]=(args[k]*unit if absolute_xyz else (position[k]+args[k]*unit if position[k] is not None else None))
        delta_e=0.
        if "E" in args:
            next_e=args["E"]*unit if absolute_e else extrusion+args["E"]*unit
            delta_e=next_e-extrusion
            extrusion=next_e
        if delta_e<0:
            debt-=delta_e
            continue
        deposited=max(0.,delta_e-debt)
        debt=max(0.,debt-delta_e)
        if deposited<=1e-10:continue
        if any(v is None for v in list(before.values())+list(position.values())):
            invalidate("위치가 확인되기 전의 압출 명령")
            continue
        length=math.dist([before[k] for k in "XYZ"],[position[k] for k in "XYZ"])
        if length<1e-8:continue  # stationary priming is not a deposited path
        if len(segments)>=max_segments:
            invalidate("경로 구간 수 한도 초과");break
        segment={"start":[before[k] for k in "XYZ"],"end":[position[k] for k in "XYZ"],
                 "filament_mm":deposited,"length_mm":length,"type":feature,"line":number}
        segments.append(segment)
        total=totals[feature]
        total["filament_mm"]+=deposited
        total["path_mm"]+=length
        total["segments"]+=1
    factor=math.pi*(filament_diameter_mm/2)**2
    for row in totals.values():row["commanded_volume_mm3"]=row["filament_mm"]*factor
    status="partial" if issues else "parsed"
    return {"schema":"amdfm-gcode/1.0","status":status,"source_sha256":hashlib.sha256(data).hexdigest(),
        "filament_diameter_mm":filament_diameter_mm,"issues":issues,"unsupported_commands":sorted(unsupported),
        "parsed_segments":len(segments),"segments":segments,"by_type":dict(totals),
        "total_commanded_volume_mm3":sum(r["commanded_volume_mm3"] for r in totals.values()) if not issues else None,
        "slicer_declared_time_seconds":declared_time,
        "scope":"Single tool, Marlin-style G90/G91 (also reset extrusion mode) and M82/M83, G0/G1 Cartesian moves; subset amounts remain partial when unsupported. Geometry identity and placement are not inferred from G-code."}
