#!/usr/bin/env python3
"""Render furniture, layout, and annotations onto room.svg.

Coordinates are in inches:
- Origin: northwest inside corner
- x increases east
- y increases south

Rectangle anchor: back-left corner, viewed from behind the furniture.
Rotation is any numeric angle in degrees, measured clockwise:
- 0   faces north
- 90  faces east
- 180 faces south
- 270 faces west

Circle anchor: center.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET

try:
    import yaml
except ImportError as exc:
    raise SystemExit("PyYAML is required: pip install PyYAML") from exc

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)

def q(tag: str) -> str:
    return f"{{{SVG_NS}}}{tag}"

ROOM_ORIGIN_X = 90.0
ROOM_ORIGIN_Y = 90.0
SCALE = 3.0

def configure_svg_coordinates(root: ET.Element) -> None:
    """Read coordinate metadata from the room SVG.

    Room SVGs may declare:
      data-origin-x="90"
      data-origin-y="90"
      data-scale="3"

    Defaults preserve compatibility with older room.svg files.
    """
    global ROOM_ORIGIN_X, ROOM_ORIGIN_Y, SCALE
    ROOM_ORIGIN_X = float(root.get("data-origin-x", "90"))
    ROOM_ORIGIN_Y = float(root.get("data-origin-y", "90"))
    SCALE = float(root.get("data-scale", "3"))
    if SCALE <= 0:
        raise ValueError("room.svg: data-scale must be positive")

STYLE_BY_CATEGORY = {
    "sofa": ("#d9e8f7", "#1f4e79"),
    "loveseat": ("#d8f0d2", "#2f6b2f"),
    "chair": ("#f7e3c6", "#7a4b18"),
    "coffee_table": ("#eadcf4", "#62407a"),
    "end_table": ("#f3ead2", "#796a3b"),
    "console_table": ("#e7e2da", "#5b544b"),
    "piano": ("#dddddd", "#222222"),
    "floor_lamp": ("#fff5bf", "#776700"),
}

def sx(x: float) -> float:
    return ROOM_ORIGIN_X + x * SCALE

def sy(y: float) -> float:
    return ROOM_ORIGIN_Y + y * SCALE

def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be a mapping")
    return data


def footprint_shape(footprint: dict) -> str | None:
    """Return an explicit or safely inferred footprint shape.

    Legacy furniture definitions often omitted ``shape``. Infer it only when
    the dimensions are unambiguous:
      - diameter -> circle
      - length + depth -> rectangle
    """
    shape = footprint.get("shape")
    if shape is not None:
        return shape
    if isinstance(footprint.get("diameter"), (int, float)):
        return "circle"
    if (
        isinstance(footprint.get("length"), (int, float))
        and isinstance(footprint.get("depth"), (int, float))
    ):
        return "rectangle"
    return None

def validate(furniture: dict, layout: dict, annotations: dict | None = None) -> list[str]:
    errors: list[str] = []
    objects = furniture.get("objects")
    placements = layout.get("placements")

    if not isinstance(objects, dict):
        return ["furniture.yaml: 'objects' must be a mapping"]
    if not isinstance(placements, list):
        return ["layout.yaml: 'placements' must be a list"]

    for name, obj in objects.items():
        if not isinstance(obj, dict):
            errors.append(f"{name}: object definition must be a mapping")
            continue
        fp = obj.get("footprint")
        if not isinstance(fp, dict):
            errors.append(f"{name}: missing footprint mapping")
            continue
        shape = footprint_shape(fp)
        if shape == "rectangle":
            for field in ("length", "depth"):
                value = fp.get(field)
                if not isinstance(value, (int, float)) or value <= 0:
                    errors.append(f"{name}: {field} must be a positive number")
        elif shape == "circle":
            value = fp.get("diameter")
            if not isinstance(value, (int, float)) or value <= 0:
                errors.append(f"{name}: diameter must be a positive number")
        else:
            errors.append(f"{name}: unsupported footprint shape {shape!r}")

        category = obj.get("category", obj.get("type"))
        if not isinstance(category, str) or not category:
            errors.append(f"{name}: category must be a non-empty string")
        symbol = obj.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            errors.append(f"{name}: symbol must be a non-empty string")

        render = obj.get("render", {})
        if render is not None and not isinstance(render, dict):
            errors.append(f"{name}: render must be a mapping")
        if isinstance(render, dict) and "seats" in render:
            seats = render["seats"]
            if not isinstance(seats, int) or seats < 1:
                errors.append(f"{name}: render.seats must be a positive integer")
        if isinstance(render, dict) and "arms" in render:
            arms = render["arms"]
            if arms not in ("both", "none", "left", "right", True, False):
                errors.append(
                    f"{name}: render.arms must be both, none, left, right, true, or false"
                )

    seen: set[str] = set()
    for i, placement in enumerate(placements, 1):
        label = f"placement #{i}"
        if not isinstance(placement, dict):
            errors.append(f"{label}: must be a mapping")
            continue
        pid = placement.get("id")
        obj_name = placement.get("object")
        if not pid:
            errors.append(f"{label}: missing id")
        elif pid in seen:
            errors.append(f"{label}: duplicate id {pid!r}")
        else:
            seen.add(pid)
        if obj_name not in objects:
            errors.append(f"{label}: unknown object {obj_name!r}")
        for field in ("x", "y"):
            if not isinstance(placement.get(field), (int, float)):
                errors.append(f"{label}: {field} must be numeric")
        rotation = placement.get("rotation", 0)
        if not isinstance(rotation, (int, float)) or isinstance(rotation, bool):
            errors.append(f"{label}: rotation must be numeric")

    if annotations is not None:
        items = annotations.get("annotations")
        if not isinstance(items, list):
            errors.append("annotations.yaml: 'annotations' must be a list")
        else:
            annotation_ids: set[str] = set()
            valid_types = {"label", "callout", "dimension", "area", "note"}
            for i, item in enumerate(items, 1):
                label = f"annotation #{i}"
                if not isinstance(item, dict):
                    errors.append(f"{label}: must be a mapping")
                    continue
                aid = item.get("id")
                atype = item.get("type")
                if not aid:
                    errors.append(f"{label}: missing id")
                elif aid in annotation_ids:
                    errors.append(f"{label}: duplicate id {aid!r}")
                else:
                    annotation_ids.add(aid)
                if atype not in valid_types:
                    errors.append(f"{label}: unsupported type {atype!r}")
                    continue

                for field in ("size", "rotation"):
                    if field in item and (not isinstance(item[field], (int, float)) or isinstance(item[field], bool)):
                        errors.append(f"{label}: {field} must be numeric")
                if "bold" in item and not isinstance(item["bold"], bool):
                    errors.append(f"{label}: bold must be true or false")

                if atype in {"label", "area", "note", "callout"}:
                    if not isinstance(item.get("text"), str):
                        errors.append(f"{label}: text must be a string")
                    for field in ("x", "y"):
                        if not isinstance(item.get(field), (int, float)) or isinstance(item.get(field), bool):
                            errors.append(f"{label}: {field} must be numeric")
                if atype == "callout":
                    target = item.get("leader_to")
                    if not isinstance(target, dict):
                        errors.append(f"{label}: leader_to must be a mapping")
                    else:
                        for field in ("x", "y"):
                            if not isinstance(target.get(field), (int, float)) or isinstance(target.get(field), bool):
                                errors.append(f"{label}: leader_to.{field} must be numeric")
                if atype == "dimension":
                    for endpoint in ("from", "to"):
                        point = item.get(endpoint)
                        if not isinstance(point, dict):
                            errors.append(f"{label}: {endpoint} must be a mapping")
                        else:
                            for field in ("x", "y"):
                                if not isinstance(point.get(field), (int, float)) or isinstance(point.get(field), bool):
                                    errors.append(f"{label}: {endpoint}.{field} must be numeric")
                    if "text" in item and not isinstance(item["text"], str):
                        errors.append(f"{label}: text must be a string")
    return errors

def add_text(group: ET.Element, x: float, y: float, text: str, size: float = 12) -> None:
    node = ET.SubElement(group, q("text"), {
        "x": f"{x:.2f}", "y": f"{y:.2f}",
        "text-anchor": "middle",
        "dominant-baseline": "middle",
        "font-family": "Arial, Helvetica, sans-serif",
        "font-size": str(size),
        "fill": "#111",
        "pointer-events": "none",
    })
    node.text = text

def local_line(group: ET.Element, p1, p2, **attrs) -> None:
    """Draw a line in a rectangle symbol's local coordinate system.

    Local origin is the furniture's back-left anchor. Positive local x runs
    along the back toward back-right. Negative local y runs toward the front.
    Values are supplied in room inches and converted to SVG units here.
    """
    base = {
        "x1": f"{p1[0] * SCALE:.2f}",
        "y1": f"{p1[1] * SCALE:.2f}",
        "x2": f"{p2[0] * SCALE:.2f}",
        "y2": f"{p2[1] * SCALE:.2f}",
    }
    base.update(attrs)
    ET.SubElement(group, q("line"), base)


def render_rectangle(group: ET.Element, placement: dict, definition: dict) -> None:
    """Render a rectangular object using a local symbol plus SVG transform.

    This supports any numeric rotation. The placement's (x, y) is the
    back-left anchor. Rotation is clockwise because SVG's y-axis points down.
    """
    fp = definition["footprint"]
    length = float(fp["length"])
    depth = float(fp["depth"])
    x = float(placement["x"])
    y = float(placement["y"])
    rotation = float(placement.get("rotation", 0))
    fill, stroke = STYLE_BY_CATEGORY.get(
        definition.get("category", definition.get("type")),
        ("#eeeeee", "#444444"),
    )

    # Position the local symbol at the room anchor, then rotate the whole
    # symbol about that anchor. Local front is negative y, so angle 0 faces
    # north and positive angles turn clockwise: 90=east, 180=south, 270=west.
    group.set(
        "transform",
        f"translate({sx(x):.2f} {sy(y):.2f}) rotate({rotation:g})",
    )
    group.set("data-rotation", f"{rotation:g}")

    ET.SubElement(group, q("rect"), {
        "x": "0",
        "y": f"{-depth * SCALE:.2f}",
        "width": f"{length * SCALE:.2f}",
        "height": f"{depth * SCALE:.2f}",
        "rx": "5",
        "fill": fill,
        "fill-opacity": "0.88",
        "stroke": stroke,
        "stroke-width": "2",
    })

    # The dark line is the back edge.
    local_line(
        group, (0, 0), (length, 0),
        stroke=stroke, **{"stroke-width": "7"}
    )

    render = definition.get("render") or {}
    seats = render.get("seats")
    arms = render.get("arms")

    # Cushion divisions run from near the back toward the front.
    if isinstance(seats, int) and seats > 1:
        inset = min(5.0, depth * 0.15)
        for i in range(1, seats):
            along = length * i / seats
            local_line(
                group,
                (along, -inset),
                (along, -(depth - inset)),
                stroke=stroke,
                **{"stroke-width": "1.5"},
            )

    # Arms at the local left and/or right ends.
    draw_left = arms in ("both", "left", True)
    draw_right = arms in ("both", "right", True)
    arm_inset = min(5.0, length * 0.12)
    if draw_left:
        local_line(
            group,
            (arm_inset, 0),
            (arm_inset, -depth),
            stroke=stroke,
            **{"stroke-width": "5"},
        )
    if draw_right:
        local_line(
            group,
            (length - arm_inset, 0),
            (length - arm_inset, -depth),
            stroke=stroke,
            **{"stroke-width": "5"},
        )

    # The label rotates with the furniture symbol.
    add_text(
        group,
        length * SCALE / 2,
        -depth * SCALE / 2,
        placement["id"],
    )

def render_circle(group: ET.Element, placement: dict, definition: dict) -> None:
    diameter = float(definition["footprint"]["diameter"])
    radius = diameter / 2
    x = float(placement["x"])
    y = float(placement["y"])
    fill, stroke = STYLE_BY_CATEGORY.get(
        definition.get("category", definition.get("type")),
        ("#eeeeee", "#444444"),
    )

    ET.SubElement(group, q("circle"), {
        "cx": f"{sx(x):.2f}", "cy": f"{sy(y):.2f}",
        "r": f"{radius*SCALE:.2f}",
        "fill": fill, "fill-opacity": "0.88",
        "stroke": stroke, "stroke-width": "2",
    })

    render = definition.get("render") or {}
    if render.get("stem"):
        ET.SubElement(group, q("circle"), {
            "cx": f"{sx(x):.2f}", "cy": f"{sy(y):.2f}",
            "r": f"{max(2.5, radius*SCALE*0.15):.2f}",
            "fill": stroke,
        })
    else:
        ET.SubElement(group, q("circle"), {
            "cx": f"{sx(x):.2f}", "cy": f"{sy(y):.2f}",
            "r": "3", "fill": stroke,
        })

    add_text(group, sx(x), sy(y), placement["id"], 10)

def remove_generated_layer(root: ET.Element, layer_id: str) -> None:
    # Search recursively, not only among direct children.
    for parent in root.iter():
        for child in list(parent):
            if child.get("id") == layer_id:
                parent.remove(child)

def annotation_text(group: ET.Element, x: float, y: float, text: str, item: dict, *, anchor: str = "middle") -> None:
    size = float(item.get("size", 12))
    color = str(item.get("color", "#222222"))
    rotation = float(item.get("rotation", 0))
    weight = "700" if item.get("bold", False) else "400"
    lines = text.splitlines() or [""]
    node = ET.SubElement(group, q("text"), {
        "x": f"{sx(x):.2f}", "y": f"{sy(y):.2f}",
        "text-anchor": anchor,
        "font-family": "Arial, Helvetica, sans-serif",
        "font-size": f"{size:g}",
        "font-weight": weight,
        "fill": color,
        "pointer-events": "none",
    })
    if rotation:
        node.set("transform", f"rotate({rotation:g} {sx(x):.2f} {sy(y):.2f})")
    line_height = size * 1.25
    start = -((len(lines) - 1) * line_height) / 2
    for index, line in enumerate(lines):
        span = ET.SubElement(node, q("tspan"), {
            "x": f"{sx(x):.2f}",
            "dy": f"{start if index == 0 else line_height:.2f}",
        })
        span.text = line

def callout_leader_start(item: dict) -> tuple[float, float] | None:
    """Return the SVG point where a callout's leader leaves its text.

    The text box is estimated from the font size, because SVG text cannot be
    measured here. Returns None when the target lies within the text box.
    """
    size = float(item.get("size", 12))
    lines = item["text"].splitlines() or [""]
    pad = 4.0
    half_w = max(len(line) for line in lines) * size * 0.6 / 2 + pad
    half_h = ((len(lines) - 1) * size * 1.25 + size * 1.05) / 2 + pad
    # Text is placed by baseline, so its visual center is slightly above y.
    center_y = -size * 0.275

    # Work in the text's own unrotated frame, relative to its anchor.
    angle = math.radians(float(item.get("rotation", 0)))
    cos, sin = math.cos(angle), math.sin(angle)
    ax, ay = sx(float(item["x"])), sy(float(item["y"]))
    tx = sx(float(item["leader_to"]["x"])) - ax
    ty = sy(float(item["leader_to"]["y"])) - ay
    dx = tx * cos + ty * sin
    dy = -tx * sin + ty * cos - center_y

    reach = max(abs(dx) / half_w, abs(dy) / half_h)
    if reach <= 1:
        return None
    px, py = dx / reach, dy / reach + center_y
    return ax + px * cos - py * sin, ay + px * sin + py * cos

def ensure_annotation_markers(root: ET.Element) -> None:
    defs = next((child for child in root if child.tag == q("defs")), None)
    if defs is None:
        defs = ET.Element(q("defs"))
        root.insert(0, defs)
    if any(child.get("id") == "annotation-arrow" for child in defs):
        return
    marker = ET.SubElement(defs, q("marker"), {
        "id": "annotation-arrow", "markerWidth": "8", "markerHeight": "8",
        "refX": "4", "refY": "4", "orient": "auto-start-reverse",
        "markerUnits": "strokeWidth",
    })
    ET.SubElement(marker, q("path"), {"d": "M 0 0 L 8 4 L 0 8 z", "fill": "context-stroke"})

def render_annotations(root: ET.Element, annotations: dict) -> None:
    items = annotations.get("annotations", [])
    if not items:
        return
    ensure_annotation_markers(root)
    layer = ET.SubElement(root, q("g"), {"id": "generated-annotations"})
    for item in items:
        group = ET.SubElement(layer, q("g"), {"id": item["id"], "data-type": item["type"]})
        atype = item["type"]
        color = str(item.get("color", "#222222"))
        if atype in {"label", "area", "note"}:
            annotation_text(group, float(item["x"]), float(item["y"]), item["text"], item)
        elif atype == "callout":
            x, y = float(item["x"]), float(item["y"])
            tx, ty = float(item["leader_to"]["x"]), float(item["leader_to"]["y"] )
            leader_start = callout_leader_start(item)
            if leader_start is not None:
                ET.SubElement(group, q("line"), {
                    "x1": f"{leader_start[0]:.2f}", "y1": f"{leader_start[1]:.2f}",
                    "x2": f"{sx(tx):.2f}", "y2": f"{sy(ty):.2f}",
                    "stroke": color, "stroke-width": "1.5",
                    "marker-end": "url(#annotation-arrow)",
                })
            annotation_text(group, x, y, item["text"], item)
        elif atype == "dimension":
            p1, p2 = item["from"], item["to"]
            x1, y1 = float(p1["x"]), float(p1["y"])
            x2, y2 = float(p2["x"]), float(p2["y"])
            ET.SubElement(group, q("line"), {
                "x1": f"{sx(x1):.2f}", "y1": f"{sy(y1):.2f}",
                "x2": f"{sx(x2):.2f}", "y2": f"{sy(y2):.2f}",
                "stroke": color, "stroke-width": "1.5",
                "marker-start": "url(#annotation-arrow)",
                "marker-end": "url(#annotation-arrow)",
            })
            distance = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
            text = item.get("text", "")
            # Fix auto label if no override was supplied.
            if "text" not in item:
                text = f'{distance:.1f}'.rstrip("0").rstrip(".") + '"'
            annotation_text(group, (x1+x2)/2, (y1+y2)/2, text, item)

def atomic_write(tree: ET.ElementTree, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=output_path.stem + "-", suffix=".svg", dir=output_path.parent
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        tree.write(temp_path, encoding="utf-8", xml_declaration=True)
        os.replace(temp_path, output_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()

def load_optional_annotations(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {"annotations": []}
    return load_yaml(path)


def project_root() -> Path:
    """Directory containing render_layout.py and the project files."""
    return Path(__file__).resolve().parent


def resolve_project_path(value: str | None, default: Path | None = None) -> Path | None:
    """Resolve an option path independently of the current working directory.

    An explicit relative path is tried first relative to the current directory,
    then relative to the project directory containing this script.
    """
    if value is None:
        return default

    supplied = Path(value).expanduser()
    if supplied.is_absolute():
        return supplied

    if supplied.exists():
        return supplied.resolve()

    return project_root() / supplied


def resolve_room_argument(value: str) -> tuple[Path, Path | None]:
    """Resolve --room as either an SVG path or a room directory/name.

    Examples accepted from the project root:
      --room living
      --room rooms/living
      --room rooms/living/room.svg
    """
    supplied = Path(value)
    if supplied.is_file():
        return supplied, supplied.parent
    if supplied.is_dir():
        candidate = supplied / "room.svg"
        if candidate.exists():
            return candidate, supplied
    candidate_dir = project_root() / "rooms" / value
    candidate = candidate_dir / "room.svg"
    if candidate.exists():
        return candidate, candidate_dir
    raise FileNotFoundError(
        f"Cannot resolve room {value!r}; expected an SVG path, room directory, "
        f"or rooms/{value}/room.svg"
    )


def render(
    room_path: Path,
    furniture_path: Path,
    layout_path: Path,
    annotations_path: Path | None,
    output_path: Path,
) -> None:
    furniture = load_yaml(furniture_path)
    layout = load_yaml(layout_path)
    annotations = load_optional_annotations(annotations_path)
    errors = validate(furniture, layout, annotations)
    if errors:
        raise ValueError("\n".join(errors))

    tree = ET.parse(room_path)
    root = tree.getroot()
    configure_svg_coordinates(root)
    remove_generated_layer(root, "generated-furniture")
    remove_generated_layer(root, "generated-annotations")

    layer = ET.SubElement(root, q("g"), {"id": "generated-furniture"})
    objects = furniture["objects"]

    for placement in layout["placements"]:
        definition = objects[placement["object"]]
        item = ET.SubElement(layer, q("g"), {
            "id": placement["id"],
            "data-object": placement["object"],
        })
        shape = footprint_shape(definition["footprint"])
        if shape == "rectangle":
            render_rectangle(item, placement, definition)
        elif shape == "circle":
            render_circle(item, placement, definition)
        else:
            raise ValueError(
                f"{placement['object']}: cannot determine footprint shape"
            )

    render_annotations(root, annotations)
    atomic_write(tree, output_path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render a furniture layout onto a generated room SVG."
    )
    parser.add_argument(
        "--room",
        default="room.svg",
        help="Room name (for example living), room directory, or room.svg path",
    )
    parser.add_argument("--furniture", default=None)
    parser.add_argument("--layout", default=None)
    parser.add_argument("--annotations", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    try:
        room_path, room_dir = resolve_room_argument(args.room)
        root = project_root()
        furniture_path = resolve_project_path(
            args.furniture, root / "furniture.yaml"
        )
        layout_path = resolve_project_path(
            args.layout,
            room_dir / "layout.yaml" if room_dir else root / "layout.yaml",
        )

        if args.annotations:
            annotations_path = resolve_project_path(args.annotations)
        elif room_dir and (room_dir / "annotations.yaml").exists():
            annotations_path = room_dir / "annotations.yaml"
        elif (root / "annotations.yaml").exists():
            annotations_path = root / "annotations.yaml"
        else:
            annotations_path = None

        output_path = resolve_project_path(
            args.output,
            room_dir / "room_with_furniture.svg"
            if room_dir
            else root / "room_with_furniture.svg",
        )

        for label, path in (
            ("room", room_path),
            ("furniture", furniture_path),
            ("layout", layout_path),
        ):
            if path is None or not path.exists():
                raise FileNotFoundError(f"{label} file not found: {path}")

        for label, path in (
            ("room", room_path),
            ("furniture", furniture_path),
            ("layout", layout_path),
        ):
            if path is None or not path.exists():
                raise FileNotFoundError(f"{label} file not found: {path}")

        furniture = load_yaml(furniture_path)
        layout = load_yaml(layout_path)
        annotations = load_optional_annotations(annotations_path)
        errors = validate(furniture, layout, annotations)
        if errors:
            print("Validation failed:", file=sys.stderr)
            for error in errors:
                print(f"  - {error}", file=sys.stderr)
            return 1

        if args.validate_only:
            print("YAML validation passed.")
            return 0

        render(room_path, furniture_path, layout_path, annotations_path, output_path)
        print(f"Wrote {output_path.resolve()}")
        return 0
    except Exception as exc:
        print(f"Render failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
