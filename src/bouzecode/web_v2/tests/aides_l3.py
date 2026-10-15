# [desc] Aides des tests du lot L3/L5 : spawn d'agent remplacé par une fiche (aucun process LLM), attente d'un état, ticket isolé dans un vrai worktree avec du travail commité. [/desc]
"""Les routes cibles sont appelées par le VRAI client Flask, sur le vrai store et du vrai git
(`delivery_repo`). Seul le lancement d'un process d'agent est remplacé (`spawn_factice`) : il
écrit la fiche que le runner aurait écrite et rend l'agent, sans lancer de LLM."""
from __future__ import annotations

import time
import uuid
from pathlib import Path

from bouzecode.web_v2.runtime.runner import agent_creation
from bouzecode.web_v2.services.work import tickets, worktrees

from aides_tickets import fiche_agent
from delivery_repo import SLUG, git_out


def spawn_factice(monkeypatch) -> list[dict]:
    """Remplace `runner.create_agent` ; rend la liste des lancements demandés."""
    lancements: list[dict] = []

    def _creer(prompt, model, cwd, **options):
        agent_id = uuid.uuid4().hex[:12]
        lancements.append({"agent_id": agent_id, "prompt": prompt, "cwd": cwd, **options})
        return fiche_agent(agent_id, slug=options.get("ticket_slug", ""),
                           ticket_id=options.get("ticket_id", ""), cwd=cwd,
                           run_token="jeton-" + agent_id)
    monkeypatch.setattr(agent_creation, "create_agent", _creer)
    return lancements


def attendre_etat(slug: str, ticket_id: str, *etats: str, delai_s: float = 10.0) -> dict:
    fin = time.monotonic() + delai_s
    while True:
        ticket = tickets.get_ticket(slug, ticket_id)
        if ticket["state"] in etats or time.monotonic() > fin:
            return ticket
        time.sleep(0.05)


def attendre_les_fils(*prefixes: str, delai_s: float = 30.0) -> None:
    """Attend la fin des fils de fond du serveur (`integration-…`, `lancement-…`, `relance-…`) :
    un fil qui survit au test écrirait dans le store d'après (HOME du worker)."""
    import threading
    for fil in [f for f in threading.enumerate() if f.name.startswith(prefixes)]:
        fil.join(delai_s)


def ticket_isole(repo: Path, titre: str, fichiers: dict[str, str], etat_livre: bool = True,
                 branche_de_base: str = "develop") -> dict:
    """Un ticket dans un VRAI worktree `agent/<id>` dont la branche porte un commit des
    `fichiers` donnés ; livré (par la vraie fin de run) si `etat_livre`."""
    from bouzecode.web_v2.services.work import constats
    from bouzecode.web_v2.services.work.provisioning import meta_du_worktree
    ticket = tickets.create_ticket(SLUG, titre, "fais-le")
    meta = worktrees.provision(str(repo), ticket["id"], base_branch=branche_de_base,
                               with_venv=False)
    assert meta["ok"], meta
    for nom, contenu in fichiers.items():
        (Path(meta["worktree"]) / nom).write_text(contenu, encoding="utf-8")
    git_out(meta["worktree"], "add", "-A")
    git_out(meta["worktree"], "-c", "user.email=t@t.t", "-c", "user.name=t", "commit", "-q",
            "-m", f"travail {titre}")
    tickets.poser(SLUG, ticket, worktree=meta_du_worktree(meta), isolation="worktree")
    tickets.set_launching(SLUG, ticket)
    agent_id = "ag" + ticket["id"]
    tickets.add_run(SLUG, ticket, agent_id, "work", "")
    if etat_livre:
        constats.fin_de_run(SLUG, ticket["id"], agent_id, "final_answer")
    return tickets.get_ticket(SLUG, ticket["id"])
