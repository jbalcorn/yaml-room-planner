import math
from xml.etree import ElementTree as ET

import pytest
import yaml

from room_planner import render_layout

SVG = "{http://www.w3.org/2000/svg}"


def make_furniture(**objects):
    sofa = {
        "category": "sofa",
        "symbol": "sofa",
        "footprint": {"shape": "rectangle", "length": 80, "depth": 30},
    }
    lamp = {
        "category": "floor_lamp",
        "symbol": "floor_lamp",
        "footprint": {"shape": "circle", "diameter": 20},
    }
    return {"objects": {"Sofa": sofa, "Lamp": lamp, **objects}}


def make_layout(*placements):
    return {"placements": list(placements)}


def place(**changes):
    return {"id": "P1", "object": "Sofa", "x": 10, "y": 50, **changes}


def make_callout(**changes):
    return {
        "id": "C", "type": "callout", "text": "Hello",
        "x": 50, "y": 50, "leader_to": {"x": 90, "y": 50}, **changes,
    }


# --- validation ---------------------------------------------------------


def test_valid_input_has_no_errors():
    layout = make_layout(place(), place(id="P2", object="Lamp", rotation=45.5))
    assert render_layout.validate(make_furniture(), layout, {"annotations": [make_callout()]}) == []


@pytest.mark.parametrize(
    ("placement", "message"),
    [
        (place(id=""), "missing id"),
        (place(object="Throne"), "unknown object 'Throne'"),
        (place(x="left"), "x must be numeric"),
        (place(rotation=True), "rotation must be numeric"),
        ("not a mapping", "must be a mapping"),
    ],
)
def test_bad_placements_are_reported(placement, message):
    errors = render_layout.validate(make_furniture(), make_layout(placement))
    assert any(message in error for error in errors)


def test_duplicate_placement_ids_are_reported():
    errors = render_layout.validate(make_furniture(), make_layout(place(), place()))
    assert errors == ["placement #2: duplicate id 'P1'"]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"footprint": None}, "missing footprint"),
        ({"footprint": {"shape": "triangle"}}, "unsupported footprint shape"),
        ({"footprint": {"shape": "rectangle", "length": 0, "depth": 5}}, "length must be"),
        ({"footprint": {"shape": "circle", "diameter": -1}}, "diameter must be"),
        ({"category": ""}, "category must be"),
        ({"symbol": None}, "symbol must be"),
        ({"render": []}, "render must be"),
        ({"render": {"seats": 0}}, "seats must be"),
        ({"render": {"arms": "three"}}, "arms must be"),
    ],
)
def test_bad_furniture_is_reported(changes, message):
    thing = {**make_furniture()["objects"]["Sofa"], **changes}
    errors = render_layout.validate(make_furniture(Thing=thing), make_layout())
    assert any(error.startswith("Thing") and message in error for error in errors)


@pytest.mark.parametrize(
    ("annotation", "message"),
    [
        (make_callout(id=""), "missing id"),
        (make_callout(type="scribble"), "unsupported type"),
        (make_callout(text=5), "text must be a string"),
        (make_callout(x=None), "x must be numeric"),
        (make_callout(leader_to=None), "leader_to must be a mapping"),
        (make_callout(bold="yes"), "bold must be"),
        (make_callout(size="big"), "size must be numeric"),
        ({"id": "D", "type": "dimension", "from": {"x": 0, "y": 0}}, "to must be a mapping"),
    ],
)
def test_bad_annotations_are_reported(annotation, message):
    errors = render_layout.validate(
        make_furniture(), make_layout(), {"annotations": [annotation]}
    )
    assert any(message in error for error in errors)


@pytest.mark.parametrize(
    ("footprint", "expected"),
    [
        ({"shape": "circle"}, "circle"),
        ({"diameter": 10}, "circle"),
        ({"length": 10, "depth": 5}, "rectangle"),
        ({"length": 10}, None),
    ],
)
def test_footprint_shape(footprint, expected):
    assert render_layout.footprint_shape(footprint) == expected


# --- furniture ----------------------------------------------------------


@pytest.mark.parametrize("rotation", [0, 90, 225, 12.5])
def test_rectangle_is_placed_and_rotated_at_its_anchor(rotation):
    group = ET.Element("g")
    sofa = make_furniture()["objects"]["Sofa"]

    render_layout.render_rectangle(group, place(rotation=rotation), sofa)

    # x: 90 + 10*3, y: 90 + 50*3
    assert group.get("transform") == f"translate(120.00 240.00) rotate({rotation:g})"
    rect = group.find(f"{SVG}rect")
    assert (rect.get("width"), rect.get("height"), rect.get("y")) == ("240.00", "90.00", "-90.00")


@pytest.mark.parametrize(
    ("render", "line_count"),
    [
        ({}, 1),
        ({"seats": 3}, 3),
        ({"arms": "left"}, 2),
        ({"arms": "both"}, 3),
        ({"arms": True, "seats": 2}, 4),
        ({"arms": "none"}, 1),
    ],
)
def test_seats_and_arms_are_drawn(render, line_count):
    group = ET.Element("g")
    sofa = {**make_furniture()["objects"]["Sofa"], "render": render}

    render_layout.render_rectangle(group, place(), sofa)

    assert len(group.findall(f"{SVG}line")) == line_count


@pytest.mark.parametrize("stem", [True, False])
@pytest.mark.parametrize("diameter", [12, 20, 60])
def test_round_furniture_label_clears_the_center_dot(diameter, stem):
    group = ET.Element("g")
    lamp = {
        "category": "floor_lamp",
        "footprint": {"diameter": diameter},
        "render": {"stem": stem},
    }

    render_layout.render_circle(group, place(), lamp)

    dot = group.findall(f"{SVG}circle")[1]
    label = group.find(f"{SVG}text")
    label_top = float(label.get("y")) - float(label.get("font-size")) / 2
    assert label_top > float(dot.get("cy")) + float(dot.get("r"))


# --- annotations --------------------------------------------------------


def test_callout_leader_starts_between_the_text_and_target():
    x, y = render_layout.callout_leader_start(make_callout())
    assert render_layout.sx(50) < x < render_layout.sx(90)


@pytest.mark.parametrize(
    ("target", "direction"),
    [((50, 10), "up"), ((50, 90), "down"), ((10, 50), "left"), ((90, 50), "right")],
)
def test_callout_leader_leaves_the_side_facing_the_target(target, direction):
    callout = make_callout(leader_to={"x": target[0], "y": target[1]})
    x, y = render_layout.callout_leader_start(callout)
    dx, dy = x - render_layout.sx(50), y - render_layout.sy(50)

    actual = ("left" if dx < 0 else "right") if abs(dx) > abs(dy) else ("up" if dy < 0 else "down")
    assert actual == direction


def test_callout_rotation_turns_the_text_box():
    """Rotating the text with its target rotates the leader start too."""
    flat = render_layout.callout_leader_start(make_callout())
    turned = render_layout.callout_leader_start(
        make_callout(rotation=90, leader_to={"x": 50, "y": 90})
    )
    ax, ay = render_layout.sx(50), render_layout.sy(50)
    dx, dy = flat[0] - ax, flat[1] - ay
    assert (turned[0] - ax, turned[1] - ay) == pytest.approx((-dy, dx))


def test_callout_without_room_for_a_leader_has_no_line():
    root = ET.Element("svg")
    callout = make_callout(leader_to={"x": 50, "y": 50})

    render_layout.render_annotations(root, {"annotations": [callout]})

    assert render_layout.callout_leader_start(callout) is None
    assert list(root.iter(f"{SVG}line")) == []
    assert "".join(root.itertext()) == "Hello"


@pytest.mark.parametrize(
    "line",
    [
        (0, 0, 60, 0),
        (60, 0, 0, 0),
        (0, 0, 0, 60),
        (0, 60, 0, 0),
        (0, 0, 40, 40),
        (40, 0, 0, 40),
    ],
)
@pytest.mark.parametrize("rotation", [0, 30, 90])
def test_dimension_text_is_clear_of_its_line(line, rotation):
    x1, y1, x2, y2 = line
    size = 12
    x, y = render_layout.dimension_text_position({"rotation": rotation}, '60"', *line)

    # Find the visual center and corners of the text in SVG units.
    angle = math.radians(rotation)
    cos, sin = math.cos(angle), math.sin(angle)
    offset = render_layout.text_center_offset(size)
    center = (x * 3 - offset * sin, y * 3 + offset * cos)
    half_w, half_h = render_layout.text_half_size('60"', size)
    half_w, half_h = half_w - 1, half_h - 1  # within the padding
    corners = [
        (center[0] + a * cos - b * sin, center[1] + a * sin + b * cos)
        for a in (-half_w, half_w)
        for b in (-half_h, half_h)
    ]

    # Every corner must be strictly on the same side of the line.
    sides = [(x2 - x1) * (cy - y1 * 3) - (y2 - y1) * (cx - x1 * 3) for cx, cy in corners]
    assert all(s > 0 for s in sides) or all(s < 0 for s in sides)


def test_zero_length_dimension_does_not_fail():
    x, y = render_layout.dimension_text_position({}, '0"', 5, 5, 5, 5)
    assert x == pytest.approx(5)
    assert y < 5


@pytest.mark.parametrize(
    ("extra", "expected"), [({}, '50"'), ({"text": "custom"}, "custom"), ({"text": ""}, "")]
)
def test_dimension_label(extra, expected):
    root = ET.Element("svg")
    item = {"id": "D", "type": "dimension", "from": {"x": 0, "y": 0}, "to": {"x": 30, "y": 40}, **extra}

    render_layout.render_annotations(root, {"annotations": [item]})

    assert "".join(root.itertext()) == expected


def test_multi_line_note_has_one_span_per_line():
    root = ET.Element("svg")
    note = {"id": "N", "type": "note", "text": "one\ntwo\n", "x": 1, "y": 1}

    render_layout.render_annotations(root, {"annotations": [note]})

    assert [span.text for span in root.iter(f"{SVG}tspan")] == ["one", "two"]


# --- files --------------------------------------------------------------


@pytest.fixture
def files(tmp_path):
    """Write the input files and return the arguments for render()."""
    (tmp_path / "room.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" data-origin-x="100" '
        'data-origin-y="120" data-scale="2"><g id="generated-furniture"/></svg>',
        encoding="utf-8",
    )
    layout = make_layout(place(), place(id="P2", object="Lamp"))
    (tmp_path / "layout.yaml").write_text(yaml.safe_dump(layout), encoding="utf-8")
    (tmp_path / "furniture.yaml").write_text(yaml.safe_dump(make_furniture()), encoding="utf-8")
    return [tmp_path / n for n in ("room.svg", "furniture.yaml", "layout.yaml")] + [
        None, tmp_path / "out.svg"
    ]


def test_furniture_replaces_the_existing_layer(files):
    render_layout.render(*files)

    root = ET.parse(files[-1]).getroot()
    layers = [n for n in root.iter() if n.get("id") == "generated-furniture"]
    assert len(layers) == 1
    assert [n.get("id") for n in layers[0]] == ["P1", "P2"]
    # The origin and scale come from room.svg: 100 + 10*2, 120 + 50*2
    assert layers[0][0].get("transform") == "translate(120.00 220.00) rotate(0)"


def test_rendering_over_the_output_changes_nothing(files):
    render_layout.render(*files)
    first = files[-1].read_bytes()

    render_layout.render(files[-1], *files[1:])

    assert files[-1].read_bytes() == first


def test_invalid_layout_writes_nothing(files):
    files[2].write_text(yaml.safe_dump(make_layout(place(object="Throne"))), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown object 'Throne'"):
        render_layout.render(*files)
    assert not files[-1].exists()
