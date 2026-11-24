import os
import shutil
import subprocess
import sys
from xml.etree import ElementTree as ET

import pytest

from room_planner import generate_room

SVG = "{http://www.w3.org/2000/svg}"


def make_room(*features, width=120, depth=100, **extra):
    shape = {"type": "rectangle", "width": width, "depth": depth}
    return {"name": "Test", "shape": shape, "features": list(features), **extra}


def make_door(wall="north", **changes):
    door = {"width": 32, "hinge": "left", "opens": "into_room"}
    door.update(changes.pop("door", {}))
    return {"id": "Door", "type": "doorway", "wall": wall, "offset": 20, "width": 36, "door": door, **changes}


def make_window(**changes):
    return {"id": "Window", "type": "window", "wall": "north", "offset": 20, "width": 40, **changes}


@pytest.fixture
def generate(tmp_path):
    """Generate a room and return the root SVG element."""

    def run(room, scale=3.0):
        output = tmp_path / "room.svg"
        generate_room.generate(room, output, scale)
        return ET.parse(output).getroot()

    return run


def find_text(root, value):
    return next(node for node in root.iter(f"{SVG}text") if node.text == value)


# --- validation ---------------------------------------------------------


@pytest.mark.parametrize("value", [0, -5, "wide", True, None])
@pytest.mark.parametrize("field", ["width", "depth"])
def test_bad_room_size_is_rejected(field, value):
    with pytest.raises(ValueError, match=field):
        generate_room.validate_room(make_room(**{field: value}))


def test_only_rectangles_are_supported():
    with pytest.raises(ValueError, match="rectangle"):
        generate_room.validate_room({"shape": {"type": "circle"}})


@pytest.mark.parametrize(
    ("features", "message"),
    [
        ([make_window(id="")], "missing id"),
        ([make_window(), make_window(offset=70)], "duplicate feature id"),
        ([make_window(wall="up")], "north/east/south/west"),
        ([make_window(offset=100)], "outside the north wall"),
        ([make_window(offset=-1)], "outside the north wall"),
        ([make_window(), make_window(id="W2", offset=50)], "overlaps Window"),
        ([make_door(door={"width": 40})], "cannot exceed"),
        ([make_door(door={"hinge": "top"})], "hinge"),
        ([make_door(door={"leaves": 2})], "hinge"),
        ([make_door(door={"leaves": 3})], "leaves"),
        ([make_door(door={"opens": "sideways"})], "opens"),
        ([{"id": "X", "type": "portal"}], "unsupported feature type"),
        ([{"id": "R", "type": "radiator", "x": 0, "y": 0, "depth": 8, "length": 40, "orientation": "up"}], "orientation"),
    ],
)
def test_bad_features_are_rejected(features, message):
    with pytest.raises(ValueError, match=message):
        generate_room.validate_room(make_room(*features))


def test_features_may_touch_without_overlapping():
    room = make_room(make_window(), make_window(id="W2", offset=60))
    assert generate_room.validate_room(room)[:2] == (120, 100)


# --- wall positions -----------------------------------------------------


@pytest.mark.parametrize(
    ("wall", "field", "expected"),
    [
        ("north", "offset", 10),
        ("north", "start", 10),
        ("south", "start_from_west", 10),
        ("south", "start_from_east", 120 - 10 - 30),
        ("east", "start_from_north", 10),
        ("west", "start_from_south", 100 - 10 - 30),
    ],
)
def test_feature_start(wall, field, expected):
    feature = {"id": "F", "width": 30, field: 10}
    assert generate_room.feature_start(feature, wall, 120, 100) == expected


def test_feature_start_is_required():
    with pytest.raises(ValueError, match="missing wall start"):
        generate_room.feature_start({"id": "F", "width": 30}, "north", 120, 100)


@pytest.mark.parametrize(
    ("value", "expected"), [(12, '12"'), (12.5, '12.5"'), (40.25, '40.25"'), (1 / 3, '0.333"')]
)
def test_fmt_inches(value, expected):
    assert generate_room.fmt_inches(value) == expected


# --- drawing ------------------------------------------------------------


def test_svg_records_its_coordinates(generate):
    root = generate(make_room(), scale=4)

    assert root.get("data-scale") == "4"
    assert root.get("data-origin-x") == "128"
    assert root.get("data-room-width") == "120"
    assert root.get("data-room-depth") == "100"


def test_wall_has_a_gap_for_an_opening(generate):
    root = generate(make_room({"id": "O", "type": "opening", "wall": "north", "offset": 20, "width": 40}))
    origin = float(root.get("data-origin-x"))
    top = float(root.get("data-origin-y"))

    segments = sorted(
        ((float(n.get("x1")) - origin) / 3, (float(n.get("x2")) - origin) / 3)
        for n in root.iter(f"{SVG}line")
        if n.get("class") == "wall" and float(n.get("y1")) == float(n.get("y2")) == top
    )
    assert segments == [(0, 20), (60, 120)]


@pytest.mark.parametrize("scale", [1, 2, 3, 5])
def test_title_clears_the_overall_width_label(generate, scale):
    root = generate(make_room(make_window()), scale=scale)

    title = next(n for n in root.iter(f"{SVG}text") if n.get("class") == "title")
    title_bottom = float(title.get("y")) + 6
    label_top = float(find_text(root, '120"').get("y")) - 10
    assert label_top > title_bottom


@pytest.mark.parametrize("opens", ["into_room", "out_of_room"])
@pytest.mark.parametrize("wall", ["north", "east", "south", "west"])
def test_door_label_is_on_the_side_away_from_the_swing(generate, wall, opens):
    root = generate(make_room(make_door(wall, label="Way out", door={"opens": opens})))
    label = find_text(root, "Way out")
    x = (float(label.get("x")) - float(root.get("data-origin-x"))) / 3
    y = (float(label.get("y")) - float(root.get("data-origin-y"))) / 3

    outside = {"north": y < 0, "south": y > 100, "west": x < 0, "east": x > 120}[wall]
    assert outside == (opens == "into_room")


def test_double_door_draws_two_arcs(generate):
    room = make_room(make_door(width=64, door={"width": 60, "leaves": 2, "hinge": "both"}))
    arcs = [n for n in generate(room).iter(f"{SVG}path") if n.get("class") == "door"]
    assert len(arcs) == 2


@pytest.mark.parametrize("position", ["left", True])
def test_bad_door_position_is_rejected(generate, position):
    with pytest.raises(ValueError, match="position"):
        generate(make_room(make_door(door={"position": position})))


def test_bad_reference_line_is_rejected(generate):
    with pytest.raises(ValueError, match="vertical or horizontal"):
        generate(make_room(reference_lines=[{"id": "L", "orientation": "diagonal", "offset": 5}]))


# --- files --------------------------------------------------------------


def test_output_is_the_same_on_every_run(repo_root, tmp_path):
    """Python randomizes set order per process, so use separate processes."""
    shutil.copy(repo_root / "examples/house/den/room.yaml", tmp_path)
    results = set()
    for seed in ("0", "1", "2", "3"):
        subprocess.run(
            [sys.executable, "-m", "room_planner", "generate", "--project", tmp_path],
            check=True, capture_output=True, cwd=repo_root,
            env={**os.environ, "PYTHONHASHSEED": seed},
        )
        results.add((tmp_path / "room.svg").read_bytes())
    assert len(results) == 1


@pytest.mark.parametrize("text", ["[]", "other: 1", "room: text"])
def test_room_mapping_is_required(tmp_path, text):
    source = tmp_path / "room.yaml"
    source.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match="room|mapping"):
        generate_room.load_yaml(source)
