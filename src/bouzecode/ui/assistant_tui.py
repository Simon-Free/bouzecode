# [desc] L'assistant du Bureau dans le terminal (`bouzecode --assistant`, `/assistant`) : identite de parent `tui:<id>` et ligne d'alerte des signalements au prompt. [/desc]
"""Hors du serveur web, l'assistant n'a pas d'agent_id : les taches qu'il lance n'avaient pas
de parent, donc personne ne les suivait. On lui donne une identite `tui:<id>` (variable
`BOUZECODE_TUI_PARENT`, lue par `bureau_tools._moi` et l'outil `Signaler`) : ses lancements
lui sont rattaches, il les suit avec `Flotte(attendre_s=N)`, et les signalements de sa
lignee s'affichent au-dessus du prompt.
"""
from __future__ import annotations

import os
import uuid

from .ansi import clr

ENV_TUI = "BOUZECODE_TUI_PARENT"
PROFIL = "bureau-assistant"

_deja_affiches: set[str] = set()


def armer_identite() -> str:
    """L'identite `tui:<id>` de ce terminal (creee une fois par process)."""
    if not os.environ.get(ENV_TUI):
        os.environ[ENV_TUI] = f"tui:{uuid.uuid4().hex[:12]}"
    return os.environ[ENV_TUI]


def lignes_d_alerte() -> list[str]:
    """Les signalements NOUVEAUX de la lignee de cet assistant (une fois chacun)."""
    moi = os.environ.get(ENV_TUI) or ""
    if not moi:
        return []
    from bouzecode.web_v2.services.work import signalements
    nouveaux = [s for s in signalements.de_la_lignee(moi) if s["id"] not in _deja_affiches]
    _deja_affiches.update(s["id"] for s in nouveaux)
    return [f"⚑ [{s['gravite']}] {s['titre']} — agent {s['agent_id']}"
            f" (ticket {s['ticket_id'] or '-'})" for s in nouveaux]


def afficher_alertes() -> None:
    """Appele par la boucle du REPL avant chaque prompt ; muet hors mode assistant."""
    for ligne in lignes_d_alerte():
        couleur = "red" if "[bloquant]" in ligne else "yellow"
        print(clr(f"  {ligne}", couleur))
