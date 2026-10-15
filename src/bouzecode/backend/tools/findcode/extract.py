"""Extraction des définitions d'un fichier et des noms qu'elles référencent.

Python par `ast` ; JS/TS par tree-sitter ; dans un .html, chaque `<script>` inline est
analysé comme du JS, les numéros de ligne restant ceux du fichier.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

PY_EXTS = {".py"}
JS_EXTS = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}
HTML_EXTS = {".html", ".htm"}
CODE_EXTS = PY_EXTS | JS_EXTS | HTML_EXTS
_DECOR = " -=_~*#/─═•·"  # filets de commentaires (« # ---- rendu ---- »)


@dataclass(eq=False)
class Def:
    """Une définition : `qual` est le nom accepté par Read(symbol=...)."""
    name: str
    qual: str
    kind: str  # def | class | method | const | function | type | module
    file: str
    start: int
    end: int
    sig: str = ""
    doc: str = ""
    parent: str = ""
    # nom -> 1re ligne de la référence ; « .nom » = seulement vu comme attribut (obj.nom)
    refs: dict[str, int] = field(default_factory=dict)
    words: str = ""  # docstring complète, pour le classement
    features: tuple | None = None  # mots découpés, calculés au 1er classement (search.py)


@dataclass
class FileInfo:
    defs: list[Def]
    imports: dict[str, tuple[str, str]] = field(default_factory=dict)  # alias -> (module, nom)
    module_refs: dict[str, int] = field(default_factory=dict)


def extract(rel: str, text: str) -> FileInfo:
    suffix = PurePosixPath(rel).suffix.lower()
    if suffix in PY_EXTS:
        return _python(rel, text)
    if suffix in JS_EXTS:
        if max(map(len, text.splitlines()[:200]), default=0) > 1500:
            return FileInfo([])  # minifié : rien de navigable
        return _js(rel, text, suffix, 0)
    if suffix in HTML_EXTS:
        return _html(rel, text)
    return FileInfo([])


def _is_constant(name: str) -> bool:
    core = name.lstrip("_")
    return bool(core) and core.upper() == core and any(c.isalpha() for c in core)


def _clip(text: str, limit: int = 100) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _clip_sig(sig: str) -> str:
    """Signature sur une ligne ; l'espace de tête de « = valeur » est conservé."""
    lead = " " if sig.startswith(" ") else ""
    return lead + _clip(sig, 110)


def _comment_above(lines: list[str], start: int, marker: str) -> str:
    """1re ligne du bloc de commentaires collé au-dessus de la ligne `start` (1-based)."""
    i = start - 2
    block: list[str] = []
    while i >= 0 and lines[i].strip().startswith(marker):
        block.insert(0, lines[i].strip().lstrip(marker).strip(_DECOR))
        i -= 1
    return next((b for b in block if b), "")


# ---------------------------------------------------------------- Python

_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _py_scan(nodes, own: str, imports: list) -> tuple[dict[str, int], set[str]]:
    """Un seul parcours : noms lus (et attributs, préfixés « . »), noms liés localement
    (paramètres, affectations) et imports rencontrés, ajoutés à `imports`."""
    refs: dict[str, int] = {}
    bound: set[str] = set()
    for top in nodes:
        for node in ast.walk(top):
            kind = type(node)
            if kind is ast.Name:
                _py_name(node, own, refs, bound)
            elif kind is ast.Attribute:
                refs.setdefault("." + node.attr, node.lineno)
            elif kind in _BINDING:
                bound.add(getattr(node, "arg", None) or getattr(node, "name", None))
            elif kind in _IMPORTS:
                imports.append(node)
    return refs, bound


_BINDING = (ast.arg, ast.ExceptHandler)
_IMPORTS = (ast.Import, ast.ImportFrom)


def _py_name(node, own: str, refs: dict[str, int], bound: set[str]) -> None:
    if isinstance(node.ctx, ast.Store):
        bound.add(node.id)
    elif node.id != own:
        refs.setdefault(node.id, node.lineno)


def _py_sig(node) -> str:
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(b) for b in node.bases)
        return f"({bases})" if bases else ""
    sig = f"({ast.unparse(node.args)})"
    if node.returns is not None:
        sig += f" -> {ast.unparse(node.returns)}"
    return sig


def _py_refs(node, imports: list) -> tuple[str, dict[str, int], str]:
    """(signature, références, docstring complète) d'une définition Python."""
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        refs, _ = _py_scan([node.value] if node.value is not None else [], "", imports)
        return "", refs, ""
    if isinstance(node, ast.ClassDef):
        body = [n for n in node.body if not isinstance(n, _FUNCS)]
        refs, _ = _py_scan(body + node.bases + node.decorator_list, node.name, imports)
    else:
        refs, bound = _py_scan([node], node.name, imports)
        refs = {k: v for k, v in refs.items() if k not in bound}
    return _py_sig(node), refs, (ast.get_docstring(node) or "")[:600]


def _py_def(rel, node, qual, kind, lines, imports, parent="") -> Def:
    start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
    sig, refs, full = _py_refs(node, imports)
    if kind == "const":
        sig = " = " + _clip(lines[node.lineno - 1].split("=", 1)[-1], 60)
    doc = full.strip().split("\n")[0] if full.strip() else _comment_above(lines, start, "#")
    return Def(qual.split(".")[-1], qual, kind, rel, start, node.end_lineno or node.lineno,
               _clip_sig(sig), _clip(doc), parent, refs, full)


def _py_constants(rel, node, lines, imports) -> list[Def]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return [_py_def(rel, node, t.id, "const", lines, imports)
            for t in targets if isinstance(t, ast.Name) and _is_constant(t.id)]


def _py_class(rel, node, lines, imports) -> list[Def]:
    out = [_py_def(rel, node, node.name, "class", lines, imports)]
    for sub in node.body:
        if isinstance(sub, _FUNCS):
            out.append(_py_def(rel, sub, f"{node.name}.{sub.name}", "method", lines, imports,
                               node.name))
    return out


def _py_imports(nodes: list, rel: str) -> dict[str, tuple[str, str]]:
    """alias -> (module pointé, nom importé) ; les imports relatifs sont résolus."""
    package = list(PurePosixPath(rel).parent.parts)
    imports: dict[str, tuple[str, str]] = {}
    for node in nodes:
        if isinstance(node, ast.ImportFrom):
            base = package[: len(package) - node.level + 1] if node.level else []
            module = ".".join(base + ([node.module] if node.module else []))
            for alias in node.names:
                imports[alias.asname or alias.name] = (module, alias.name)
        else:
            for alias in node.names:
                imports[alias.asname or alias.name.split(".")[0]] = (alias.name, "")
    return imports


def _python(rel: str, text: str) -> FileInfo:
    try:
        tree = ast.parse(text.lstrip("﻿"))
    except (SyntaxError, ValueError):
        return FileInfo([])
    lines = text.splitlines()
    defs: list[Def] = []
    loose, imports = [], []
    for node in tree.body:
        if isinstance(node, _FUNCS):
            defs.append(_py_def(rel, node, node.name, "def", lines, imports))
        elif isinstance(node, ast.ClassDef):
            defs += _py_class(rel, node, lines, imports)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and _is_constant_assign(node):
            defs += _py_constants(rel, node, lines, imports)
        else:
            loose.append(node)
    module_refs, _ = _py_scan(loose, "", imports)
    return FileInfo(defs, _py_imports(imports, rel), module_refs)


def _is_constant_assign(node) -> bool:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return any(isinstance(t, ast.Name) and _is_constant(t.id) for t in targets)


# ---------------------------------------------------------------- JS / TS

_PARSERS: dict[str, object] = {}
_FUNC_TYPES = {"function_declaration", "generator_function_declaration"}
_CLASS_TYPES = {"class_declaration", "abstract_class_declaration"}
_TYPE_TYPES = {"interface_declaration", "type_alias_declaration", "enum_declaration"}
_BINDERS = {"variable_declarator", "formal_parameters", "arrow_function"}
_FUNC_VALUES = {"arrow_function", "function_expression", "function", "generator_function"}
_IDENT_TYPES = {"identifier", "property_identifier", "shorthand_property_identifier",
                "type_identifier"}


def _parser(suffix: str):
    key = {".ts": "ts", ".tsx": "tsx"}.get(suffix, "js")
    if key not in _PARSERS:
        try:
            from tree_sitter import Language, Parser
            if key == "js":
                import tree_sitter_javascript as grammar
                lang = grammar.language()
            else:
                import tree_sitter_typescript as grammar
                lang = grammar.language_typescript() if key == "ts" else grammar.language_tsx()
            _PARSERS[key] = Parser(Language(lang))
        except ImportError:
            _PARSERS[key] = None
    return _PARSERS[key]


class _JsWalk:
    """Parcourt un arbre tree-sitter : les définitions nommées sont relevées (sans
    descendre dans leur corps, sauf les méthodes de classe) ; les fonctions anonymes
    (IIFE, callbacks) sont traversées, leurs références comptent pour le module."""

    def __init__(self, rel: str, src: bytes, offset: int, lines: list[str]):
        self.rel, self.src, self.offset, self.lines = rel, src, offset, lines
        self.defs: list[Def] = []
        self.module_refs: dict[str, int] = {}

    def text(self, node) -> str:
        return self.src[node.start_byte:node.end_byte].decode("utf-8", "replace")

    def line(self, node) -> int:
        return node.start_point[0] + 1 + self.offset

    def refs(self, node, own: str = "") -> dict[str, int]:
        out: dict[str, int] = {}
        bound: set[str] = set()
        stack = [node]
        while stack:
            cur = stack.pop()
            if cur.type in _IDENT_TYPES:
                self.ident(cur, own, out)
            elif cur.type in _BINDERS:
                bound |= self.bound(cur)
            stack.extend(cur.children)
        if node.type == "variable_declarator":
            bound.discard(own)
        return {k: v for k, v in out.items() if k not in bound}

    def ident(self, node, own: str, out: dict[str, int]) -> None:
        """Relève un identifiant à sa 1re ligne ; `obj.nom` est noté « .nom »."""
        name = ("." if node.type == "property_identifier" else "") + self.text(node)
        line = self.line(node)
        if name != own and line < out.get(name, line + 1):
            out[name] = line

    def bound(self, node) -> set[str]:
        """Noms déclarés par ce nœud : variable locale, paramètres."""
        if node.type == "variable_declarator":
            name = node.child_by_field_name("name")
            return {self.text(name)} if name is not None and name.type == "identifier" else set()
        if node.type == "arrow_function":
            param = node.child_by_field_name("parameter")
            return {self.text(param)} if param is not None else set()
        names = set()
        for child in node.named_children:
            target = child.child_by_field_name("left") if child.type == "assignment_pattern" else child
            if target is not None and target.type == "identifier":
                names.add(self.text(target))
        return names

    def add(self, node, name, qual, kind, sig="", parent="", body=None) -> None:
        start, end = self.line(node), node.end_point[0] + 1 + self.offset
        doc = _comment_above(self.lines, start, "//") or _comment_above(self.lines, start, "*")
        self.defs.append(Def(name, qual, kind, self.rel, start, end, _clip_sig(sig),
                             _clip(doc), parent, self.refs(body or node, own=name)))

    def params(self, node) -> str:
        params = node.child_by_field_name("parameters")
        return self.text(params) if params is not None else ""

    def visit(self, node, top: bool) -> None:
        for child in node.named_children:
            handler = self._handler(child.type)
            if handler is not None:
                handler(child, top)
            elif child.type == "export_statement":
                self.visit(child, top)
            elif child.type in _IDENT_TYPES:
                dot = "." if child.type == "property_identifier" else ""
                self.module_refs.setdefault(dot + self.text(child), self.line(child))
            else:
                self.visit(child, False)

    def _handler(self, node_type: str):
        if node_type in _FUNC_TYPES:
            return self.function
        if node_type in _CLASS_TYPES:
            return self.klass
        if node_type in _TYPE_TYPES:
            return self.type_decl
        if node_type in ("lexical_declaration", "variable_declaration"):
            return self.declaration
        return None

    def function(self, node, top: bool) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return self.visit(node, False)
        name = self.text(name_node)
        self.add(node, name, name, "function", self.params(node))

    def klass(self, node, top: bool) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return self.visit(node, False)
        name = self.text(name_node)
        self.add(node, name, name, "class")
        body = node.child_by_field_name("body")
        for member in (body.named_children if body is not None else []):
            member_name = member.child_by_field_name("name")
            if member.type == "method_definition" and member_name is not None:
                sub = self.text(member_name)
                self.add(member, sub, f"{name}.{sub}", "method", self.params(member), name)

    def type_decl(self, node, top: bool) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            name = self.text(name_node)
            self.add(node, name, name, "type")

    def declaration(self, node, top: bool) -> None:
        for decl in node.named_children:
            if decl.type == "variable_declarator":
                self.declarator(node, decl, top)

    def declarator(self, node, decl, top: bool) -> None:
        """`const f = () => …` est une fonction ; une constante MAJUSCULE (ou tout const/let
        de haut niveau) est une const ; le reste est traversé (fonctions anonymes)."""
        name_node, value = decl.child_by_field_name("name"), decl.child_by_field_name("value")
        name = self.text(name_node) if name_node is not None and name_node.type == "identifier" else ""
        if name and value is not None and value.type in _FUNC_VALUES:
            self.add(node, name, name, "function", self.params(value), body=decl)
        elif name and (top or _is_constant(name)):
            first = self.text(value).split("\n")[0] if value is not None else ""
            self.add(node, name, name, "const", " = " + _clip(first, 60), body=decl)
        else:
            self.visit(decl, False)


def _js(rel: str, text: str, suffix: str, offset: int, lines: list[str] | None = None) -> FileInfo:
    parser = _parser(suffix)
    if parser is None:
        return FileInfo([])
    src = text.encode("utf-8")
    walk = _JsWalk(rel, src, offset, lines if lines is not None else text.splitlines())
    walk.visit(parser.parse(src).root_node, True)
    return FileInfo(walk.defs, {}, walk.module_refs)


_SCRIPT = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.S | re.I)
_JS_TYPES = ("", "text/javascript", "application/javascript", "module", "text/babel")


def _html(rel: str, text: str) -> FileInfo:
    lines = text.splitlines()
    info = FileInfo([])
    for match in _SCRIPT.finditer(text):
        attrs = match.group(1)
        kind = re.search(r"""type\s*=\s*["']?([^"'\s>]+)""", attrs, re.I)
        if re.search(r"\bsrc\s*=", attrs, re.I) or (kind and kind.group(1).lower() not in _JS_TYPES):
            continue
        offset = text.count("\n", 0, match.start(2))
        part = _js(rel, match.group(2), ".js", offset, lines)
        info.defs += part.defs
        for name, line in part.module_refs.items():
            info.module_refs.setdefault(name, line)
    return info
