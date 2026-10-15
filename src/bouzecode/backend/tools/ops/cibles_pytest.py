# [desc] RunPythonTest : les `targets` lus depuis le dossier de l'agent (une seule résolution, démon ou direct, wait true ou false) ; une cible introuvable est refusée avant tout run [/desc]
"""Session de4d1304 (2026-10-14), job 246a5fe8 : `targets=['tests/focus/…']` depuis un dossier
d'agent qui n'était pas le bon projet. Le projet était déduit de la cible lue depuis ce dossier,
mais la cible était passée TELLE QUELLE à pytest, lancé, lui, à la racine du projet : deux
résolutions. Ici la cible devient absolue une fois, depuis le dossier de l'agent ; pytest ne
reçoit que des chemins qui existent."""
from __future__ import annotations

import glob
from pathlib import Path

_JOKERS = ("*", "?", "[")


def _developper(chemin: Path) -> list[Path]:
    """Un motif (`tests/test_rules*.py`, `**`) devient ses chemins existants, triés ; un chemin
    sans joker reste tel quel. Session dee74ecf8286 (B4, 2026-10-14) : `tests/test_demoapp_rules*.py`
    était refusé comme « cible introuvable »."""
    if not any(j in str(chemin) for j in _JOKERS):
        return [chemin]
    return [Path(p) for p in sorted(glob.glob(str(chemin), recursive=True))]


def cibles_absolues(targets: list[str]) -> tuple[list[str], str]:
    """(cibles absolues, `::test` conservé, motifs développés ; message d'erreur "" si toutes
    existent)."""
    from ...core.dossier_agent import courant
    dossier = Path(courant())
    absolues, introuvables = [], []
    for cible in targets:
        chemin, separateur, noeud = cible.partition("::")
        absolu = Path(chemin).expanduser()
        absolu = absolu if absolu.is_absolute() else dossier / absolu
        trouves = [p for p in _developper(absolu) if p.exists()]
        if not trouves:
            introuvables.append(f"{cible} → {absolu}")
        absolues.extend(str(p) + separateur + noeud for p in trouves or [absolu])
    if not introuvables:
        return absolues, ""
    return absolues, (
        "Error: cible introuvable : " + " ; ".join(introuvables) + f"\nDossier de l'agent : {dossier}"
        " (les chemins relatifs se lisent depuis lui). Rien n'a été lancé. Passe un chemin "
        "absolu, ou déplace-toi dans le bon projet : LoadProjectConfig(path=…, cd=true). Fichier "
        "écrit dans le même lot d'outils : RunPythonTest l'attend déjà s'il vient APRÈS le Write "
        "dans le lot ; sinon `depends_on`.")
