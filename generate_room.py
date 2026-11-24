#!/usr/bin/env python3
"""Generate a dimensioned architectural room SVG from room.yaml.

Supported room model (v1):
- rectangular rooms
- doorway features on north/east/south/west walls
- centered or offset hinged doors, opening into the room
- windows (including multiple panels)
- rectangular radiators/fixtures
- automatic overall and wall-segment dimensions
- stable SVG layers for geometry, fixed features, labels, dimensions,
  coordinate reference, furniture, and annotations

All room coordinates are inches. The room's northwest inside corner is (0, 0),
x increases east, and y increases south.
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

try:
    import yaml
except ImportError as exc:
    raise SystemExit("PyYAML is required: pip install PyYAML") from exc

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)

def q(tag: str) -> str:
    return f"{{{SVG_NS}}}{tag}"

WALLS = ("north", "east", "south", "west")

@dataclass(frozen=True)
class Canvas:
    scale: float
    origin_x: float
    origin_y: float
    width: float
    height: float

    def x(self, inches: float) -> float:
        return self.origin_x + inches * self.scale

    def y(self, inches: float) -> float:
        return self.origin_y + inches * self.scale


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be a mapping")
    room = data.get("room")
    if not isinstance(room, dict):
        raise ValueError(f"{path}: missing 'room' mapping")
    return room


def number(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    value = float(value)
    if positive and value <= 0:
        raise ValueError(f"{label} must be positive")
    return value


def wall_length(wall: str, width: float, depth: float) -> float:
    return width if wall in {"north", "south"} else depth


def feature_start(feature: dict[str, Any], wall: str, width: float, depth: float) -> float:
    """Return feature start measured in the wall's canonical direction.

    Canonical direction is west->east for north/south and north->south for
    east/west. Explicit start_from_* fields are accepted for readability.
    """
    if "offset" in feature:
        return number(feature["offset"], f"{feature.get('id','feature')}.offset")
    if "start" in feature:
        return number(feature["start"], f"{feature.get('id','feature')}.start")
    keys = {
        "north": ("start_from_west", "start_from_east"),
        "south": ("start_from_west", "start_from_east"),
        "east": ("start_from_north", "start_from_south"),
        "west": ("start_from_north", "start_from_south"),
    }[wall]
    if keys[0] in feature:
        return number(feature[keys[0]], f"{feature.get('id','feature')}.{keys[0]}")
    if keys[1] in feature:
        length = wall_length(wall, width, depth)
        return length - number(feature[keys[1]], f"{feature.get('id','feature')}.{keys[1]}") - number(feature.get("width"), f"{feature.get('id','feature')}.width", positive=True)
    raise ValueError(f"{feature.get('id','feature')}: missing wall start")


def validate_room(room: dict[str, Any]) -> tuple[float, float, list[dict[str, Any]]]:
    shape = room.get("shape")
    if not isinstance(shape, dict) or shape.get("type") != "rectangle":
        raise ValueError("room.shape.type must be 'rectangle'")
    width = number(shape.get("width"), "room.shape.width", positive=True)
    depth = number(shape.get("depth"), "room.shape.depth", positive=True)
    features = room.get("features", [])
    if not isinstance(features, list):
        raise ValueError("room.features must be a list")

    seen: set[str] = set()
    wall_intervals: dict[str, list[tuple[float, float, str]]] = {w: [] for w in WALLS}
    for i, f in enumerate(features, 1):
        if not isinstance(f, dict):
            raise ValueError(f"feature #{i} must be a mapping")
        fid = f.get("id")
        if not isinstance(fid, str) or not fid:
            raise ValueError(f"feature #{i} missing id")
        if fid in seen:
            raise ValueError(f"duplicate feature id: {fid}")
        seen.add(fid)
        ftype = f.get("type")
        if ftype in {"doorway", "window", "opening"}:
            wall = f.get("wall")
            if wall not in WALLS:
                raise ValueError(f"{fid}.wall must be north/east/south/west")
            fw = number(f.get("width"), f"{fid}.width", positive=True)
            start = feature_start(f, wall, width, depth)
            end = start + fw
            length = wall_length(wall, width, depth)
            if start < 0 or end > length + 1e-8:
                raise ValueError(f"{fid} extends outside the {wall} wall")
            for a, b, other in wall_intervals[wall]:
                if max(a, start) < min(b, end) - 1e-8:
                    raise ValueError(f"{fid} overlaps {other} on the {wall} wall")
            wall_intervals[wall].append((start, end, fid))
            if ftype == "doorway":
                door = f.get("door")
                if not isinstance(door, dict):
                    raise ValueError(f"{fid}.door must be a mapping")
                dw = number(door.get("width"), f"{fid}.door.width", positive=True)
                if dw > fw:
                    raise ValueError(f"{fid}.door.width cannot exceed doorway width")
                leaves = int(door.get("leaves", 1))
                if leaves not in {1, 2}:
                    raise ValueError(f"{fid}.door.leaves must be 1 or 2")
                allowed_hinges = {"both"} if leaves == 2 else {"left", "right"}
                if door.get("hinge") not in allowed_hinges:
                    raise ValueError(f"{fid}.door.hinge must be one of {sorted(allowed_hinges)}")
                if door.get("opens", "into_room") not in {"into_room", "out_of_room"}:
                    raise ValueError(f"{fid}.door.opens must be into_room or out_of_room")
        elif ftype == "radiator":
            for key in ("x", "y", "depth", "length"):
                number(f.get(key), f"{fid}.{key}", positive=key in {"depth", "length"})
            if f.get("orientation") not in {"north_south", "east_west"}:
                raise ValueError(f"{fid}.orientation must be north_south or east_west")
        elif ftype in {"fixture", "obstruction"}:
            for key in ("x", "y", "width", "depth"):
                number(f.get(key), f"{fid}.{key}", positive=key in {"width", "depth"})
        else:
            raise ValueError(f"{fid}: unsupported feature type {ftype!r}")
    return width, depth, features


def fmt_inches(value: float) -> str:
    rounded = round(value, 3)
    if abs(rounded - round(rounded)) < 1e-9:
        return f'{int(round(rounded))}"'
    text = f"{rounded:.3f}".rstrip("0").rstrip(".")
    return f'{text}"'


def add(parent: ET.Element, tag: str, attrs: dict[str, Any] | None = None, text: str | None = None) -> ET.Element:
    node = ET.SubElement(parent, q(tag), {k: str(v) for k, v in (attrs or {}).items()})
    if text is not None:
        node.text = text
    return node


def line(parent: ET.Element, cls: str, x1: float, y1: float, x2: float, y2: float, c: Canvas, **attrs: Any) -> None:
    base = {"class": cls, "x1": f"{c.x(x1):.3f}", "y1": f"{c.y(y1):.3f}", "x2": f"{c.x(x2):.3f}", "y2": f"{c.y(y2):.3f}"}
    base.update(attrs)
    add(parent, "line", base)


def text(parent: ET.Element, cls: str, x: float, y: float, value: str, c: Canvas, *, anchor: str = "middle", rotation: float | None = None) -> None:
    attrs: dict[str, Any] = {"class": cls, "x": f"{c.x(x):.3f}", "y": f"{c.y(y):.3f}", "text-anchor": anchor}
    if rotation is not None:
        attrs["transform"] = f"rotate({rotation:g} {c.x(x):.3f} {c.y(y):.3f})"
    add(parent, "text", attrs, value)


def wall_point(wall: str, distance: float, width: float, depth: float) -> tuple[float, float]:
    if wall == "north": return distance, 0
    if wall == "east": return width, distance
    if wall == "south": return distance, depth
    return 0, distance


def draw_walls(group: ET.Element, features: list[dict[str, Any]], width: float, depth: float, c: Canvas) -> None:
    openings: dict[str, list[tuple[float, float]]] = {w: [] for w in WALLS}
    for f in features:
        if f.get("type") in {"doorway", "window", "opening"}:
            wall = f["wall"]
            s = feature_start(f, wall, width, depth)
            openings[wall].append((s, s + float(f["width"])))
    for wall in WALLS:
        length = wall_length(wall, width, depth)
        cursor = 0.0
        for start, end in sorted(openings[wall]):
            if start > cursor:
                x1,y1 = wall_point(wall,cursor,width,depth); x2,y2 = wall_point(wall,start,width,depth)
                line(group,"wall",x1,y1,x2,y2,c)
            cursor=end
        if cursor < length:
            x1,y1=wall_point(wall,cursor,width,depth); x2,y2=wall_point(wall,length,width,depth)
            line(group,"wall",x1,y1,x2,y2,c)


def draw_window(group: ET.Element, f: dict[str, Any], width: float, depth: float, c: Canvas) -> None:
    wall=f["wall"]; start=feature_start(f,wall,width,depth); fw=float(f["width"]); panels=int(f.get("panels",1))
    off=1.25
    if wall in {"north","south"}:
        y=0 if wall=="north" else depth
        inward=1 if wall=="north" else -1
        for d in (-off,off): line(group,"window",start,y+inward*d,start+fw,y+inward*d,c)
        for i in range(1,panels):
            x=start+fw*i/panels; line(group,"window",x,y-off,x,y+off,c)
    else:
        x=0 if wall=="west" else width
        inward=1 if wall=="west" else -1
        for d in (-off,off): line(group,"window",x+inward*d,start,x+inward*d,start+fw,c)
        for i in range(1,panels):
            y=start+fw*i/panels; line(group,"window",x-off,y,x+off,y,c)


def door_leaf_bounds(f: dict[str, Any], width: float, depth: float) -> tuple[float,float,float]:
    wall=f["wall"]; opening_start=feature_start(f,wall,width,depth); opening_width=float(f["width"])
    door=f["door"]; dw=float(door["width"]); pos=door.get("position","centered")
    if pos == "centered": leaf_start=opening_start+(opening_width-dw)/2
    elif isinstance(pos,(int,float)) and not isinstance(pos,bool): leaf_start=opening_start+float(pos)
    else: raise ValueError(f"{f['id']}.door.position must be centered or numeric offset")
    return leaf_start, leaf_start+dw, dw



def draw_door(group: ET.Element, f: dict[str, Any], width: float, depth: float, c: Canvas) -> None:
    wall=f["wall"]; a,b,total=door_leaf_bounds(f,width,depth)
    door=f["door"]; leaves=int(door.get("leaves",1)); opens=door.get("opens","into_room")
    direction = 1 if opens=="into_room" else -1

    if leaves == 2:
        leaf=total/2
        mid=(a+b)/2
        if wall=="north":
            line(group,"door",a,0,b,0,c)
            line(group,"door",a,0,a,direction*leaf,c)
            line(group,"door",b,0,b,direction*leaf,c)
            r=leaf*c.scale
            sweep_left = 1 if direction > 0 else 0
            sweep_right = 0 if direction > 0 else 1
            add(group,"path",{"class":"door","d":f"M {c.x(mid):.3f} {c.y(0):.3f} A {r:.3f} {r:.3f} 0 0 {sweep_left} {c.x(a):.3f} {c.y(direction*leaf):.3f}"})
            add(group,"path",{"class":"door","d":f"M {c.x(mid):.3f} {c.y(0):.3f} A {r:.3f} {r:.3f} 0 0 {sweep_right} {c.x(b):.3f} {c.y(direction*leaf):.3f}"})
        elif wall=="south":
            line(group,"door",a,depth,b,depth,c)
            line(group,"door",a,depth,a,depth-direction*leaf,c)
            line(group,"door",b,depth,b,depth-direction*leaf,c)
            r=leaf*c.scale
            add(group,"path",{"class":"door","d":f"M {c.x(mid):.3f} {c.y(depth):.3f} A {r:.3f} {r:.3f} 0 0 {0 if direction>0 else 1} {c.x(a):.3f} {c.y(depth-direction*leaf):.3f}"})
            add(group,"path",{"class":"door","d":f"M {c.x(mid):.3f} {c.y(depth):.3f} A {r:.3f} {r:.3f} 0 0 {1 if direction>0 else 0} {c.x(b):.3f} {c.y(depth-direction*leaf):.3f}"})
        elif wall=="east":
            line(group,"door",width,a,width,b,c)
            line(group,"door",width,a,width-direction*leaf,a,c)
            line(group,"door",width,b,width-direction*leaf,b,c)
            r=leaf*c.scale
            add(group,"path",{"class":"door","d":f"M {c.x(width):.3f} {c.y(mid):.3f} A {r:.3f} {r:.3f} 0 0 {1 if direction>0 else 0} {c.x(width-direction*leaf):.3f} {c.y(a):.3f}"})
            add(group,"path",{"class":"door","d":f"M {c.x(width):.3f} {c.y(mid):.3f} A {r:.3f} {r:.3f} 0 0 {0 if direction>0 else 1} {c.x(width-direction*leaf):.3f} {c.y(b):.3f}"})
        else:
            line(group,"door",0,a,0,b,c)
            line(group,"door",0,a,direction*leaf,a,c)
            line(group,"door",0,b,direction*leaf,b,c)
            r=leaf*c.scale
            add(group,"path",{"class":"door","d":f"M {c.x(0):.3f} {c.y(mid):.3f} A {r:.3f} {r:.3f} 0 0 {0 if direction>0 else 1} {c.x(direction*leaf):.3f} {c.y(a):.3f}"})
            add(group,"path",{"class":"door","d":f"M {c.x(0):.3f} {c.y(mid):.3f} A {r:.3f} {r:.3f} 0 0 {1 if direction>0 else 0} {c.x(direction*leaf):.3f} {c.y(b):.3f}"})
        return

    hinge=door["hinge"]
    swing = total if opens=="into_room" else -total
    if wall=="north":
        hx = a if hinge=="left" else b; closed_x = b if hinge=="left" else a
        line(group,"door",a,0,b,0,c); line(group,"door",hx,0,hx,swing,c)
        start=(closed_x,0); end=(hx,swing); sweep=(1 if hinge=="left" else 0) if swing>0 else (0 if hinge=="left" else 1)
    elif wall=="south":
        hx = b if hinge=="left" else a; closed_x = a if hinge=="left" else b
        line(group,"door",a,depth,b,depth,c); line(group,"door",hx,depth,hx,depth-swing,c)
        start=(closed_x,depth); end=(hx,depth-swing); sweep=(1 if hinge=="left" else 0) if swing>0 else (0 if hinge=="left" else 1)
    elif wall=="east":
        hy = a if hinge=="left" else b; closed_y = b if hinge=="left" else a
        line(group,"door",width,a,width,b,c); line(group,"door",width,hy,width-swing,hy,c)
        start=(width,closed_y); end=(width-swing,hy); sweep=(1 if hinge=="left" else 0) if swing>0 else (0 if hinge=="left" else 1)
    else:
        hy = b if hinge=="left" else a; closed_y = a if hinge=="left" else b
        line(group,"door",0,a,0,b,c); line(group,"door",0,hy,swing,hy,c)
        start=(0,closed_y); end=(swing,hy); sweep=(1 if hinge=="left" else 0) if swing>0 else (0 if hinge=="left" else 1)
    r=abs(total*c.scale)
    add(group,"path",{"class":"door","d":f"M {c.x(start[0]):.3f} {c.y(start[1]):.3f} A {r:.3f} {r:.3f} 0 0 {sweep} {c.x(end[0]):.3f} {c.y(end[1]):.3f}"})

def draw_radiator(group: ET.Element, f: dict[str, Any], c: Canvas) -> None:
    x=float(f["x"]); y=float(f["y"]); dep=float(f["depth"]); length=float(f["length"])
    if f["orientation"]=="north_south": rw,rh=dep,length
    else: rw,rh=length,dep
    add(group,"rect",{"class":"fixture","x":f"{c.x(x):.3f}","y":f"{c.y(y):.3f}","width":f"{rw*c.scale:.3f}","height":f"{rh*c.scale:.3f}","rx":"2"})
    count=5
    if f["orientation"]=="north_south":
        for i in range(1,count): line(group,"fixture-line",x+rw*i/count,y+1,x+rw*i/count,y+rh-1,c)
    else:
        for i in range(1,count): line(group,"fixture-line",x+1,y+rh*i/count,x+rw-1,y+rh*i/count,c)


def draw_fixture(group: ET.Element, f: dict[str, Any], c: Canvas) -> None:
    x=float(f["x"]); y=float(f["y"]); fw=float(f["width"]); dep=float(f["depth"])
    style=f.get("style","generic")
    add(group,"rect",{"class":"fixture","x":f"{c.x(x):.3f}","y":f"{c.y(y):.3f}","width":f"{fw*c.scale:.3f}","height":f"{dep*c.scale:.3f}","rx":"2"})
    if style=="fireplace":
        inset=min(4.0,dep/4)
        add(group,"rect",{"class":"fixture-line","x":f"{c.x(x+inset):.3f}","y":f"{c.y(y+inset):.3f}","width":f"{(fw-2*inset)*c.scale:.3f}","height":f"{max(dep-2*inset,1)*c.scale:.3f}"})

def draw_labels(group: ET.Element, room: dict[str, Any], features: list[dict[str, Any]], width: float, depth: float, c: Canvas) -> None:
    for f in features:
        fid=f["id"]; label=f.get("label") or fid.replace("_"," ")
        if f["type"] in {"doorway","window","opening"}:
            wall=f["wall"]; s=feature_start(f,wall,width,depth); mid=s+float(f["width"])/2
            if wall=="north": text(group,"label",mid,-5.5,label,c)
            elif wall=="south": text(group,"label",mid,depth-4,label,c)
            elif wall=="east": text(group,"label",width-4,mid,label,c,rotation=90)
            else: text(group,"label",4,mid,label,c,rotation=90)
        elif f["type"]=="fixture":
            x=float(f["x"]); y=float(f["y"]); fw=float(f["width"]); dep=float(f["depth"])
            text(group,"small",x+fw/2,y+dep/2,label,c)
        elif f["type"]=="radiator":
            x=float(f["x"]); y=float(f["y"]); dep=float(f["depth"]); length=float(f["length"])
            if f["orientation"]=="north_south": text(group,"small",x+dep/2,y+length/2,label,c,rotation=90)
            else: text(group,"small",x+length/2,y+dep/2,label,c)


def dimension(group: ET.Element, c: Canvas, p1: tuple[float,float], p2: tuple[float,float], label: str, text_at: tuple[float,float], rotation: float|None=None) -> None:
    line(group,"dim",p1[0],p1[1],p2[0],p2[1],c)
    text(group,"small",text_at[0],text_at[1],label,c,rotation=rotation)


def wall_breaks(features: list[dict[str,Any]], wall: str, width: float, depth: float) -> list[float]:
    points={0.0,wall_length(wall,width,depth)}
    for f in features:
        if f.get("wall")==wall and f.get("type") in {"doorway","window","opening"}:
            s=feature_start(f,wall,width,depth); points.update((s,s+float(f["width"])))
    return sorted(points)


def draw_dimensions(group: ET.Element, features: list[dict[str,Any]], width: float, depth: float, c: Canvas) -> None:
    # Overall dimensions
    line(group,"ext",0,0,0,-19,c); line(group,"ext",width,0,width,-19,c)
    dimension(group,c,(0,-16),(width,-16),fmt_inches(width),(width/2,-19))
    line(group,"ext",-21,0,0,0,c); line(group,"ext",-21,depth,0,depth,c)
    dimension(group,c,(-17,0),(-17,depth),fmt_inches(depth),(-21,depth/2),90)
    offsets={"north":-8,"south":depth+8,"east":width+8,"west":-8}
    for wall in ("north","east","south","west"):
        pts=wall_breaks(features,wall,width,depth)
        for a,b in zip(pts,pts[1:]):
            if b-a < 0.01: continue
            mid=(a+b)/2; label=fmt_inches(b-a)
            if wall=="north": dimension(group,c,(a,offsets[wall]),(b,offsets[wall]),label,(mid,offsets[wall]-2.5))
            elif wall=="south": dimension(group,c,(a,offsets[wall]),(b,offsets[wall]),label,(mid,offsets[wall]+4))
            elif wall=="east": dimension(group,c,(offsets[wall],a),(offsets[wall],b),label,(offsets[wall]+4,mid),90)
            else: dimension(group,c,(offsets[wall],a),(offsets[wall],b),label,(offsets[wall]-4,mid),90)


def generate(room: dict[str,Any], output: Path, scale: float) -> None:
    width,depth,features=validate_room(room)
    margin_in=32.0
    c=Canvas(scale=scale,origin_x=margin_in*scale,origin_y=margin_in*scale,width=(width+2*margin_in)*scale,height=(depth+2*margin_in)*scale)
    root=ET.Element(q("svg"),{
        "width":f"{c.width:.0f}","height":f"{c.height:.0f}","viewBox":f"0 0 {c.width:.3f} {c.height:.3f}",
        "data-origin-x":f"{c.origin_x:g}","data-origin-y":f"{c.origin_y:g}","data-scale":f"{scale:g}",
        "data-room-width":f"{width:g}","data-room-depth":f"{depth:g}","data-generated-from":"room.yaml"
    })
    defs=add(root,"defs")
    marker=add(defs,"marker",{"id":"dim-arrow","markerWidth":"7","markerHeight":"7","refX":"3.5","refY":"3.5","orient":"auto-start-reverse","markerUnits":"strokeWidth"})
    add(marker,"path",{"d":"M 0 0 L 7 3.5 L 0 7 z","fill":"#555"})
    style=add(defs,"style")
    style.text="""
.wall{stroke:#111;stroke-width:6;fill:none;stroke-linecap:square}.window{stroke:#2878b5;stroke-width:3;fill:none}.door{stroke:#2463a8;stroke-width:2.3;fill:none}.fixture{stroke:#9b3a2d;stroke-width:2;fill:#eee}.fixture-line{stroke:#999;stroke-width:.8;fill:none}.reference-line{stroke:#555;stroke-width:1.2;stroke-dasharray:4 7}.dim{stroke:#555;stroke-width:1.1;fill:none;marker-start:url(#dim-arrow);marker-end:url(#dim-arrow)}.ext{stroke:#999;stroke-width:.8}.label{font-family:Arial,Helvetica,sans-serif;fill:#222;font-size:12px}.small{font-family:Arial,Helvetica,sans-serif;fill:#444;font-size:10px}.title{font-family:Arial,Helvetica,sans-serif;fill:#111;font-size:22px;font-weight:700}
"""
    add(root,"rect",{"width":"100%","height":"100%","fill":"white"})
    add(root,"rect",{"x":f"{c.x(0):.3f}","y":f"{c.y(0):.3f}","width":f"{width*c.scale:.3f}","height":f"{depth*c.scale:.3f}","fill":"#f7f1e8"})
    add(root,"text",{"class":"title","x":f"{c.width/2:.3f}","y":"30","text-anchor":"middle"},f"{room.get('name',room.get('id','Room'))} — Dimensioned Master")
    geometry=add(root,"g",{"id":"room-geometry"}); draw_walls(geometry,features,width,depth,c)
    fixed=add(root,"g",{"id":"fixed-features"})
    for f in features:
        if f["type"]=="window": draw_window(fixed,f,width,depth,c)
        elif f["type"]=="doorway": draw_door(fixed,f,width,depth,c)
        elif f["type"]=="radiator": draw_radiator(fixed,f,c)
        elif f["type"]=="fixture": draw_fixture(fixed,f,c)
    refs=add(root,"g",{"id":"reference-lines"})
    for ref in room.get("reference_lines", []):
        if ref.get("orientation")=="vertical":
            off=number(ref.get("offset"),f"{ref.get('id','reference')}.offset")
            line(refs,"reference-line",off,0,off,depth,c)
            text(refs,"small",off+3,depth-4,ref.get("label",ref.get("id","Reference")),c,anchor="start")
        elif ref.get("orientation")=="horizontal":
            off=number(ref.get("offset"),f"{ref.get('id','reference')}.offset")
            line(refs,"reference-line",0,off,width,off,c)
            text(refs,"small",width-3,off-3,ref.get("label",ref.get("id","Reference")),c,anchor="end")
        else:
            raise ValueError(f"{ref.get('id','reference')}.orientation must be vertical or horizontal")
    labels=add(root,"g",{"id":"feature-labels"}); draw_labels(labels,room,features,width,depth,c)
    dims=add(root,"g",{"id":"dimensions"}); draw_dimensions(dims,features,width,depth,c)
    coords=add(root,"g",{"id":"coordinate-reference"})
    add(coords,"circle",{"cx":f"{c.x(0):.3f}","cy":f"{c.y(0):.3f}","r":"4","fill":"#b00020"})
    add(coords,"text",{"class":"small","x":f"{c.x(0)+7:.3f}","y":f"{c.y(0)+14:.3f}"},"(0,0)")
    add(root,"g",{"id":"generated-furniture"}); add(root,"g",{"id":"generated-annotations"})
    ET.indent(root,space="  ")
    output.parent.mkdir(parents=True,exist_ok=True)
    tree=ET.ElementTree(root)
    tree.write(output,encoding="utf-8",xml_declaration=True)


def main() -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("room_yaml",type=Path,help="Input room.yaml")
    ap.add_argument("-o","--output",type=Path,help="Output SVG (default: room.svg beside YAML)")
    ap.add_argument("--scale",type=float,default=3.0,help="SVG units per inch (default: 3)")
    args=ap.parse_args()
    if args.scale<=0: ap.error("--scale must be positive")
    output=args.output or args.room_yaml.with_name("room.svg")
    try:
        room=load_yaml(args.room_yaml)
        generate(room,output,args.scale)
    except (OSError,ValueError,yaml.YAMLError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr); return 2
    print(f"Generated {output}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
