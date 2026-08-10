# [desc] Un ticket « planté » dont l'agent est reparti perd son drapeau ; un agent vraiment mort le garde. [/desc]
"""Le drapeau `crashed` est RÉVOCABLE.

Histoire vécue : le watchdog déclare un manager planté, l'utilisateur le
reprend, l'agent repart, livre, puis redispatche — et le board continue d'afficher « planté »,
parce que seul `add_run` retirait le drapeau et qu'un manager repris ne crée AUCUN run sur SON
ticket. On joue donc la mort, puis la résurrection, et on vérifie enfin qu'un mort reste mort.
Aucun mock : la vivacité vient de vrais PID (celui du process de test pour un agent vivant)."""
from __future__ import annotations

import json
import os

import pytest

from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2.services.sessions import store
from bouzecode.web_v2.services.work import _persistence, fleet, projects, wake
from bouzecode.web_v2.services.work import tickets as tickets_svc

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
    monkeypatch.setattr(runner, "AGENTS_DIR", tmp_path / "agents")
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
        ticket["typology"] = typology
        tickets_svc.update_ticket(SLUG, ticket)
    tickets_svc.add_run(SLUG, ticket, agent_id, "work", "opus", typology=typology)
    _write_agent(agents_dir, agent_id, PID_INEXISTANT)
    for _ in range(wake._CRASH_DEAD_TICKS):
        wake.tick()
    planted = tickets_svc.get_ticket(SLUG, ticket["id"])
    assert planted["crashed"] is True and tickets_svc.derive_status(planted) == "planté"
    return planted


def test_a_resumed_agent_loses_the_planted_flag(agents_dir):
    """L'utilisateur reprend un agent déclaré planté : le ticket cesse d'afficher « planté »."""
    planted = _planted_ticket(agents_dir, "coder-repris")

    _write_agent(agents_dir, "coder-repris", os.getpid())  # reprise : un process vit de nouveau

    wake.tick()

    revenu = tickets_svc.get_ticket(SLUG, planted["id"])
    assert "crashed" not in revenu
    assert tickets_svc.derive_status(revenu) == "en cours"


def test_a_manager_that_delivered_since_loses_the_planted_flag(agents_dir):
    """Cas beefcafe : le manager déclaré planté a repris, livré son verdict, puis reclos son
    tour. Le verdict PROUVE qu'il n'a pas planté — le ticket redevient lisible."""
    planted = _planted_ticket(agents_dir, "manager-repris", typology="manager")
    planted["runs"][0]["verdict"] = "OK"  # verdict livré depuis, parsé par refresh_verdicts
    tickets_svc.update_ticket(SLUG, planted)

    wake.tick()

    revenu = tickets_svc.get_ticket(SLUG, planted["id"])
    assert "crashed" not in revenu
    assert tickets_svc.derive_status(revenu, parents_with_children=set()) == "à relire"


def test_a_genuinely_dead_agent_keeps_the_planted_flag(agents_dir):
    """Un agent mort qui ne revient jamais reste « planté », tick après tick."""
    planted = _planted_ticket(agents_dir, "coder-mort")

    for _ in range(3):
        wake.tick()

    toujours_mort = tickets_svc.get_ticket(SLUG, planted["id"])
    assert toujours_mort["crashed"] is True
    assert tickets_svc.derive_status(toujours_mort) == "planté"


def test_the_watchdog_keeps_watching_a_planted_ticket_that_has_delivered(agents_dir):
    """Un ticket planté dont le run porte un verdict reste inspecté : sans ça il sortait du
    filtre du watchdog exactement quand la preuve de son non-crash apparaissait."""
    planted = _planted_ticket(agents_dir, "coder-verdict")
    planted["runs"][0]["verdict"] = "OK"

    assert wake.ticket_needs_watchdog(planted) is True
