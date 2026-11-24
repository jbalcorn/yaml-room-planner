"""The committed sample house must match what room-planner produces now.

If a drawing change is intentional, rebuild the sample house as described in
README.md and commit the new files.
"""

import shutil

from room_planner.cli import main


def test_sample_house_is_current(repo_root, tmp_path):
    committed = repo_root / "examples" / "house"
    house = tmp_path / "house"
    shutil.copytree(
        committed, house, ignore=shutil.ignore_patterns("*.svg", "furniture.yaml")
    )

    assert main(["build", "--all", "--project", str(house)]) == 0

    def contents(folder):
        # read_text ignores platform line endings
        return {
            path.relative_to(folder).as_posix(): path.read_text(encoding="utf-8")
            for path in folder.rglob("*")
            if path.is_file()
        }

    assert contents(house) == contents(committed)
