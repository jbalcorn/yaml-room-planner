"""The room-planner command."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml

from room_planner import generate_room, merge_furniture, render_layout, starter
from room_planner.project import Project

ERRORS = (OSError, ValueError, yaml.YAMLError, ET.ParseError)


def find_furniture(
    project: Project, room: Path, override: Path | None, merged: set[Path] | None
) -> Path:
    """Return the furniture file to use for a room.

    Sources are merged first when 'merged' is given. It holds the folders
    already merged by this command, so that each is merged only once.
    """
    if override is not None and override.is_file():
        return override
    if override is not None and not override.is_dir():
        raise FileNotFoundError(f"Furniture not found: {override}")

    folder = override.resolve() if override else project.furniture_folder(room)
    if merged is not None and folder not in merged:
        if merge_furniture.find_sources(folder):
            print(f"Merged {merge_furniture.merge_folder(folder)}")
        merged.add(folder)

    output = folder / merge_furniture.OUTPUT_NAME
    if not output.is_file():
        raise FileNotFoundError(f"{output} not found; run room-planner merge first")
    return output


def generate(room: Path, scale: float) -> None:
    output = room / "room.svg"
    generate_room.generate(generate_room.load_yaml(room / "room.yaml"), output, scale)
    print(f"Generated {output}")


def for_each_room(rooms: list[Path], action: Callable[[Path], None]) -> int:
    """Run an action on every room, reporting errors without stopping."""
    failed = False
    for room in rooms:
        try:
            action(room)
        except ERRORS as exc:
            failed = True
            print(f"ERROR: {room.name}: {exc}", file=sys.stderr)
    return 1 if failed else 0


def run_build(args: argparse.Namespace) -> int:
    project = Project.open(args.project)
    merged: set[Path] = set()

    def build(room: Path) -> None:
        generate(room, args.scale)
        layout = room / "layout.yaml"
        if not layout.is_file():
            print(f"No layout.yaml in {room}, so no furniture was drawn")
            return
        furniture = find_furniture(project, room, args.furniture, merged)
        output = room / "room_with_furniture.svg"
        render_layout.render(
            room / "room.svg", furniture, layout, project.annotations_file(room), output
        )
        print(f"Wrote {output}")

    return for_each_room(project.select_rooms(args.rooms, args.all), build)


def run_generate(args: argparse.Namespace) -> int:
    rooms = Project.open(args.project).select_rooms(args.rooms, args.all)
    return for_each_room(rooms, lambda room: generate(room, args.scale))


def run_render(args: argparse.Namespace) -> int:
    project = Project.open(args.project)
    rooms = project.select_rooms(args.rooms, args.all)
    if len(rooms) > 1 and (args.layout or args.annotations or args.output):
        raise ValueError("--layout, --annotations, and --output need a single room")
    if args.annotations and not args.annotations.is_file():
        raise FileNotFoundError(f"Annotations not found: {args.annotations}")

    def render(room: Path) -> None:
        furniture = find_furniture(project, room, args.furniture, None)
        layout = args.layout or room / "layout.yaml"
        annotations = args.annotations or project.annotations_file(room)
        if args.validate_only:
            errors = render_layout.validate(
                render_layout.load_yaml(furniture),
                render_layout.load_yaml(layout),
                render_layout.load_optional_annotations(annotations),
            )
            if errors:
                raise ValueError("\n".join(errors))
            print(f"{room.name}: YAML validation passed")
            return
        svg = room / "room.svg"
        if not svg.is_file():
            raise FileNotFoundError(f"{svg} not found; run room-planner generate first")
        output = args.output or room / "room_with_furniture.svg"
        render_layout.render(svg, furniture, layout, annotations, output)
        print(f"Wrote {output}")

    return for_each_room(rooms, render)


def run_merge(args: argparse.Namespace) -> int:
    folder = Project.open(args.project).root
    for path in merge_furniture.find_sources(folder):
        print(path)
    print(f"Merged {merge_furniture.merge_folder(folder, force=args.force)}")
    return 0


def run_init(args: argparse.Namespace) -> int:
    folder = args.folder.expanduser().resolve()
    room = args.room or (folder.name if args.single else "living")
    for path in starter.create(folder, room, single=args.single):
        print(f"Created {path}")
    return 0


def positive(value: str) -> float:
    number = float(value)
    if not 0 < number < float("inf"):
        raise argparse.ArgumentTypeError("must be positive")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="room-planner",
        description="Draw rooms and furniture layouts as SVG from YAML.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    # Options shared by several commands
    project = argparse.ArgumentParser(add_help=False)
    project.add_argument(
        "-p", "--project", type=Path, metavar="DIR",
        help="project folder (default: current directory)",
    )
    rooms = argparse.ArgumentParser(add_help=False)
    rooms.add_argument(
        "rooms", nargs="*", metavar="ROOM",
        help="room name; not needed when the project is a single room",
    )
    rooms.add_argument("--all", action="store_true", help="every room in the project")
    scale = argparse.ArgumentParser(add_help=False)
    scale.add_argument(
        "--scale", type=positive, default=3.0, help="SVG units per inch (default: 3)"
    )
    furniture = argparse.ArgumentParser(add_help=False)
    furniture.add_argument(
        "--furniture", type=Path, metavar="PATH",
        help="furniture file, or folder of furniture files",
    )

    def add(name, function, summary, *parents):
        command = commands.add_parser(
            name, help=summary, description=summary, parents=parents
        )
        command.set_defaults(function=function)
        return command

    add("build", run_build, "Merge furniture, then generate and render rooms.",
        project, rooms, scale, furniture)
    add("generate", run_generate, "Draw room.svg from room.yaml.",
        project, rooms, scale)

    render = add("render", run_render, "Draw furniture and annotations onto room.svg.",
                 project, rooms, furniture)
    render.add_argument("--layout", type=Path, help="use another layout file")
    render.add_argument("--annotations", type=Path, help="use another annotations file")
    render.add_argument("--output", type=Path, help="write to another SVG file")
    render.add_argument(
        "--validate-only", action="store_true",
        help="check the YAML without writing an SVG",
    )

    merge = add("merge", run_merge, "Merge furniture_*.yaml into furniture.yaml.", project)
    merge.add_argument(
        "--force", action="store_true",
        help="overwrite a furniture.yaml that room-planner did not generate",
    )

    init = add("init", run_init, "Create a starter project.")
    init.add_argument("folder", type=Path, help="folder to create the project in")
    init.add_argument(
        "--room",
        help="first room's name (default: living, or the folder's name with --single)",
    )
    init.add_argument(
        "--single", action="store_true", help="put one room at the top of the project"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.function(args)
    except ERRORS as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
