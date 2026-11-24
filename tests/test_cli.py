import shutil

import pytest
import yaml

from room_planner import merge_furniture, starter
from room_planner.cli import main
from room_planner.project import Project


def add_room(folder, *, layout=starter.LAYOUT):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "room.yaml").write_text(starter.ROOM % {"name": folder.name}, encoding="utf-8")
    if layout:
        (folder / "layout.yaml").write_text(layout, encoding="utf-8")
    return folder


def add_furniture(folder):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "furniture_all.yaml").write_text(starter.FURNITURE, encoding="utf-8")


def add_annotation(folder, text):
    data = {"annotations": [{"id": "A", "type": "label", "text": text, "x": 1, "y": 1}]}
    (folder / "annotations.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


def drawing(room):
    return (room / "room_with_furniture.svg").read_text(encoding="utf-8")


@pytest.fixture
def house(tmp_path, monkeypatch):
    """A house with two rooms, with the current directory somewhere else."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    root = tmp_path / "house"
    add_furniture(root)
    add_room(root / "living")
    add_room(root / "bedroom")
    return root


# --- building -----------------------------------------------------------


def test_build_one_room_from_another_directory(house):
    assert main(["build", "living", "--project", str(house)]) == 0

    assert 'data-object="Sofa84"' in drawing(house / "living")
    assert not (house / "bedroom" / "room.svg").exists()
    assert list((house.parent / "elsewhere").iterdir()) == []


def test_build_uses_the_current_directory_by_default(house, monkeypatch):
    monkeypatch.chdir(house)
    assert main(["build", "living"]) == 0
    assert drawing(house / "living")


def test_build_all_merges_furniture_once(house, capsys):
    assert main(["build", "--all", "-p", str(house)]) == 0

    assert drawing(house / "living") and drawing(house / "bedroom")
    assert capsys.readouterr().out.count("Merged") == 1


def test_rooms_folder_is_supported(tmp_path):
    add_furniture(tmp_path)
    room = add_room(tmp_path / "rooms" / "den")

    assert main(["build", "den", "-p", str(tmp_path)]) == 0
    assert drawing(room)


def test_single_room_project(tmp_path):
    add_furniture(tmp_path)
    add_room(tmp_path)

    assert main(["build", "-p", str(tmp_path)]) == 0
    assert drawing(tmp_path)


@pytest.mark.parametrize("path", ["den", "rooms/den"])
def test_build_from_a_room_folder_uses_the_house_furniture(tmp_path, monkeypatch, path):
    add_furniture(tmp_path)
    room = add_room(tmp_path / path)
    add_annotation(tmp_path, "house note")
    monkeypatch.chdir(room)

    assert main(["build"]) == 0
    assert "house note" in drawing(room)


def test_room_without_a_layout_is_only_generated(house, capsys):
    (house / "living" / "layout.yaml").unlink()

    assert main(["build", "living", "-p", str(house)]) == 0
    assert (house / "living" / "room.svg").exists()
    assert not (house / "living" / "room_with_furniture.svg").exists()
    assert "No layout.yaml" in capsys.readouterr().out


def test_one_bad_room_does_not_stop_the_others(house, capsys):
    (house / "bedroom" / "room.yaml").write_text("room: {", encoding="utf-8")

    assert main(["build", "--all", "-p", str(house)]) == 1
    assert drawing(house / "living")
    assert "ERROR: bedroom" in capsys.readouterr().err


def test_scale(house):
    main(["build", "living", "-p", str(house), "--scale", "2"])
    assert 'data-scale="2"' in drawing(house / "living")


@pytest.mark.parametrize("scale", ["0", "-1", "nan", "inf", "big"])
def test_bad_scale_is_rejected(house, scale):
    with pytest.raises(SystemExit):
        main(["build", "living", "-p", str(house), f"--scale={scale}"])


# --- furniture and annotations ------------------------------------------


def test_room_furniture_is_preferred(house):
    (house / "living" / "furniture_own.yaml").write_text(
        starter.FURNITURE.replace("length: 84", "length: 60"), encoding="utf-8"
    )

    main(["build", "living", "-p", str(house)])

    assert 'width="180.00"' in drawing(house / "living")
    assert not (house / "furniture.yaml").exists()


def test_hand_written_catalog_is_used_as_is(house):
    (house / "furniture_all.yaml").rename(house / "furniture.yaml")

    assert main(["build", "living", "-p", str(house)]) == 0
    assert (house / "furniture.yaml").read_text(encoding="utf-8") == starter.FURNITURE


def test_hand_written_catalog_is_protected(house, capsys):
    (house / "furniture.yaml").write_text("objects: {}", encoding="utf-8")

    assert main(["build", "living", "-p", str(house)]) == 1
    assert "merge --force" in capsys.readouterr().err
    assert main(["merge", "--force", "-p", str(house)]) == 0
    assert main(["build", "living", "-p", str(house)]) == 0


@pytest.mark.parametrize("as_folder", [True, False])
def test_furniture_can_be_shared_between_projects(tmp_path, as_folder):
    shared = tmp_path / "shared"
    add_furniture(shared)
    room = add_room(tmp_path / "den")
    path = shared if as_folder else shared / "furniture_all.yaml"

    assert main(["build", "-p", str(room), "--furniture", str(path)]) == 0
    assert drawing(room)


def test_room_annotations_are_preferred(house):
    add_annotation(house, "house note")
    main(["build", "living", "-p", str(house)])
    assert "house note" in drawing(house / "living")

    add_annotation(house / "living", "room note")
    main(["build", "living", "-p", str(house)])
    assert "room note" in drawing(house / "living")
    assert "house note" not in drawing(house / "living")


# --- separate steps -----------------------------------------------------


def test_separate_steps_match_build(house, tmp_path):
    copy = tmp_path / "copy"
    shutil.copytree(house, copy)
    main(["build", "living", "-p", str(house)])

    assert main(["merge", "-p", str(copy)]) == 0
    assert main(["generate", "living", "-p", str(copy)]) == 0
    assert main(["render", "living", "-p", str(copy)]) == 0

    assert drawing(copy / "living") == drawing(house / "living")


def test_alternative_layout_and_output(house, tmp_path):
    main(["build", "living", "-p", str(house)])
    original = drawing(house / "living")
    layout = tmp_path / "other.yaml"
    layout.write_text("placements: []", encoding="utf-8")
    output = tmp_path / "other.svg"

    assert main(["render", "living", "-p", str(house),
                 "--layout", str(layout), "--output", str(output)]) == 0
    assert "Sofa84" not in output.read_text(encoding="utf-8")
    assert drawing(house / "living") == original


def test_validate_only_writes_nothing(house, capsys):
    main(["merge", "-p", str(house)])
    before = sorted(house.rglob("*"))

    assert main(["render", "--all", "--validate-only", "-p", str(house)]) == 0
    (house / "living" / "layout.yaml").write_text(
        "placements: [{id: A, object: Throne, x: 1, y: 1}]", encoding="utf-8"
    )
    assert main(["render", "living", "--validate-only", "-p", str(house)]) == 1

    assert "unknown object 'Throne'" in capsys.readouterr().err
    assert sorted(house.rglob("*")) == before


# --- mistakes -----------------------------------------------------------


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["build"], "use --all"),
        (["build", "attic"], "rooms found: bedroom, living"),
        (["build", "living", "--furniture", "missing.yaml"], "Furniture not found"),
        (["render", "living"], "run room-planner merge"),
        (["render", "--all", "--output", "x.svg"], "need a single room"),
        (["render", "living", "--annotations", "missing.yaml"], "Annotations not found"),
    ],
)
def test_mistakes_are_explained(house, capsys, args, message):
    assert main([*args, "-p", str(house)]) == 1
    assert message in capsys.readouterr().err


def test_render_needs_a_generated_room(house, capsys):
    main(["merge", "-p", str(house)])
    assert main(["render", "living", "-p", str(house)]) == 1
    assert "run room-planner generate" in capsys.readouterr().err


def test_missing_furniture_is_explained(tmp_path, capsys):
    add_room(tmp_path / "den")
    assert main(["build", "den", "-p", str(tmp_path)]) == 1
    assert "No furniture files found" in capsys.readouterr().err


def test_missing_project_is_explained(tmp_path, capsys):
    assert main(["build", "--all", "-p", str(tmp_path / "nowhere")]) == 1
    assert "Project folder not found" in capsys.readouterr().err


def test_empty_project_is_explained(tmp_path, capsys):
    assert main(["build", "--all", "-p", str(tmp_path)]) == 1
    assert "No rooms found" in capsys.readouterr().err


def test_ambiguous_room_is_rejected(house):
    add_room(house / "rooms" / "living")
    with pytest.raises(ValueError, match="ambiguous"):
        Project.open(house).find_room("living")


# --- starter projects ---------------------------------------------------


def test_starter_house_builds(tmp_path):
    house = tmp_path / "new" / "house"

    assert main(["init", str(house)]) == 0
    assert main(["build", "living", "-p", str(house)]) == 0
    assert drawing(house / "living")


def test_starter_single_room_builds(tmp_path):
    room = tmp_path / "den"

    assert main(["init", str(room), "--single"]) == 0
    assert main(["build", "-p", str(room)]) == 0
    assert "den" in drawing(room)


@pytest.mark.parametrize("name", ["no", "101"])
def test_starter_room_name_stays_text(tmp_path, name):
    main(["init", str(tmp_path), "--room", name])
    room = yaml.safe_load((tmp_path / name / "room.yaml").read_text(encoding="utf-8"))
    assert room["room"]["name"] == name


def test_starter_overwrites_nothing(tmp_path, capsys):
    (tmp_path / "furniture_starter.yaml").write_text("mine", encoding="utf-8")

    assert main(["init", str(tmp_path)]) == 1
    assert "already exist" in capsys.readouterr().err
    assert [p.name for p in tmp_path.iterdir()] == ["furniture_starter.yaml"]


@pytest.mark.parametrize("name", ["../x", "a b", "a/b", "-"])
def test_bad_starter_names_are_rejected(tmp_path, name):
    assert main(["init", str(tmp_path / "p"), f"--room={name}"]) == 1
    assert not (tmp_path / "p").exists()


def test_generated_warning_is_recognized():
    assert merge_furniture.HEADER.startswith(merge_furniture.WARNING)
