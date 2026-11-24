"""Fixtures shared by every test file."""

from pathlib import Path

import pytest

import render_layout


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def default_coordinates(monkeypatch):
    """Rendering changes these module globals, so reset them for each test."""
    monkeypatch.setattr(render_layout, "ROOM_ORIGIN_X", 90.0)
    monkeypatch.setattr(render_layout, "ROOM_ORIGIN_Y", 90.0)
    monkeypatch.setattr(render_layout, "SCALE", 3.0)
