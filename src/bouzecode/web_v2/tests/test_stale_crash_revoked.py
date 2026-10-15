# [desc] Un ticket « planté » dont l'agent est reparti perd son drapeau ; un agent vraiment mort le garde. [/desc]
"""« Planté » est RÉVOCABLE (lot L2 : c'est un ÉTAT, `stopped{crashed}`, plus un drapeau).

Histoire vécue (ticket 642e1a3f) : le watchdog déclare un manager planté, l'utilisateur le
reprend, l'agent repart, livre, puis redispatche — et le board continue d'afficher « planté »,
parce que seul `add_run` retirait le drapeau et qu'un manager repris ne crée AUCUN run sur SON
ticket. Depuis L2, la reprise (`runner` → `runs_ticket.signaler(..., "message")`) est une
transition explicite `message_sent` → `running`. On joue donc la mort, puis la résurrection,
et on vérifie enfin qu'un mort reste mort.
Aucun mock : la vivacité vient de vrais PID (celui du process de test pour un agent vivant)."""
from __future__ import annotations

import json
import os

import pytest

from bouzecode.web_v2.runtime.runner import agent_fiche
from bouzecode.web_v2.services.sessions import store
from bouzecode.web_v2.services.work import _persistence, constats, fleet, projects, runs_ticket, wake
from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.services.work.fsm import etats

SLUG = "projet-du-revenant"
PID_INEXISTANT = 4_000_000


@pytest.fixture(autouse=True)
def _own_store(tmp_path, monkeypatch):
    monkeypatch.setattr(_persistence, "TICKETS_DIR", tmp_path / "tickets")
    monkeypatch.setattr(projects, "list_projects", lambda: [{"slug": SLUG, "name": "T"}])
    # Balayer le warm-pool pour de vrai tuerait des process de la machine (AGENTS_DIR global).
    monkeypatch.setattr(fleet, "sweep_warm_pool", lambda: [])


@pytest.fixture()
def agents_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_fiche, "AGENTS_DIR", tmp_path / "agents")
    (tmp_path / "agents").mkdir()
    return tmp_path / "agents"


def _write_agent(agents_dir, agent_id: str, pid: int) -> None:
    """Écrit le fichier agent tel que le runner le pose au (re)spawn : pas de returncode,
    donc `is_running` ne dépend que de l'existence du PID."""
    (agents_dir / f"{agent_id}.json").write_text(json.dumps({
        "agent_id": agent_id, "prompt": "fais le travail", "model": "opus",
        "cwd": str(agents_dir), "pid": pid, "started_at": "2026-07-27T10:00:00",
        "session_path": str(agents_dir / f"{agent_id}.session.json"),
    }), encoding="utf-8")
    (agents_dir / f"{agent_id}.session.json").write_text('{"messages": []}', encoding="utf-8")
    store.invalidate_status(agent_id)  # comme le respawn : le statut « finished » n'est plus vrai


def _planted_ticket(agents_dir, agent_id: str, typology: str = "") -> dict:
    """Un ticket dont l'agent est lancé puis meurt sans clore : le watchdog le déclare planté."""
    ticket = tickets_svc.create_ticket(SLUG, "mission", "fais le travail")
    if typology:
        tickets_svc.poser(SLUG, ticket, typology=typology)
    tickets_svc.set_launching(SLUG, ticket)
    tickets_svc.add_run(SLUG, ticket, agent_id, "work", "opus", typology=typology)
    _write_agent(agents_dir, agent_id, PID_INEXISTANT)
    for _ in range(constats.MORTS_AVANT_CRASH):
        wake.tick()
    planted = tickets_svc.get_ticket(SLUG, ticket["id"])
    assert planted["state"] == etats.STOPPED and tickets_svc.derive_status(planted) == "planté"
    return planted


def _reprendre(agents_dir, planted: dict, agent_id: str) -> dict:
    """Ce que fait le runtime à la reprise : un process vit de nouveau, le ticket le sait."""
    _write_agent(agents_dir, agent_id, os.getpid())
    runs_ticket.signaler(SLUG, planted["id"], agent_id, "message")
    return tickets_svc.get_ticket(SLUG, planted["id"])


def test_a_resumed_agent_loses_the_planted_flag(agents_dir):
    """L'utilisateur reprend un agent déclaré planté : le ticket cesse d'afficher « planté »."""
    planted = _planted_ticket(agents_dir, "coder-repris")
    _reprendre(agents_dir, planted, "coder-repris")

    wake.tick()  # l'agent vit : le watchdog ne le re-déclare pas mort

    revenu = tickets_svc.get_ticket(SLUG, planted["id"])
    assert revenu["state"] == etats.RUNNING
    assert tickets_svc.derive_status(revenu) == "en cours"


def test_a_manager_that_delivered_since_loses_the_planted_flag(agents_dir):
    """Cas 642e1a3f : le manager déclaré planté a repris, livré, puis reclos son tour. Sa
    clôture gracieuse PROUVE qu'il n'a pas planté — le ticket redevient lisible."""
    planted = _planted_ticket(agents_dir, "manager-repris", typology="manager")
    _reprendre(agents_dir, planted, "manager-repris")

    constats.fin_de_run(SLUG, planted["id"], "manager-repris", "final_answer", final_answer=True)

    revenu = tickets_svc.get_ticket(SLUG, planted["id"])
    assert revenu["state"] == etats.DELIVERED
    assert tickets_svc.derive_status(revenu) == "à relire"


def test_a_genuinely_dead_agent_keeps_the_planted_flag(agents_dir):
    """Un agent mort qui ne revient jamais reste « planté », tick après tick."""
    planted = _planted_ticket(agents_dir, "coder-mort")

    for _ in range(3):
        wake.tick()

    toujours_mort = tickets_svc.get_ticket(SLUG, planted["id"])
    assert toujours_mort["state"] == etats.STOPPED
    assert toujours_mort["version"] == planted["version"]  # aucune écriture de plus
    assert tickets_svc.derive_status(toujours_mort) == "planté"


def test_a_resumed_planted_ticket_is_watched_again(agents_dir):
    """Un ticket planté n'est plus inspecté (rien à constater) ; repris, il l'est de nouveau :
    sa prochaine mort ou sa livraison sera constatée."""
    planted = _planted_ticket(agents_dir, "coder-verdict")
    assert wake.ticket_needs_watchdog(planted) is False

    assert wake.ticket_needs_watchdog(_reprendre(agents_dir, planted, "coder-verdict")) is True
