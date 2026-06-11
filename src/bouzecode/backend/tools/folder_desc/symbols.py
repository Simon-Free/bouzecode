# [desc] Symbol extraction (Python via ast, JS/TS via tree-sitter) and symbol lookup for source files. [/desc]
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Symbol:
    name: str
    kind: str  # "def", "class", "function"
    docstring: str | None
    start_line: int  # 1-based
    end_line: int  # 1-based inclusive
    children: list[Symbol] = field(default_factory=list)


_SYMBOL_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx"}


def extract_symbols(file_path: str, content: str | None = None) -> list[Symbol]:
    ext = Path(file_path).suffix.lower()
    if ext not in _SYMBOL_EXTS:
        return []
    if content is None:
        content = Path(file_path).read_text(encoding="utf-8", errors="replace")
    if ext == ".py":
        return _extract_python(content)
    return _extract_js_ts(content, ext)


def find_symbol(
    file_path: str, symbol_name: str, content: str | None = None,
) -> tuple[int, int] | None:
    """Find symbol by name and return (start_line, end_line) 1-based inclusive."""
    symbols = extract_symbols(file_path, content)
    parts = symbol_name.split(".", 1)
    for sym in symbols:
        if sym.name == parts[0]:
            if len(parts) == 1:
                return sym.start_line, sym.end_line
            for child in sym.children:
                if child.name == parts[1]:
                    return child.start_line, child.end_line
    return None


# -- Python (stdlib ast) --------------------------------------------------

def _first_docline(node) -> str | None:
    doc = ast.get_docstring(node)
    if not doc:
        return None
    return doc.split("\n")[0].strip()[:100]


def _extract_python(content: str) -> list[Symbol]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []
    symbols: list[Symbol] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(Symbol(
                name=node.name, kind="def", docstring=_first_docline(node),
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
            ))
        elif isinstance(node, ast.ClassDef):
            methods: list[Symbol] = []
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.append(Symbol(
                        name=child.name, kind="def",
                        docstring=_first_docline(child),
                        start_line=child.lineno,
                        end_line=child.end_lineno or child.lineno,
                    ))
            symbols.append(Symbol(
                name=node.name, kind="class", docstring=_first_docline(node),
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
                children=methods,
            ))
    return symbols


# -- JS/TS (tree-sitter) --------------------------------------------------

def _extract_js_ts(content: str, ext: str) -> list[Symbol]:
    try:
        import tree_sitter_javascript as ts_js
        import tree_sitter_typescript as ts_ts
        from tree_sitter import Language, Parser
    except ImportError:
        return []
    if ext in (".ts", ".tsx"):
        lang_fn = ts_ts.language_typescript if ext == ".ts" else ts_ts.language_tsx
        lang = Language(lang_fn())
    else:
        lang = Language(ts_js.language())
    parser = Parser(lang)
    tree = parser.parse(content.encode())
    symbols: list[Symbol] = []
    for node in tree.root_node.children:
        sym = _js_node_to_symbol(node, content)
        if sym:
            symbols.append(sym)
    return symbols


def _js_jsdoc(node, content: str) -> str | None:
    prev = node.prev_named_sibling
    if prev and prev.type == "comment":
        text = content[prev.start_byte:prev.end_byte]
        for line in text.split("\n"):
            cleaned = line.strip().lstrip("/*").lstrip("*").strip()
            if cleaned and not cleaned.startswith("@") and cleaned != "/":
                return cleaned[:100]
    return None


def _js_field_name(node, content: str) -> str | None:
    n = node.child_by_field_name("name")
    return content[n.start_byte:n.end_byte] if n else None


def _js_node_to_symbol(node, content: str) -> Symbol | None:
    if node.type in ("function_declaration", "generator_function_declaration"):
        name = _js_field_name(node, content)
        if not name:
            return None
        return Symbol(
            name=name, kind="function", docstring=_js_jsdoc(node, content),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )

    if node.type == "class_declaration":
        name = _js_field_name(node, content)
        if not name:
            return None
        methods: list[Symbol] = []
        body = node.child_by_field_name("body")
        if body:
            for child in body.children:
                if child.type == "method_definition":
                    m_name = _js_field_name(child, content)
                    if m_name:
                        methods.append(Symbol(
                            name=m_name, kind="def",
                            docstring=_js_jsdoc(child, content),
                            start_line=child.start_point[0] + 1,
                            end_line=child.end_point[0] + 1,
                        ))
        return Symbol(
            name=name, kind="class", docstring=_js_jsdoc(node, content),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            children=methods,
        )

    if node.type == "export_statement":
        for child in node.children:
            sym = _js_node_to_symbol(child, content)
            if sym:
                return sym
        return None

    if node.type in ("lexical_declaration", "variable_declaration"):
        for decl in node.children:
            if decl.type == "variable_declarator":
                name_n = decl.child_by_field_name("name")
                val_n = decl.child_by_field_name("value")
                if name_n and val_n and val_n.type in (
                    "arrow_function", "function_expression", "function",
                ):
                    return Symbol(
                        name=content[name_n.start_byte:name_n.end_byte],
                        kind="function",
                        docstring=_js_jsdoc(node, content),
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                    )
    return None
