# [desc] Aides de test du lot L2 : un projet enregistré, une fiche d'agent écrite comme le runner, un ticket amené dans un état par la machine à états (jamais par un drapeau). [/desc]
"""Les tests construisent leurs tickets par les VRAIS chemins (`create_ticket`, `set_launching`,
`add_run`, `ticket_fsm.appliquer`) ou les SÈMENT dans un état donné (`semer`, l'état passé fait
foi, comme une base migrée). Aucun mock : un agent est une fiche JSON dans `AGENTS_DIR` (isolé
par la fixture autouse), éventuellement adossée à un vrai process."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from bouzecode.web_v2.runtime.runner import agent_fiche, agent_registre
from bouzecode.web_v2.services.sessions import store
from bouzecode.web_v2.services.work import projects, ticket_fsm, tickets
from bouzecode.web_v2.services.work.fsm import etats


def maintenant() -> str:
    return datetime.now().isoformat(timespec="seconds")


def projet(tmp_path: Path, monkeypatch, slug: str = "proj", chemin: Path | None = None) -> Path:
    """Enregistre le projet `slug` (dossier `chemin`, défaut `tmp_path`)."""
    registre = tmp_path / "projects.json"
    monkeypatch.setattr(projects, "PROJECTS_PATH", registre)
    registre.write_text(json.dumps([{"slug": slug, "name": slug,
                                     "path": str(chemin or tmp_path)}]), encoding="utf-8")
    return chemin or tmp_path


def fiche_agent(agent_id: str, slug: str = "", ticket_id: str = "", close_reason=None,
                final_answer: str = "", pid=None, ipc: dict | None = None, **champs):
    """La fiche que le runner écrit pour un agent (mort par défaut : returncode -1), sa
    session (si `close_reason` est donné) et son IPC (si `ipc`). Rend l'agent chargé."""
    parc = agent_fiche.AGENTS_DIR
    parc.mkdir(parents=True, exist_ok=True)
    session = parc / f"{agent_id}.session.json"
    ipc_dir = parc / f"{agent_id}.ipc"
    fiche = {"agent_id": agent_id, "prompt": "Corrige le calcul", "model": "m", "cwd": "",
             "pid": pid, "started_at": "2026-10-01T10:00:00",
             "returncode": None if pid else -1, "finished_at": "",
             "session_path": str(session), "stdout_path": str(parc / f"{agent_id}.out.log"),
             "ipc_dir": str(ipc_dir) if ipc is not None else "", "parent": "",
             "ticket_slug": slug, "ticket_id": ticket_id, **champs}
    if pid:
        import psutil
        fiche.setdefault("pid_create_time", psutil.Process(pid).create_time())
    (parc / f"{agent_id}.json").write_text(json.dumps(fiche), encoding="utf-8")
    if close_reason is not None:
        donnees = {"messages": [], "close_reason": close_reason}
        if final_answer:
            donnees["final_answer"] = final_answer
        session.write_text(json.dumps(donnees), encoding="utf-8")
    if ipc is not None:
        ipc_dir.mkdir(parents=True, exist_ok=True)
        (ipc_dir / "state.json").write_text(json.dumps(ipc), encoding="utf-8")
    agent_fiche._list_agents_cache.clear()
    agent_registre._agent_file_cache.clear()
    store.invalidate_status(agent_id)
    return agent_fiche.load_agent(agent_id)


def en_cours(slug: str, agent_id: str = "a1", titre: str = "T", kind: str = "work",
             **champs) -> dict:
    """Un ticket lancé dont l'agent tourne (`running`), par le vrai chemin de lancement."""
    ticket = tickets.create_ticket(slug, titre, "faire")
    if champs:
        tickets.poser(slug, ticket, **champs)
    tickets.set_launching(slug, ticket)
    tickets.add_run(slug, ticket, agent_id, kind, "m")
    return ticket


def amener(slug: str, ticket: dict, *evenements: str, **data) -> dict:
    """Applique les événements dans l'ordre (le dernier reçoit `data`) ; rend le ticket frais."""
    for evenement in evenements[:-1]:
        ticket_fsm.appliquer(slug, ticket["id"], evenement)
    frais = ticket_fsm.appliquer(slug, ticket["id"], evenements[-1], **data)
    ticket.clear()
    ticket.update(frais)
    return frais


def livre(slug: str, agent_id: str = "a1", **champs) -> dict:
    """Un ticket dont l'agent a rendu sa réponse finale (`delivered`, run `completed`)."""
    ticket = en_cours(slug, agent_id, **champs)
    tickets.mark_run_completed(slug, ticket, agent_id)
    return amener(slug, ticket, etats.RUN_ENDED, delivered=True, close_reason="final_answer")


def semer(slug: str, ident: str, state: str, code: str | None = None, runs=(), **champs) -> dict:
    """Un ticket SEMÉ directement dans `state` (l'état passé fait foi, comme une base migrée)."""
    ticket = {"id": ident, "title": champs.pop("title", ident), "prompt": "faire",
              "created_at": maintenant(), "comments": [], "state": state,
              "state_reason": {"code": code, "message": champs.pop("message", ""),
                               "at": maintenant()} if code else None,
              "runs": [dict(run) for run in runs], **champs}
    tickets._save_unlocked(slug, [ticket])
    return tickets.get_ticket(slug, ident)


def run(agent_id: str, state: str = "ended", **champs) -> dict:
    return {"agent_id": agent_id, "kind": "work", "model": "m", "started_at": maintenant(),
            "state": state, **champs}


def constater_tout(fois: int = 2) -> None:
    """Ce que le watchdog aurait CONSTATÉ avant qu'on regarde : `fois` passages de
    `constats.constater` sur chaque ticket en vol (une mort se confirme en deux passages)."""
    from bouzecode.web_v2.services.work import _persistence, constats
    for _ in range(fois):
        for slug, ticket in _persistence.all_tickets():
            if constats.a_constater(ticket):
                constats.constater(slug, ticket)
