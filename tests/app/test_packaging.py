"""What ships in the wheel. Tests run from the source tree, where every data file exists, so a data
file missing from `package-data` is invisible to them and breaks only after `pip install`."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]
PACKAGE = ROOT / "src" / "minifactory"


def shipped():
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text())
    patterns = meta["tool"]["setuptools"]["package-data"]["minifactory"]
    return {p for pattern in patterns for p in PACKAGE.glob(pattern) if p.is_file()}


def test_every_non_python_file_in_the_package_is_declared_as_package_data():
    data_files = {p for p in PACKAGE.rglob("*") if p.is_file() and p.suffix != ".py"
                  and "__pycache__" not in p.parts and p.suffix != ".pyc"}
    missing = sorted(str(p.relative_to(PACKAGE)) for p in data_files - shipped())
    assert not missing, f"not in package-data, so absent from the wheel: {missing}"


def test_the_stack_profiles_and_templates_are_part_of_what_ships():
    names = {p.relative_to(PACKAGE).as_posix() for p in shipped()}
    assert {"profiles/python.yaml", "profiles/node.yaml", "profiles/java.yaml", "profiles/flutter.yaml"} <= names
    assert "templates/app-factory/workflow.yaml" in names and "py.typed" in names


def test_every_python_folder_is_a_package_so_the_wheel_includes_it():
    folders = {p.parent for p in PACKAGE.rglob("*.py")}
    missing = sorted(str(f.relative_to(PACKAGE)) for f in folders if not (f / "__init__.py").exists())
    assert not missing, f"folders with modules but no __init__.py are left out of the wheel: {missing}"
