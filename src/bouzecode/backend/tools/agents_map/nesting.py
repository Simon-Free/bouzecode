# [desc] Checks call-graph nesting against the AST: an indented call must really be made by its parent. [/desc]
from __future__ import annotations

import ast
import re
from pathlib import Path

_TREE_LINE = re.compile(r"^(?P<indent>[\s│]*)[├└]─(?P<call>─)?\s*(?P<name>[A-Za-z_]\w*)?")
_ROOT_LINE = re.compile(r"^(?P<name>[A-Za-z_]\w*)\s*\(")


def calls_made_by(folder: Path) -> dict[str, set[str]]:
    """``{function name: names it calls}`` over the folder's own Python files.

    A name defined twice in the folder merges its call sets — an over-approximation,
    which is the right bias: it never rejects a real edge.
    """
    out: dict[str, set[str]] = {}
    for path in sorted(folder.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        aliases = _aliases(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            called = out.setdefault(node.name, set())
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call):
                    continue
                fn = sub.func
                name = fn.id if isinstance(fn, ast.Name) else (
                    fn.attr if isinstance(fn, ast.Attribute) else None)
                if name:
                    called.add(name)
                    called.add(aliases.get(name, name))
    return out


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else None


def nested_as_arguments(folder: Path) -> dict[str, set[str]]:
    """``{callee: names computed inside its own argument list}``.

    ``_atomic_write(doc, compose(x))`` reads, to any reader, as compose feeding
    _atomic_write — so a map that nests compose under it is not lying, even
    though the enclosing function is the real caller. Judged separately rather
    than reported as an invented edge.
    """
    out: dict[str, set[str]] = {}
    for path in sorted(folder.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            outer = _call_name(node.func)
            if not outer:
                continue
            bucket = out.setdefault(outer, set())
            for arg in list(node.args) + [kw.value for kw in node.keywords]:
                for sub in ast.walk(arg):
                    if isinstance(sub, ast.Call):
                        inner = _call_name(sub.func)
                        if inner:
                            bucket.add(inner)
    return out


def _aliases(tree: ast.AST) -> dict[str, str]:
    """``{local alias: original name}`` — ``import x as _x`` must not read as a
    different function, or an honest call graph gets rejected for naming the real one."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.asname:
                    out[alias.asname] = alias.name.rsplit(".", 1)[-1]
    return out


def wrong_nesting(md: str, folder: Path) -> list[str]:
    """Indented edges the AST contradicts: parent P shown calling C, but never does.

    Control-flow labels (``├─ [if ...]``) are part of the tree but are not calls:
    a call nested under a label belongs to the label's enclosing CALL, not to the
    call that happened to print above it. Only edges whose two ends are both
    defined in this folder are judged — a call into another module is left alone.
    """
    known = calls_made_by(folder)
    as_args = nested_as_arguments(folder)
    stack: list[tuple[int, str | None]] = []
    bad: list[str] = []
    for line in md.splitlines():
        root = _ROOT_LINE.match(line.rstrip())
        if root:
            # A new tree starts: its head is the caller of everything below it.
            stack = [(-1, root.group("name"))]
            continue
        m = _TREE_LINE.match(line.rstrip())
        if not m:
            continue
        depth = len(m.group("indent"))
        name = m.group("name") if m.group("call") else None
        while stack and stack[-1][0] >= depth:
            stack.pop()
        if name:
            parent = next((n for _, n in reversed(stack) if n), None)
            if (
                parent in known and name in known
                and name not in known[parent]
                and name not in as_args.get(parent, ())
            ):
                bad.append(f"{parent}() is shown calling {name}(), but its body never does")
        stack.append((depth, name))
    return bad
