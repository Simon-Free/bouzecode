# [desc] Verrou : chaque répertoire de tests est un package, sinon un module de test peut en masquer un autre. [/desc]
"""Every collected test tree must be an unbroken package chain up to an import root.

Why it matters here and not in an ordinary project: this repository keeps flat
packages at its root (`tools/`, `commands/`, `plugin/`, `ui/`, `memory/`, `mcp/`,
`skill/`, `task/`, …) and several directories under `tests/` bear the SAME names.

With `--import-mode=importlib` (set in pyproject) pytest asks
`resolve_pkg_root_and_module_name` for a module name. It walks UP from the test
file while it keeps finding `__init__.py`:

  * unbroken chain  → package root is an import root, module name is fully qualified
    (`tests.backend.tools.registry.test_x`, `bouzecode.backend.tests.test_read_image`)
    — it can shadow nothing;
  * chain broken    → package root is the directory itself and the module name
    collapses to the bare stem (`test_x`), so two identically named test files in
    two different directories overwrite each other in `sys.modules`, and which
    one wins depends on collection order.

Nothing warns when the chain breaks; the symptom is a test that "passes" because
its module was never the one imported. Hence this check.

The roots come from `testpaths` in pyproject, not from a list kept here: four trees under
`src/` joined the collection after years outside it, and a hand-maintained copy would have
gone stale the day a fifth one does. A tree under `src/` stops at `src/` rather than at the
repository root — `src` is a sys.path root (`pythonpath`), so `bouzecode.…` already is a
fully-qualified name.
"""
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]

IGNORED_DIRS = {"__pycache__", ".pytest_cache"}


def _pytest_config() -> dict:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return pyproject["tool"]["pytest"]["ini_options"]


def _import_roots() -> list[Path]:
    """The sys.path entries pytest is given — where a fully-qualified name is anchored."""
    return [(REPO_ROOT / entry).resolve() for entry in _pytest_config()["pythonpath"]]


def _collected_roots() -> list[Path]:
    return [(REPO_ROOT / entry).resolve() for entry in _pytest_config()["testpaths"]]


def _dirs_holding_python_tests() -> list[Path]:
    found = []
    for root in _collected_roots():
        for path in sorted(root.rglob("*.py")):
            if any(part in IGNORED_DIRS for part in path.parts):
                continue
            if path.name.startswith("test_") or path.name == "conftest.py":
                found.append(path.parent)
    return sorted(set(found))


def _import_root_of(directory: Path) -> Path:
    """The first ancestor that is not itself a package — where the module name starts."""
    parent = directory
    while (parent / "__init__.py").exists() and parent != parent.parent:
        parent = parent.parent
    return parent


def test_the_declared_test_roots_all_exist():
    """A typo in `testpaths` silently collects nothing at all."""
    missing = [str(root) for root in _collected_roots() if not root.is_dir()]
    assert missing == [], "testpaths names directories that do not exist:\n  " + \
                          "\n  ".join(missing)


def test_every_test_directory_is_a_package():
    """A directory holding test modules must carry an `__init__.py`."""
    missing = [str(d.relative_to(REPO_ROOT))
               for d in _dirs_holding_python_tests()
               if not (d / "__init__.py").exists()]
    assert missing == [], (
        "These test directories have no __init__.py, so their modules import "
        "under a bare name and can shadow one another:\n  " + "\n  ".join(missing)
    )


def test_the_chain_reaches_an_import_root_without_a_hole():
    """An `__init__.py` deep down is useless if a parent directory lacks one."""
    roots = _import_roots()
    stranded = [f"{d.relative_to(REPO_ROOT)} (chain stops at {_import_root_of(d)})"
                for d in _dirs_holding_python_tests()
                if _import_root_of(d) not in roots]
    assert stranded == [], (
        "The __init__.py chain of these directories does not reach a sys.path root "
        f"({', '.join(str(r) for r in roots)}), so their module names are not fully "
        "qualified:\n  " + "\n  ".join(stranded)
    )
