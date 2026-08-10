# [desc] Verrou : chaque répertoire de tests est un package, sinon un module de test peut en masquer un autre. [/desc]
"""The `tests/` tree must be an unbroken package chain.

Why it matters here and not in an ordinary project: this repository keeps flat
packages at its root (`tools/`, `commands/`, `plugin/`, `ui/`, `memory/`, `mcp/`,
`skill/`, `task/`, …) and several directories under `tests/` bear the SAME names.

With `--import-mode=importlib` (set in pyproject) pytest asks
`resolve_pkg_root_and_module_name` for a module name. It walks UP from the test
file while it keeps finding `__init__.py`:

  * unbroken chain  → package root is the repo, module name is fully qualified
    (`tests.backend.tools.registry.test_x`) — it can shadow nothing;
  * chain broken    → package root is the directory itself and the module name
    collapses to the bare stem (`test_x`), so two identically named test files in
    two different directories overwrite each other in `sys.modules`, and which
    one wins depends on collection order.

Nothing warns when the chain breaks; the symptom is a test that "passes" because
its module was never the one imported. Hence this check.
"""
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parents[3]

IGNORED_DIRS = {"__pycache__", ".pytest_cache"}


def _dirs_holding_python_tests() -> list[Path]:
    found = []
    for path in sorted(TESTS_ROOT.rglob("*.py")):
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        if path.name.startswith("test_") or path.name == "conftest.py":
            found.append(path.parent)
    return sorted(set(found))


def test_every_test_directory_is_a_package():
    """A directory holding test modules must carry an `__init__.py`."""
    missing = [str(d.relative_to(TESTS_ROOT.parent))
               for d in _dirs_holding_python_tests()
               if not (d / "__init__.py").exists()]
    assert missing == [], (
        "These test directories have no __init__.py, so their modules import "
        "under a bare name and can shadow one another:\n  " + "\n  ".join(missing)
    )


def test_the_chain_reaches_the_tests_package_without_a_hole():
    """An `__init__.py` deep down is useless if a parent directory lacks one."""
    holes = []
    for directory in _dirs_holding_python_tests():
        parent = directory
        while parent != TESTS_ROOT:
            if not (parent / "__init__.py").exists():
                holes.append(str(parent.relative_to(TESTS_ROOT.parent)))
            parent = parent.parent
    assert sorted(set(holes)) == [], (
        "The package chain up to tests/ is broken at:\n  " + "\n  ".join(sorted(set(holes)))
    )
