# [desc] Codebase-wide guard: every src file must compile, and every lazy/eager `from bouzecode.* import NAME` must resolve to a real attribute or submodule. [/desc]
"""Turns the safety net that eager (module-level) imports would give us into a test,
without physically hoisting the ~300 in-function imports that exist to break cycles.

`test_import_targets_resolve.py` checks the *module* of each import exists. This goes
further and catches the two failure modes that only eager imports would surface:
  1. Syntax errors in modules that no test ever imports (we compile every file).
  2. Forgotten / renamed *symbols* — `from x import Renamed` where the module is fine
     but `Renamed` no longer exists (find_spec can't see this).
"""
import ast
import importlib
import importlib.util
from pathlib import Path

import bouzecode

SRC_ROOT = Path(bouzecode.__file__).parent


def _module_exists(dotted: str) -> bool:
    try:
        return importlib.util.find_spec(dotted) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def _bouzecode_from_imports(tree: ast.AST):
    """Yield (module, name, lineno) for every `from bouzecode.* import name` (lazy or not)."""
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ImportFrom) and node.level == 0 and node.module):
            continue
        if node.module != "bouzecode" and not node.module.startswith("bouzecode."):
            continue
        for alias in node.names:
            if alias.name != "*":
                yield node.module, alias.name, node.lineno


def _symbol_resolves(module: str, name: str) -> bool:
    """True if `name` is an attribute of `module`, or `module.name` is itself a submodule."""
    if not _module_exists(module):
        return False
    try:
        mod = importlib.import_module(module)
    except ModuleNotFoundError as exc:
        # A real module that fails only because of a missing optional 3rd-party dep
        # is not what this guard is about — the module path itself is valid.
        return not (exc.name or "").startswith("bouzecode")
    except Exception:
        return False
    if hasattr(mod, name):
        return True
    return _module_exists(f"{module}.{name}")


def test_all_source_files_compile():
    """No syntax errors anywhere under src/bouzecode — even in modules nothing imports."""
    errors = []
    for path in SRC_ROOT.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        try:
            compile(source, str(path), "exec")
        except SyntaxError as exc:
            errors.append(f"{path.relative_to(SRC_ROOT.parent)}:{exc.lineno}: {exc.msg}")
    assert not errors, "Syntax errors:\n" + "\n".join(errors)


def test_all_bouzecode_import_symbols_resolve():
    """Every `from bouzecode.* import NAME` target resolves (catches renamed/forgotten exports)."""
    failures = []
    for path in SRC_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module, name, lineno in _bouzecode_from_imports(tree):
            if not _symbol_resolves(module, name):
                rel = path.relative_to(SRC_ROOT.parent)
                failures.append(f"{rel}:{lineno} -> from {module} import {name}")
    assert not failures, (
        "Unresolvable import symbols (renamed module or forgotten export):\n"
        + "\n".join(sorted(set(failures)))
    )
