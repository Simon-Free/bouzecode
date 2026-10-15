# [desc] Attente du résultat d'un sous-agent lancé en fenêtre de terminal (`bouzecode -p --result-file`) : sa réponse FinalAnswer, ou sa fiche de clôture quand il a fini sans livrer. [/desc]
"""Le sous-agent en terminal est un run `-p` : il n'écrit `--result-file` QUE s'il a clos par
FinalAnswer (ui/cloture_cli.py), puis écrit toujours sa fiche `<stem>.cloture.json`. Attendre le
seul fichier résultat faisait patienter le parent jusqu'au délai maximal (300 s) pour un enfant
qui avait fini en prose ou été refusé : la fiche dit tout de suite qu'il n'y aura rien.

Les lanceurs (wt.exe, `cmd /c start`) rendent la main immédiatement : on ne peut pas suivre le
process, seulement l'APPARITION des fichiers."""
from __future__ import annotations

import json
import time
from pathlib import Path

from ...ui.cloture_cli import chemin_fiche


def _fin_sans_livraison(fiche: Path) -> str:
    cloture = json.loads(fiche.read_text(encoding="utf-8"))
    detail = str(cloture.get("close_detail") or "")
    return (f"Sub-agent ended WITHOUT delivering (no FinalAnswer): close_reason="
            f"{cloture.get('close_reason') or '?'}, exit code {cloture.get('code_sortie')}"
            + (f" — {detail}" if detail else ""))


def constat(result_file: str) -> tuple[str, str] | None:
    """UN relevé : `completed` + la réponse FinalAnswer, `failed` + la fin sans livraison lue
    dans la fiche, ou None (rien encore). Les fichiers lus sont supprimés."""
    resultat, fiche = Path(result_file), chemin_fiche(result_file)
    if resultat.exists():
        texte = resultat.read_text(encoding="utf-8").strip()
        resultat.unlink(missing_ok=True)
        fiche.unlink(missing_ok=True)
        return "completed", texte
    if fiche.exists():
        raison = _fin_sans_livraison(fiche)
        fiche.unlink(missing_ok=True)
        return "failed", raison
    return None


def attendre_resultat(result_file: str, delai_s: float, intervalle_s: float) -> tuple[str, str]:
    """`(statut, texte)` : le premier `constat` rendu, ou `failed` si le délai est dépassé."""
    attendu = 0.0
    while True:
        releve = constat(result_file)
        if releve is not None:
            return releve
        if attendu >= delai_s:
            return "failed", f"No result file produced (timed out after {delai_s}s)"
        time.sleep(intervalle_s)
        attendu += intervalle_s
