"""Test that all MCP references are removed from source code.

This test MUST FAIL before the cleanup (loop.py and dispatch.py still reference bouzecode.mcp).
After removing the dead code blocks, it should pass.
"""
import re
from pathlib import Path

import bouzecode
SRC_DIR = Path(bouzecode.__file__).parent


def test_no_bouzecode_mcp_imports_in_source():
    """No source file should import from bouzecode.mcp (module was deleted)."""
    violations = []
    for py_file in SRC_DIR.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8", errors="ignore")
        for i, line in enumerate(content.splitlines(), 1):
            if re.search(r"\bbouzecode\.mcp\b|from\s+\.+mcp\b", line):
                # Exclude oss_shims which legitimately reference mcp concepts
                rel = str(py_file.relative_to(SRC_DIR))
                if "oss_shims" in rel:
                    continue
                violations.append(f"{rel}:{i}: {line.strip()}")
    assert not violations, (
        "Dead MCP references found in source:\n" + "\n".join(violations)
    )
