# [desc] Passe mécanique (sans modèle) sur les extraits de la note : périmés, temporaires, disparus, doublons [/desc]
"""La moitié MÉCANIQUE de la compaction des extraits (snippets) de la note.

Pourquoi : le retrait d'un extrait n'était jamais automatique. Un Edit/Write ne fait
qu'ajouter un marqueur ``## snippet-stale:`` en fin de note (réécrire l'extrait sur
place casserait le cache à chaque édition) ; le tri était confié au juge (un appel au
modèle) et à l'agent. Rejoué le 2026-09-24 sur une vraie session DeepSeek : le juge,
tronqué, n'a rien retiré, et la passe de prose a avalé les 31 marqueurs — les vieux
extraits restaient sans marqueur, présentés comme valides (46 sur 50 périmés, jetables
ou en double).

Tout ce qui ne demande AUCUN jugement est donc tranché ici, au moment de la
compaction seulement (le cache est de toute façon réécrit à ce moment-là) :

- extrait périmé ciblé par SYMBOLE : relu dans le fichier actuel, ou retiré si le
  symbole a disparu ;
- extrait périmé ciblé par LIGNES : retiré (ses numéros de ligne ne veulent plus rien dire) ;
- extrait d'un fichier supprimé ou temporaire (``/tmp/x.py``, scratch du harnais) : retiré ;
- doublons et chevauchements d'une même source : fusionnés en un seul extrait, relu
  sur disque quand le fichier existe ;
- les marqueurs ``## snippet-stale:`` traités sont consommés.

Chaque retrait laisse une ligne de trace ``## snippet-dropped: … — extrait retiré (…)`` ;
le juge ne garde que la question « cet extrait sert-il encore ? ».
"""
from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass

from .note_blocks import _split_into_blocks

_ENTETE = re.compile(
    r"^## snippet: (?P<path>.+?)"
    r"(?P<loc> L(?P<start>\d+)-(?P<end>\d+)| :: (?P<symbol>[^\s—]+))"
    r"(?P<rest>.*)$"
)
_LIGNE_NUMEROTEE = re.compile(r"^\s*(\d+)  (.*)$")
_NOTE_FIGEE = " (frozen from the content read earlier — file no longer on disk)"


@dataclass
class Extrait:
    index: int
    key: str
    path: str
    start: int
    end: int
    symbol: str
    rest: str
    texte: str

    @property
    def loc(self) -> str:
        return f" :: {self.symbol}" if self.symbol else f" L{self.start}-{self.end}"

    @property
    def est_fichier(self) -> bool:
        return os.path.isabs(self.path)


@dataclass
class Resultat:
    note: str
    retraits: list[str]
    fusions: int

    @property
    def change(self) -> bool:
        return bool(self.retraits or self.fusions)


def _extrait(index: int, texte: str, key: str) -> Extrait | None:
    m = _ENTETE.match(texte.split("\n", 1)[0])
    if not m:
        return None
    return Extrait(index, key, m.group("path").strip(), int(m.group("start") or 0),
                   int(m.group("end") or 0), m.group("symbol") or "", m.group("rest"), texte)


def _racines_temporaires() -> set[str]:
    return {os.path.realpath(tempfile.gettempdir()), "/tmp"}


def est_temporaire(path: str) -> bool:
    """Fichier posé directement dans un répertoire temporaire, ou scratch du harnais.

    Les sondes jetables d'un agent (``/tmp/probe4.py``) le sont ; un projet de test
    rangé plus profond sous /tmp (``/tmp/pytest-…/test_x/app.py``) ne l'est pas."""
    if "/bouzecode_scratch/" in path:
        return True
    return os.path.dirname(path) in _racines_temporaires()


def _raison_de_retrait(e: Extrait, perimes: set[str]) -> str:
    """Pourquoi l'extrait doit partir, ou "" s'il reste (éventuellement relu)."""
    if e.est_fichier and est_temporaire(e.path):
        return "fichier temporaire"
    if e.est_fichier and not os.path.exists(e.path):
        return "fichier supprimé"
    if e.key in perimes and not e.symbol:
        return "périmé"
    return ""


def _trace(e: Extrait, raison: str) -> str:
    return f"## snippet-dropped: {e.path}{e.loc} — extrait retiré ({raison}) : relis-le si besoin"


def _numerote(lignes: list[str], debut: int, fin: int) -> str:
    return "\n".join(f"{i:>5}  {lignes[i - 1]}" for i in range(debut, fin + 1))


def _lire(path: str) -> list[str] | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()
    except OSError:
        return None


def _relire_symbole(e: Extrait) -> str | None:
    """Le bloc de l'extrait-symbole relu dans le fichier actuel, ou None s'il a disparu."""
    from ..tools.folder_desc.symbols import find_symbol
    lignes = _lire(e.path)
    if lignes is None:
        return None
    trouve = find_symbol(e.path, e.symbol, "\n".join(lignes))
    if trouve is None:
        return None
    rest = e.rest.replace(_NOTE_FIGEE, "")
    return f"## snippet: {e.path} :: {e.symbol}{rest}\n{_numerote(lignes, *trouve)}"


def _corps(e: Extrait) -> dict[int, str]:
    lignes = {}
    for ligne in e.texte.split("\n")[1:]:
        m = _LIGNE_NUMEROTEE.match(ligne)
        if m:
            lignes[int(m.group(1))] = m.group(2)
    return lignes


def _fusionne(groupe: list[Extrait]) -> str:
    """Un seul extrait couvrant le groupe : relu sur disque, sinon union des corps."""
    debut, fin = min(e.start for e in groupe), max(e.end for e in groupe)
    # Le libellé de la plage la plus large décrit le mieux l'ensemble fusionné.
    large = max(groupe, key=lambda e: (e.end - e.start, e.index))
    lignes = _lire(large.path) if large.est_fichier else None
    if lignes is not None and fin <= len(lignes):
        corps = _numerote(lignes, debut, fin)
        rest = large.rest.replace(_NOTE_FIGEE, "")
    else:
        union: dict[int, str] = {}
        for e in sorted(groupe, key=lambda e: e.index):
            union.update(_corps(e))
        corps = "\n".join(f"{i:>5}  {union[i]}" for i in sorted(union))
        rest = large.rest
    return f"## snippet: {large.path} L{debut}-{fin}{rest}\n{corps}"


def _groupes_qui_se_chevauchent(extraits: list[Extrait]) -> list[list[Extrait]]:
    """Plages d'une même source qui se recouvrent ou s'emboîtent (≥ 2 membres)."""
    par_source: dict[str, list[Extrait]] = {}
    for e in extraits:
        if not e.symbol:
            par_source.setdefault(e.path, []).append(e)
    groupes = []
    for plages in par_source.values():
        courant: list[Extrait] = []
        for e in sorted(plages, key=lambda e: (e.start, e.end)):
            if courant and e.start <= max(c.end for c in courant):
                courant.append(e)
            else:
                groupes.append(courant)
                courant = [e]
        groupes.append(courant)
    return [g for g in groupes if len(g) > 1]


def _doublons_de_symbole(extraits: list[Extrait]) -> list[Extrait]:
    """Les extraits-symboles répétés : on ne garde que le plus récent."""
    vus: dict[str, Extrait] = {}
    doublons = []
    for e in sorted(extraits, key=lambda e: e.index):
        if e.symbol:
            if e.key in vus:
                doublons.append(vus[e.key])
            vus[e.key] = e
    return doublons


@dataclass
class Analyse:
    """Ce que les règles décident, sans lire aucun fichier (sauf leur existence)."""
    marqueurs: list[int]
    retraits: list[tuple[Extrait, str]]
    a_relire: dict[str, Extrait]
    relus_en_double: list[Extrait]
    vivants: list[Extrait]


def _est_marqueur(key: str | None) -> bool:
    return bool(key) and key.startswith("stale:")


def _extraits(blocs: list[tuple[str, str | None]]) -> list[Extrait]:
    candidats = (_extrait(i, t, k) for i, (t, k) in enumerate(blocs)
                 if k and not _est_marqueur(k))
    return [e for e in candidats if e is not None]


def _range(a: Analyse, e: Extrait, perimes: set[str]) -> None:
    raison = _raison_de_retrait(e, perimes)
    if raison:
        a.retraits.append((e, raison))
    elif e.symbol and e.key in perimes:
        if e.key in a.a_relire:  # même symbole déjà vu : seul le plus récent est relu
            a.relus_en_double.append(a.a_relire[e.key])
        a.a_relire[e.key] = e
    else:
        a.vivants.append(e)


def _analyse(blocs: list[tuple[str, str | None]]) -> Analyse:
    perimes = {k[len("stale:"):] for _t, k in blocs if _est_marqueur(k)}
    a = Analyse([i for i, (_t, k) in enumerate(blocs) if _est_marqueur(k)], [], {}, [], [])
    for e in _extraits(blocs):
        _range(a, e, perimes)
    return a


def _plan(blocs: list[tuple[str, str | None]]) -> tuple[dict[int, str | None], int]:
    """index de bloc -> texte de remplacement (None = retiré sans trace), + nb de fusions."""
    a = _analyse(blocs)
    remplace: dict[int, str | None] = {i: None for i in a.marqueurs}
    remplace.update({e.index: _trace(e, raison) for e, raison in a.retraits})
    remplace.update({e.index: None for e in a.relus_en_double})
    for e in a.a_relire.values():
        remplace[e.index] = _relire_symbole(e) or _trace(e, "symbole disparu")
    return remplace, _dedoublonne(a.vivants, remplace)


def _dedoublonne(vivants: list[Extrait], remplace: dict[int, str | None]) -> int:
    fusions = 0
    for e in _doublons_de_symbole(vivants):
        remplace[e.index] = None
        fusions += 1
    for groupe in _groupes_qui_se_chevauchent(vivants):
        dernier = max(groupe, key=lambda e: e.index)
        for e in groupe:
            remplace[e.index] = None
        remplace[dernier.index] = _fusionne(groupe)
        fusions += len(groupe) - 1
    return fusions


def passe_mecanique(note: str) -> Resultat:
    """Applique les règles mécaniques ; la note est rendue telle quelle si rien ne change."""
    blocs = _split_into_blocks(note)
    remplace, fusions = _plan(blocs)
    if not remplace:
        return Resultat(note, [], 0)
    sortie, retraits = [], []
    for i, (texte, _key) in enumerate(blocs):
        if i not in remplace:
            sortie.append(texte)
            continue
        nouveau = remplace[i]
        if nouveau is not None:
            sortie.append(nouveau)
            if nouveau.startswith("## snippet-dropped:"):
                retraits.append(nouveau)
    return Resultat("\n".join(sortie), retraits, fusions)


def poids_mort(note: str) -> int:
    """Caractères que la passe mécanique retirerait (sans lire les fichiers à fusionner)."""
    blocs = _split_into_blocks(note)
    a = _analyse(blocs)
    total = sum(len(blocs[i][0]) for i in a.marqueurs)
    total += sum(len(e.texte) for e, _raison in a.retraits)
    total += sum(len(e.texte) for e in a.relus_en_double + _doublons_de_symbole(a.vivants))
    for groupe in _groupes_qui_se_chevauchent(a.vivants):
        total += sum(len(e.texte) for e in groupe) - max(len(e.texte) for e in groupe)
    return total


def journaliser(config: dict | None, avant: str, resultat: Resultat) -> None:
    """Trace la passe dans le journal de session (auditable depuis la vue d'enquête)."""
    log_list = getattr((config or {}).get("_state"), "compaction_log", None)
    if log_list is None or not resultat.change:
        return
    log_list.append({
        "phase": "note_snippet_cleanup",
        "turn": getattr((config or {}).get("_state"), "turn_count", 0),
        "chars_removed": len(avant) - len(resultat.note),
        "dropped": [t[len("## snippet-dropped: "):] for t in resultat.retraits],
        "merged": resultat.fusions,
    })
