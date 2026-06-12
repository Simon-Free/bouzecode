"""
Test that ALL lazy imports inside command handler functions resolve correctly.

Scans every .py file under src/bouzecode/backend/commands/, extracts import
statements that live inside function bodies (lazy imports), and attempts to
execute each one. This catches ModuleNotFoundError early — the kind of bug
where a module is moved/renamed but a rarely-hit code path still references
the old location.
"""

import ast
import importlib
import pathlib
import sys
from typing import List, Tuple

import pytest

COMMANDS_DIR = (
    pathlib.Path(__file__).resolve().parents[4]
    / "src"
    / "bouzecode"
    / "backend"
    / "commands"
)


def _collect_lazy_imports() -> List[Tuple[str, int, str]]:
    """
    Walk all .py files under commands/ and return a list of
    (file_relative_path, lineno, import_module_path) for every import
    statement found inside a function or method body.
    """
    results: List[Tuple[str, int, str]] = []

    for py_file in sorted(COMMANDS_DIR.rglob("*.py")):
        source = py_file.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            continue

        rel = py_file.relative_to(COMMANDS_DIR)

        for node in ast.walk(tree):
            # Only look inside function/method bodies
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            for child in ast.walk(node):
                if isinstance(child, ast.ImportFrom):
                    if child.module is None:
                        continue
                    # Resolve relative imports based on the package of the file
                    if child.level > 0:
                        # Compute the package path of this file
                        pkg_parts = list(py_file.relative_to(
                            COMMANDS_DIR.parents[2]  # src/
                        ).parts)
                        # Remove filename to get package parts
                        pkg_parts = pkg_parts[:-1]  # e.g. ['bouzecode','backend','commands','info']
                        # Go up `level` packages:
                        # level=1 means current package, level=2 means parent, etc.
                        base_parts = pkg_parts[: len(pkg_parts) - child.level + 1]
                        if child.module:
                            full_module = ".".join(base_parts) + "." + child.module
                        else:
                            full_module = ".".join(base_parts)
                    else:
                        full_module = child.module

                    # Collect each imported name
                    for alias in child.names:
                        results.append((
                            str(rel),
                            child.lineno,
                            f"{full_module}.{alias.name}" if alias.name != "*" else full_module,
                        ))

                elif isinstance(child, ast.Import):
                    for alias in child.names:
                        # Mark ast.Import entries so we import the full dotted path
                        # directly (handles stdlib sub-modules like urllib.request)
                        results.append((str(rel), child.lineno, f"__direct__:{alias.name}"))

    return results


_LAZY_IMPORTS = _collect_lazy_imports()

# Modules that are optional dependencies — skip if not installed
_OPTIONAL_MODULES = {"PIL", "PIL.ImageGrab"}


@pytest.mark.parametrize(
    "file_rel,lineno,module_path",
    _LAZY_IMPORTS,
    ids=[f"{f}:L{ln}:{m}" for f, ln, m in _LAZY_IMPORTS],
)
def test_lazy_import_resolves(file_rel: str, lineno: int, module_path: str):
    """Each lazy import inside a command handler must resolve without error."""

    # Handle ast.Import entries (direct full-path imports like 'import urllib.request')
    if module_path.startswith("__direct__:"):
        direct_mod = module_path.removeprefix("__direct__:")
        if direct_mod.split(".")[0] in _OPTIONAL_MODULES or direct_mod in _OPTIONAL_MODULES:
            pytest.skip(f"Optional dependency: {direct_mod}")
        try:
            importlib.import_module(direct_mod)
        except ModuleNotFoundError as exc:
            pytest.fail(
                f"{file_rel}:{lineno} — lazy import failed: {exc}\n"
                f"  Attempted: import {direct_mod}"
            )
        return

    # We try to import the module part (everything up to the last dot which is
    # the attribute/name being imported from)
    parts = module_path.rsplit(".", 1)
    module_to_import = parts[0]
    attr_name = parts[1] if len(parts) > 1 else None

    # Skip optional dependencies
    top_level = module_to_import.split(".")[0]
    if top_level in _OPTIONAL_MODULES or module_to_import in _OPTIONAL_MODULES:
        pytest.skip(f"Optional dependency: {module_to_import}")

    try:
        mod = importlib.import_module(module_to_import)
    except ModuleNotFoundError as exc:
        pytest.fail(
            f"{file_rel}:{lineno} — lazy import failed: {exc}\n"
            f"  Attempted: import {module_to_import}"
        )

    if attr_name:
        try:
            has = hasattr(mod, attr_name)
        except Exception as exc:
            # e.g. PackageNotFoundError when bouzecode is not pip-installed
            if "PackageNotFoundError" in type(exc).__name__ or "metadata" in str(exc):
                pytest.skip(f"Package not installed in editable mode: {exc}")
            raise
        if not has:
            pytest.fail(
                f"{file_rel}:{lineno} — attribute '{attr_name}' not found in '{module_to_import}'\n"
                f"  Available: {', '.join(a for a in dir(mod) if not a.startswith('_'))}"
            )
