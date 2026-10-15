# [desc] Le récap du codeur embarqué dans le commit d'intégration, et l'archivage des brouillons de fusion après un merge. [/desc]
"""Extrait d'`integration.py` (seuil ~200 lignes)."""
from __future__ import annotations

import logging
from pathlib import Path

from ...runtime.runner import agent_fiche
from ..sessions import store
from . import brouillons_integres


def _work_run(ticket: dict) -> dict | None:
    return next((r for r in ticket.get("runs") or []
                 if isinstance(r, dict) and r.get("kind") == "work"), None)


def _coder_recap(ticket: dict) -> dict:
    """Le `recap` structuré du codeur (run kind=work), lu dans sa session ({} si absent)."""
    run = _work_run(ticket)
    agent = agent_fiche.load_agent(run.get("agent_id")) if run else None
    if not agent or not getattr(agent, "session_path", None):
        return {}
    recap = (store.load_session_json(Path(agent.session_path)) or {}).get("recap")
    return recap if isinstance(recap, dict) else {}


def _changes_lines(changes) -> list[str]:
    if not isinstance(changes, list) or not changes:
        return []
    lignes = ["## Changes"]
    for item in changes:
        if isinstance(item, dict) and str(item.get("file", "")).strip():
            lignes.append(f"- {str(item['file']).strip()} — {str(item.get('summary', '')).strip()}")
    return lignes + [""]


def coder_recap_body(ticket: dict) -> str:
    """Le récap du codeur en markdown, embarqué dans le message du commit intégré (même
    source que GET /recap). "" si aucun run work ou aucun récap."""
    recap = _coder_recap(ticket)
    lines: list[str] = []
    for cle, titre in (("symptoms", "## Symptoms"), ("explanation", "## Explanation"),
                       ("tests", "## Tests")):
        if str(recap.get(cle, "")).strip():
            lines += [titre, str(recap[cle]).strip(), ""]
    lines += _changes_lines(recap.get("changes"))
    return "\n".join(lines).strip()


def archiver_les_brouillons_de_fusion(ticket: dict) -> None:
    """Les brouillons « Fusionner la branche … » de ce ticket n'ont plus d'objet. Le merge est
    fait : un échec ici se journalise et ne le défait jamais (le tick du watchdog rattrape)."""
    try:
        brouillons_integres.apres_integration(ticket)
    except Exception:  # noqa: BLE001 — le merge est livré quoi qu'il arrive
        logging.getLogger(__name__).warning("brouillons de fusion non archivés", exc_info=True)
