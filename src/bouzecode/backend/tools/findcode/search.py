"""Classement des définitions pour une requête, et rendu de la réponse de FindCode.

Barème : nom exact > nom partiel > mots de la docstring/commentaire > chemin > noms
référencés dans le corps ; malus pour les tests, sauf si la requête en parle.
"""
from __future__ import annotations

import re
import unicodedata

from .extract import Def
from .index import RepoIndex, is_test_path

TOP = 10
WITH_NEIGHBOURS = 3
NEIGHBOURS = 4
LOAD_MAX = 3
LOAD_LINES = 150
EXACT = 40.0
WEIGHTS = (10, 3, 2, 1)  # nom, docstring/commentaire, chemin, noms référencés dans le corps
TEST_PENALTY = 0.2
_STOP = set("""
a an and are as at be by de des du en est et for from how in is it la le les of on or ou par
pour que qui quel quels quelle quelles sa se ses son sur the to un une what where which with dans
ce cet cette ces il elle je veux dois doit faut fait faire comment quoi symboles symbole charger
modifier changer code fichier fichiers fonction fonctions this that when then than avec sans
""".split())
_WORD = re.compile(r"[A-Za-z_À-ÿ][\w.À-ÿ]*")


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def _parts(identifier: str) -> list[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", identifier)
    return [p for p in re.split(r"[^A-Za-z0-9]+", _fold(spaced)) if len(p) >= 2]


SPECIFIC_WORD = 8


def _identifier_shaped(word: str) -> bool:
    """Le mot désigne-t-il un NOM de code ? `snake_case`, `camelCase`, `Classe.méthode`, chiffre,
    MAJUSCULES d'au moins 5 lettres (`COSTS` ; `API`, `UI`, `XML` restent des sigles), ou mot
    long, donc spécifique (`staleness`, `resoudre`).

    Un mot ordinaire et court de la requête (« api », « select », « card », « images ») ne prouve
    pas qu'on cherche la définition qui porte ce nom : dans les sessions DeepSeek, ces homonymes
    génériques de 1 à 8 lignes prenaient la tête, et le corps joint par `load` avec eux."""
    return ("_" in word or "." in word.strip(".") or any(c.isdigit() for c in word)
            or re.search(r"[a-z][A-Z]", word) is not None
            or (word.isupper() and len(word) >= 5) or len(word) >= SPECIFIC_WORD)


class Query:
    def __init__(self, text: str):
        words = _WORD.findall(text or "")
        self.idents = {_fold(w) for w in words if _identifier_shaped(w)}
        terms: list[str] = []
        for word in words:
            terms += [p for p in _parts(word) if len(p) >= 3 and p not in _STOP]
        self.terms = list(dict.fromkeys(terms))
        self.about_tests = any(t.startswith(("test", "pytest", "spec")) for t in self.terms)


def _matches(term: str, word: str) -> bool:
    """Égalité, ou préfixe commun long (`resolve`/`resolution`, `champ`/`champs`)."""
    if term == word:
        return True
    common = _common(term, word)
    return common >= 4 and common >= min(len(term), len(word)) - 2


def _common(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def _hit(term: str, words: list[str]) -> bool:
    return any(_matches(term, w) for w in words)


def _features(d: Def) -> tuple:
    """Mots découpés et repliés d'une définition, calculés une fois par extraction."""
    if d.features is None:
        d.features = (_fold(d.qual), _fold(d.name), set(_parts(d.name)),
                      set(_parts(d.doc + " " + d.words)), set(_parts(d.file)),
                      {p for r in d.refs for p in _parts(r)})
    return d.features


def score(d: Def, q: Query) -> float:
    """Nom exact 40, puis par terme : nom 10, doc 3, chemin 2, noms du corps 1 ;
    pondéré par la part des termes couverts, malus tests et dunders."""
    if not q.terms and not q.idents:
        return 0.0
    qual, name, *fields = _features(d)
    total, matched = (EXACT if (qual in q.idents or name in q.idents) else 0.0), 0
    for term in q.terms:
        gain = sum(weight * _hit(term, words) for weight, words in zip(WEIGHTS, fields))
        total += gain
        matched += gain > 0
    if q.terms:
        total *= 0.4 + 0.6 * matched / len(q.terms)
    return total * _penalty(d, q)


def _penalty(d: Def, q: Query) -> float:
    factor = TEST_PENALTY if is_test_path(d.file) and not q.about_tests else 1.0
    return factor * (0.5 if d.name.startswith("__") and d.name.endswith("__") else 1.0)


def rank(index: RepoIndex, q: Query, prefix: str = "") -> list[tuple[float, Def]]:
    scored = []
    for info_file, info in index.files.items():
        if prefix and not info_file.startswith(prefix):
            continue
        for d in info.defs:
            s = score(d, q)
            if s > 0:
                scored.append((s, d))
    scored.sort(key=lambda sd: (-sd[0], sd[1].file, sd[1].start))
    return scored


# ---------------------------------------------------------------- rendu

def headline(d: Def) -> str:
    doc = f" — {d.doc}" if d.doc else ""
    return f"{d.file}:L{d.start}-{d.end} {d.kind} {d.qual}{d.sig}{doc}"


def _where(other: Def, line: int, here: str) -> str:
    """`fichier:Lligne`, réduit à `Lligne` quand c'est le fichier de la définition."""
    return f"L{line}" if other.file == here else f"{other.file}:L{line}"


def _ref(d: Def, line: int, here: str = "") -> str:
    return f"{_where(d, line, here)} " + ("(module level)" if d.kind == "module" else d.qual)


def _callee(d: Def, here: str = "") -> str:
    return f"{_where(d, d.start, here)} {d.qual}"


def _joined(items: list[str], cap: int = NEIGHBOURS) -> str:
    more = f" (+{len(items) - cap})" if len(items) > cap else ""
    return " · ".join(items[:cap]) + more


def _callers_text(index: RepoIndex, d: Def) -> str:
    """Appelants du code d'abord ; ceux des tests ne sont que comptés s'il y en a d'autres."""
    pairs = index.callers(d)
    code = [_ref(u, line, d.file) for u, line in pairs if not is_test_path(u.file)]
    tests = [_ref(u, line, d.file) for u, line in pairs if is_test_path(u.file)]
    if not code:
        return _joined(tests)
    return _joined(code) + (f" (+{len(tests)} in tests)" if tests else "")


def neighbour_lines(index: RepoIndex, d: Def, indent: str = "   ") -> list[str]:
    out = []
    callers = _callers_text(index, d)
    callees = [_callee(c, d.file) for c, _ in index.callees(d)]
    label = "used by" if d.kind == "const" else "called by"
    if callers:
        out.append(f"{indent}{label}: {callers}")
    if callees:
        out.append(f"{indent}calls: {_joined(callees)}")
    return out


def body(index: RepoIndex, d: Def, limit: int = LOAD_LINES) -> str:
    path = index.root / d.file
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    end = min(d.end, d.start + limit - 1)
    text = "\n".join(f"{i:6}\t{lines[i - 1]}" for i in range(d.start, end + 1))
    cut = ""
    if end < d.end:
        cut = f"\n[… {d.end - end} more lines: Read(file_path=\"{path}\", symbol=\"{d.qual}\")]"
    return f"--- {d.file} :: {d.qual} (L{d.start}-{d.end}) ---\n{text}{cut}"


def loaded(index: RepoIndex, defs: list[Def]) -> str:
    return "\n\n".join(body(index, d) for d in defs)


def to_load(ranked: list[tuple[float, Def]]) -> list[Def]:
    """1 à 3 meilleurs : ceux qui restent à au moins 60 % du score du premier."""
    if not ranked:
        return []
    best = ranked[0][0]
    return [d for s, d in ranked[:LOAD_MAX] if s >= 0.6 * best]


def render_search(index: RepoIndex, query: str, ranked: list[tuple[float, Def]]) -> str:
    top = [d for _, d in ranked[:TOP]]
    head = (f"FindCode {query!r}: {len(ranked)} definitions match, best {len(top)} "
            f"(paths relative to {index.root}; a bare Lnn is in the same file):")
    lines = [head]
    for rank_no, d in enumerate(top, 1):
        lines.append(f"{rank_no}. {headline(d)}")
        if rank_no <= WITH_NEIGHBOURS:
            lines += neighbour_lines(index, d)
    lines.append(f'Load: Read(file_path="{index.root}/<file>", symbol="<qualname>"), '
                 'or FindCode(symbol="<qualname>", depth=2) for its call graph.')
    return "\n".join(lines)


def render_neighbourhood(index: RepoIndex, targets: list[Def], depth: int) -> str:
    lines = [f"FindCode symbol={targets[0].qual!r} depth={depth} "
             f"(paths relative to {index.root}; a bare Lnn is in the same file):"]
    for d in targets[:3]:
        lines.append(headline(d))
        lines += _tree(index, d, depth, "   ")
    return "\n".join(lines)


def _direction(index: RepoIndex, d: Def, up: bool, here: str) -> list[tuple[Def, str]]:
    """Appelants (`up`) ou appelés de `d`, écrits relativement au fichier `here`."""
    if up:
        return [(other, _ref(other, line, here)) for other, line in index.callers(d)]
    return [(other, _callee(other, here)) for other, _ in index.callees(d)]


def _tree(index: RepoIndex, d: Def, depth: int, indent: str) -> list[str]:
    out = []
    for label, up in (("used by" if d.kind == "const" else "called by", True), ("calls", False)):
        pairs = _direction(index, d, up, d.file)
        if pairs:
            out.append(f"{indent}{label}:")
            out += _branch(index, pairs, (depth, up, d.file), indent + "  ")
    return out or [f"{indent}(no caller or callee found in the index)"]


def _branch(index: RepoIndex, pairs: list[tuple[Def, str]], how: tuple[int, bool, str],
            indent: str) -> list[str]:
    depth, up, here = how
    out = []
    for other, text in pairs[:6]:
        out.append(indent + text)
        if depth > 1 and other.kind != "module":
            further = [t for _, t in _direction(index, other, up, here)]
            if further:
                out.append(f"{indent}  {'called by' if up else 'calls'}: {_joined(further)}")
    if len(pairs) > 6:
        out.append(f"{indent}(+{len(pairs) - 6} more)")
    return out


def find_exact(index: RepoIndex, symbol: str, prefix: str = "") -> list[Def]:
    wanted = symbol.strip().split("::")[-1].strip("`() ")
    hits = [d for info in index.files.values() for d in info.defs
            if (d.qual == wanted or d.name == wanted) and d.file.startswith(prefix)]
    hits.sort(key=lambda d: (d.qual != wanted, is_test_path(d.file), d.file, d.start))
    return hits
