# [desc] AST sweep verifying every `bouzecode.*` import target in source files resolves to a real module
# <tool_use name="FinalAnswer" id="f1"><param name="answer">AST sweep verifying every `bouzecode.*` import target in source files resolves to a real module</param></tool_use> [/desc]
"""Guard against stale import paths that slip past module-level smoke tests.

Function-local (lazy) imports — e.g. `from bouzecode.backend.core.context_manager
import ContextState` inside a command handler — are NOT executed when the module is
imported, so they only blow up at runtime (here: at `/resume`). This test parses
the AST of every source file and asserts each absolute `bouzecode.*` import target
exists, catching renamed/moved modules without running the code.
"""
import ast
import importlib.util

import bouzecode
from pathlib import Path

SRC_ROOT = Path(bouzecode.__file__).parent


def _bouzecode_import_targets(tree: ast.AST):
    """Yield every absolute `bouzecode.*` module referenced by import statements."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module == "bouzecode" or node.module.startswith("bouzecode."):
                yield node.module, node.lineno
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "bouzecode" or alias.name.startswith("bouzecode."):
                    yield alias.name, node.lineno


def _module_exists(dotted: str) -> bool:
    """True if `dotted` is importable without executing the importing module."""
    try:
        return importlib.util.find_spec(dotted) is not None
    except (ImportError, AttributeError, ValueError):
        # ModuleNotFoundError on a missing parent package also lands here.
        return False


# Lazy imports guarded by try/except or runtime checks — not expected to resolve statically
KNOWN_UNRESOLVABLE = {"bouzecode.web"}


def test_all_bouzecode_import_targets_resolve():
    failures = []
    for path in SRC_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module, lineno in _bouzecode_import_targets(tree):
            if module in KNOWN_UNRESOLVABLE:
                continue
            if not _module_exists(module):
                rel = path.relative_to(SRC_ROOT.parent)
                failures.append(f"{rel}:{lineno} -> {module}")

    assert not failures, "Stale/unresolvable bouzecode import targets:\n" + "\n".join(
        sorted(failures)
    )
