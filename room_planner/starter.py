"""Create a starter project."""

from __future__ import annotations

from pathlib import Path

FURNITURE = """\
# Changes to this file are not used until you run room-planner build or merge,
# which merges all furniture_*.yaml files into furniture.yaml.
version: 1.0
units: inches
objects:
  Sofa84:
    category: sofa
    symbol: sofa
    footprint: {shape: rectangle, length: 84, depth: 34}
    render: {arms: both, seats: 3}
  FloorLamp14:
    category: floor_lamp
    symbol: floor_lamp
    footprint: {shape: circle, diameter: 14}
    render: {stem: true}
"""

# The name is quoted because YAML reads names such as "no" or "101" as other types.
ROOM = """\
room:
  id: "%(name)s"
  name: "%(name)s"
  units: inches
  shape: {type: rectangle, width: 144, depth: 120}
  features:
    - id: SouthDoor
      type: doorway
      wall: south
      offset: 100
      width: 36
      label: Door
      door: {width: 32, hinge: left, opens: into_room}
    - id: NorthWindow
      type: window
      wall: north
      offset: 42
      width: 60
      label: Window
"""

LAYOUT = """\
version: 1.0
units: inches
placements:
  - {id: Sofa, object: Sofa84, x: 4, y: 118, rotation: 0}
  - {id: Lamp, object: FloorLamp14, x: 14, y: 14}
"""

GITATTRIBUTES = "* text=auto eol=lf\n"


def create(folder: Path, room: str, *, single: bool = False) -> list[Path]:
    """Create a starter project and return the files written.

    Nothing is written if any of the files already exists.
    """
    if not room.replace("-", "").replace("_", "").isalnum():
        raise ValueError(
            "Room names may contain only letters, numbers, hyphens, and "
            f"underscores, not {room!r}; use --room to choose a name"
        )
    home = folder if single else folder / room
    files = {
        folder / ".gitattributes": GITATTRIBUTES,
        folder / "furniture_starter.yaml": FURNITURE,
        home / "room.yaml": ROOM % {"name": room},
        home / "layout.yaml": LAYOUT,
        home / "annotations.yaml": "annotations: []\n",
    }
    existing = [path for path in files if path.exists()]
    if existing:
        raise FileExistsError(
            "Nothing was created because these files already exist: "
            + ", ".join(str(path) for path in existing)
        )
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return list(files)
