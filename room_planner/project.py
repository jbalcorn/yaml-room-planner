"""Find rooms and shared files in a project folder.

A project is any folder that holds room folders, either directly or in a
"rooms" folder. A folder that contains room.yaml is a room, so a project can
also be a single room.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from room_planner import merge_furniture

ROOM_FILE = "room.yaml"


def is_room(folder: Path) -> bool:
    return (folder / ROOM_FILE).is_file()


def has_furniture(folder: Path) -> bool:
    return (folder / merge_furniture.OUTPUT_NAME).is_file() or bool(
        merge_furniture.find_sources(folder)
    )


@dataclass(frozen=True)
class Project:
    root: Path

    @classmethod
    def open(cls, folder: Path | None) -> Project:
        """Open a project folder, or the current directory if None."""
        root = (folder or Path.cwd()).expanduser().resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"Project folder not found: {root}")
        return cls(root)

    def rooms(self) -> list[Path]:
        """Return every room folder in the project."""
        if is_room(self.root):
            return [self.root]
        return sorted(
            (
                folder
                for parent in (self.root, self.root / "rooms")
                if parent.is_dir()
                for folder in parent.iterdir()
                if folder.is_dir() and is_room(folder)
            ),
            key=lambda folder: folder.name.lower(),
        )

    def find_room(self, name: str) -> Path:
        """Return the folder of a room given its name or path."""
        folders = {
            folder.resolve()
            for folder in (self.root / name, self.root / "rooms" / name)
            if is_room(folder)
        }
        if len(folders) > 1:
            raise ValueError(
                f"Room {name!r} is ambiguous: "
                + ", ".join(str(folder) for folder in sorted(folders))
            )
        if not folders:
            known = ", ".join(folder.name for folder in self.rooms()) or "none"
            raise FileNotFoundError(
                f"No room named {name!r} in {self.root} (rooms found: {known})"
            )
        return folders.pop()

    def select_rooms(self, names: list[str], every: bool) -> list[Path]:
        """Return the rooms a command should work on."""
        if names:
            return [self.find_room(name) for name in names]
        if every or is_room(self.root):
            rooms = self.rooms()
            if not rooms:
                raise FileNotFoundError(f"No rooms found in {self.root}")
            return rooms
        raise ValueError("Name a room, or use --all to select every room")

    def search_folders(self, room: Path) -> list[Path]:
        """Return where to look for a room's shared files, in order.

        When the project is a room inside a larger project, such as when a
        command is run from a room's folder, the larger project is included.
        """
        folders = [room]
        if self.root != room:
            folders.append(self.root)
        elif has_furniture(room.parent):
            folders.append(room.parent)
        elif room.parent.name == "rooms" and has_furniture(room.parent.parent):
            folders.append(room.parent.parent)
        return folders

    def furniture_folder(self, room: Path) -> Path:
        for folder in self.search_folders(room):
            if has_furniture(folder):
                return folder
        raise FileNotFoundError(
            "No furniture files found; looked in "
            + ", ".join(str(folder) for folder in self.search_folders(room))
        )

    def annotations_file(self, room: Path) -> Path | None:
        for folder in self.search_folders(room):
            path = folder / "annotations.yaml"
            if path.is_file():
                return path
        return None
