# [desc] Tests folder description utilities: ignore filtering, code file collection, and description formatting. [/desc]
from pathlib import Path

from bouzecode.backend.tools.folder_desc.desc_utils import _batch_is_ignored
from bouzecode.backend.tools.folder_desc.analyzer import _collect_code_files


def test_batch_is_ignored_skips_always_skip(tmp_path):
    venv_file = tmp_path / ".venv" / "lib" / "foo.py"
    venv_file.parent.mkdir(parents=True)
    venv_file.write_text("x = 1")
    normal = tmp_path / "main.py"
    normal.write_text("x = 1")

    ignored = _batch_is_ignored([venv_file, normal], tmp_path)
    assert venv_file in ignored
    assert normal not in ignored


def test_batch_is_ignored_empty():
    assert _batch_is_ignored([], Path(".")) == set()


def test_collect_code_files_filters_non_code(tmp_path):
    (tmp_path / "readme.md").write_text("# Hi")
    (tmp_path / "data.json").write_text("{}")
    py = tmp_path / "main.py"
    py.write_text("x = 1")

    files = _collect_code_files(tmp_path)
    assert files == [py]


def test_collect_code_files_skips_venv(tmp_path):
    venv = tmp_path / ".venv" / "lib" / "pkg.py"
    venv.parent.mkdir(parents=True)
    venv.write_text("x = 1")
    real = tmp_path / "app.py"
    real.write_text("y = 2")

    files = _collect_code_files(tmp_path)
    assert real in files
    assert venv not in files


def test_collect_code_files_skips_any_dir_with_pyvenv_cfg(tmp_path):
    custom_venv = tmp_path / ".venv-ui"
    (custom_venv / "Lib").mkdir(parents=True)
    (custom_venv / "pyvenv.cfg").write_text("home = /whatever\n")
    venv_file = custom_venv / "Lib" / "pkg.py"
    venv_file.write_text("x = 1")
    real = tmp_path / "app.py"
    real.write_text("y = 2")

    files = _collect_code_files(tmp_path)
    assert real in files
    assert venv_file not in files


def test_collect_code_files_keeps_dir_without_pyvenv_cfg(tmp_path):
    regular = tmp_path / "mylib"
    regular.mkdir()
    inside = regular / "foo.py"
    inside.write_text("x = 1")

    files = _collect_code_files(tmp_path)
    assert inside in files


def test_get_folder_description_skips_described(tmp_path):
    (tmp_path / "a.py").write_text("# [desc] Does A [/desc]\nx = 1\n")
    (tmp_path / "b.py").write_text("# [desc] Does B [/desc]\ny = 2\n")

    from bouzecode.backend.tools.folder_desc.tools import _get_folder_description
    result = _get_folder_description({"folder_path": str(tmp_path)}, {})

    assert "[Auto-analyzed" not in result
    assert "Does A" in result
    assert "Does B" in result


def test_get_folder_description_tree_format(tmp_path):
    sub = tmp_path / "pkg"
    sub.mkdir()
    (tmp_path / "main.py").write_text("# [desc] Entry point [/desc]\n")
    (sub / "util.py").write_text("# [desc] Helpers [/desc]\n")

    from bouzecode.backend.tools.folder_desc.tools import _get_folder_description
    result = _get_folder_description({"folder_path": str(tmp_path)}, {})

    lines = result.strip().splitlines()
    assert tmp_path.name in lines[0]
    assert "Entry point" in result
    assert "Helpers" in result
