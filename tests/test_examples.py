"""The committed example output must match what the scripts produce now.

If a drawing change is intentional, regenerate the examples as described in
README.md and commit the new files.
"""

import shutil
import sys

import pytest

import generate_room
import get_furniture
import render_layout


def read(path):
    """Read text, ignoring platform line endings."""
    return path.read_text(encoding="utf-8")


@pytest.fixture
def examples(repo_root, tmp_path):
    """A scratch copy of examples/ without any generated files."""
    copy = tmp_path / "examples"
    shutil.copytree(
        repo_root / "examples", copy, ignore=shutil.ignore_patterns("*.svg", "furniture.yaml")
    )
    return copy


def test_merged_furniture_is_current(repo_root, examples, monkeypatch):
    monkeypatch.chdir(examples)
    get_furniture.main()
    assert read(examples / "furniture.yaml") == read(repo_root / "examples/furniture.yaml")


@pytest.mark.parametrize("room", ["den", "studio"])
def test_room_svgs_are_current(repo_root, examples, monkeypatch, room):
    folder = examples / "rooms" / room
    committed = repo_root / "examples" / "rooms" / room

    monkeypatch.setattr(sys, "argv", ["generate_room.py", str(folder / "room.yaml")])
    assert generate_room.main() == 0
    monkeypatch.setattr(sys, "argv", [
        "render_layout.py", "--room", str(folder),
        "--furniture", str(repo_root / "examples/furniture.yaml"),
    ])
    assert render_layout.main() == 0

    for name in ("room.svg", "room_with_furniture.svg"):
        assert read(folder / name) == read(committed / name), f"{room}/{name} is out of date"
