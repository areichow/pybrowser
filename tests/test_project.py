from pathlib import Path
from pybrowser.project import discover_modules, dotted_module_name, open_world


def test_discovers_packages_and_excludes_generated_directories(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("")
    (tmp_path / "app" / "main.py").write_text("VALUE = 1\n")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "ignored.py").write_text("")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "ignored.py").write_text("")
    entries = discover_modules(tmp_path)
    assert [item.relative_path.as_posix() for item in entries] == ["app/__init__.py", "app/main.py"]
    assert [item.dotted_name for item in entries] == ["app", "app.main"]


def test_dotted_name_for_root_module(tmp_path):
    path = tmp_path / "config.py"
    path.write_text("")
    assert dotted_module_name(tmp_path, path) == "config"


def test_single_file_world(tmp_path):
    path = tmp_path / "one.py"
    path.write_text("x = 1\n")
    world = open_world(path)
    assert world.single_file
    assert world.modules[0].path == path.resolve()
