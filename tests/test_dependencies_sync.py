from pathlib import Path

import tomllib


def test_project_dependencies_match_requirements():
    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text("utf-8"))
    pyproject_deps = set(pyproject["project"]["dependencies"])

    with (root / "requirements.txt").open() as req_file:
        requirements = {
            line.strip()
            for line in req_file
            if line.strip() and not line.startswith("#")
        }

    assert pyproject_deps == requirements
