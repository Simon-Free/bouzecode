# [desc] Lecture d'une sortie pytest : verdict, sections `=== titre ===` (toutes, connues ou non), warnings dédoublonnés, tests lents. [/desc]
"""Découpe une sortie pytest en sections, sans rien décider de ce qu'on en montre.

Toute ligne `=== titre ===` clôt la section précédente. L'ancienne lecture ne reconnaissait
que cinq titres : la section d'un plugin (`=== écritures dans le VRAI HOME hors d'un test ===`,
400 lignes) restait collée au « warnings summary » qui la précédait et partait avec lui
dans chaque résultat, même vert (8 723 car. pour 175 tests verts, 2026-10-07).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

VERDICT_RE = re.compile(
    r"^=+ (.*\b(?:passed|failed|errors?|skipped|warnings?|deselected|xfailed|xpassed|no tests ran)"
    r"\b.* in [\d.]+s.*?) =+$")
VERDICT_NU_RE = re.compile(r"^\d+ \w+(?:, \d+ \w+)* in [\d.]+s")  # `-q` : verdict sans `===`
TITRE_RE = re.compile(r"^=+ (.+?) =+$")
INTERRUPTION_RE = re.compile(r"^!{3,} .+ !{3,}$")
#  Lignes de l'en-tête (avant toute section de résultats) qui signalent un crash, pas un test.
#  `ERROR: file or directory not found: x` : seule explication d'un « no tests ran ».
_CRASH_RE = re.compile(r"^INTERNALERROR|^ERROR: |node down|crashed worker|replacing crashed")
_DUREE_RE = re.compile(r"^(\d+(?:\.\d+)?)s\s+(?:call|setup|teardown)\s+\S")
_EMPLACEMENT_WARNING_RE = re.compile(r"^\s*\S+:\d+: (\w*Warning: .*)$")
SEUIL_LENT_S = 1.0
TESTS_LENTS_MONTRES = 5


@dataclass
class SortiePytest:
    verdict: str = ""
    sections: list[tuple[str, list[str]]] = field(default_factory=list)
    interruptions: list[str] = field(default_factory=list)
    crashs: list[str] = field(default_factory=list)

    def section(self, nom: str) -> list[str]:
        return [l for titre, lignes in self.sections if titre == nom for l in lignes]

    @property
    def vert(self) -> bool:
        return bool(self.verdict) and not re.search(r"\b(failed|errors?)\b", self.verdict) \
            and not self.interruptions and not self.crashs


def _nom_de_section(titre: str) -> str:
    if titre.startswith("slowest"):
        return "slowest durations"
    if titre.startswith("warnings summary"):  # « warnings summary (final) » aussi
        return "warnings summary"
    return titre


def est_pytest(sortie: str) -> bool:
    lignes = sortie.split("\n")
    return any("test session starts" in l for l in lignes[:10]) or any(
        VERDICT_RE.match(l.strip()) for l in lignes)


def lire(sortie: str) -> SortiePytest:
    lu = SortiePytest()
    courante: list[str] | None = None
    for ligne in sortie.split("\n"):
        net = ligne.strip()
        if m := VERDICT_RE.match(net):
            lu.verdict, courante = m.group(1), None
        elif VERDICT_NU_RE.match(net) and not lu.verdict:
            lu.verdict, courante = net, None
        elif INTERRUPTION_RE.match(net):
            lu.interruptions.append(net)
        elif m := TITRE_RE.match(net):
            courante = []
            lu.sections.append((_nom_de_section(m.group(1)), courante))
        elif courante is not None:
            courante.append(ligne)
        if _CRASH_RE.search(net) and (courante is None or lu.sections[-1][0] == "test session starts"):
            lu.crashs.append(net)
    return lu


def _blocs_de_warnings(lignes: list[str]) -> list[tuple[list[str], list[str]]]:
    """(emplacements, message) par bloc séparé d'une ligne vide ; « -- Docs: » ignoré."""
    blocs: list[tuple[list[str], list[str]]] = []
    for ligne in lignes:
        if not ligne.strip() or ligne.startswith("-- Docs:"):
            if blocs and blocs[-1][1]:
                blocs.append(([], []))
            continue
        if not blocs:
            blocs.append(([], []))
        if ligne[:1].isspace():
            m = _EMPLACEMENT_WARNING_RE.match(ligne)
            blocs[-1][1].append(m.group(1) if m else ligne.strip())
        else:
            if blocs[-1][1]:
                blocs.append(([], []))
            blocs[-1][0].append(ligne.strip())
    return [b for b in blocs if b[1]]


def warnings_dedoublonnes(lignes: list[str], fichiers_en_echec: set[str] | None = None,
                          max_chars: int = 3000) -> str:
    """Un warning par message, avec ses emplacements distincts et le nombre d'occurrences.

    `fichiers_en_echec` donné : seuls les warnings levés dans ces fichiers sont gardés."""
    groupes: dict[tuple[str, ...], list[str]] = {}
    for emplacements, message in _blocs_de_warnings(lignes):
        if fichiers_en_echec is not None and not any(
                _fichier(e) in fichiers_en_echec for e in emplacements):
            continue
        groupes.setdefault(tuple(message[:3]), []).extend(emplacements)
    rendu = []
    for message, emplacements in groupes.items():
        distincts = list(dict.fromkeys(emplacements))
        fois = f" (×{len(emplacements)})" if len(emplacements) > 1 else ""
        rendu.append(", ".join(distincts[:3]) + (" …" if len(distincts) > 3 else "") + fois)
        rendu.extend(f"  {m[:300]}" for m in message)
    texte = "\n".join(rendu)
    return texte if len(texte) <= max_chars else texte[:max_chars] + "\n… (warnings coupés)"


def _fichier(emplacement: str) -> str:
    """`tests\\a.py:19` ou `tests/a.py::test_x` → `tests/a.py`."""
    return re.split(r"::|:\d", emplacement.replace("\\", "/"), maxsplit=1)[0]


def fichiers_en_echec(resume: list[str]) -> set[str]:
    """Fichiers cités par les lignes `FAILED …` / `ERROR …` du short test summary."""
    return {_fichier(l.split()[1]) for l in resume if l.startswith(("FAILED ", "ERROR ")) and
            len(l.split()) > 1}


def tests_lents(lignes: list[str], tout: bool = False) -> list[str]:
    """Les durées ≥ SEUIL_LENT_S, au plus TESTS_LENTS_MONTRES ; `tout` : la section entière."""
    if tout:
        return [" ".join(l.split()) for l in lignes if l.strip()]
    lentes = [" ".join(l.split()) for l in lignes
              if (m := _DUREE_RE.match(l)) and float(m.group(1)) >= SEUIL_LENT_S]
    return lentes[:TESTS_LENTS_MONTRES]
