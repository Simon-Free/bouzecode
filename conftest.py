"""Root conftest — ensure src-layout package resolution.

Without this, bouzecode.py (legacy CLI at repo root) shadows the
src/bouzecode/ package when pytest adds the rootdir to sys.path.

Strategy: keep rootdir in sys.path (needed for flat OSS modules like memory,
voice, etc.) but ensure src/ comes FIRST so that `import bouzecode` resolves
to the package in src/bouzecode/ rather than bouzecode.py.
"""
import sys
from pathlib import Path

_src = str(Path(__file__).resolve().parent / "src")

# Ensure src/ is at position 0 (before rootdir)
if _src in sys.path:
    sys.path.remove(_src)
sys.path.insert(0, _src)

# Purge any already-loaded non-package 'bouzecode' module (script, not package)
_mod = sys.modules.get("bouzecode")
if _mod is not None and not hasattr(_mod, "__path__"):
    del sys.modules["bouzecode"]
