"""Root conftest — ensure src-layout package resolution.

Without this, bouzecode.py (legacy CLI at repo root) shadows the
src/bouzecode/ package when pytest adds the rootdir to sys.path.
"""
import sys
from pathlib import Path

_root = str(Path(__file__).resolve().parent)
_src = str(Path(__file__).resolve().parent / "src")

# 1. Remove rootdir from sys.path so bouzecode.py cannot shadow the package
while _root in sys.path:
    sys.path.remove(_root)

# 2. Ensure src/ is first
if _src not in sys.path:
    sys.path.insert(0, _src)
elif sys.path[0] != _src:
    sys.path.remove(_src)
    sys.path.insert(0, _src)

# 3. Purge any already-loaded non-package 'bouzecode' module
for _key in list(sys.modules):
    if _key == "bouzecode" or _key.startswith("bouzecode."):
        _mod = sys.modules[_key]
        if _key == "bouzecode" and not hasattr(_mod, "__path__"):
            del sys.modules[_key]
