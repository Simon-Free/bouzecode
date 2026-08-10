# [desc] Le garde-fou de clôture ne coûte rien au watchdog : ni lecture d'agent, ni écriture répétée. [/desc]
"""Coût du garde-fou de clôture, payé à CHAQUE tick du watchdog (toutes les 8 s).

Même méthode que `test_wake_watchdog_idle_cost` : les coutures d'I/O sont espionnées par un
compteur qui DÉLÈGUE ensuite à la vraie implémentation. Deux garanties : le garde-fou ne
rouvre AUCUN fichier agent ni session (ses prédicats sont purs sur les tickets déjà chargés
par `wake._children_by_parent`), et il n'écrit dans le store que lorsque la situation de
blocage CHANGE — un manager bloqué depuis une heure ne coûte plus rien.
"""
from __future__ import annotations

import pytest

from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2.services.sessions import store
from bouzecode.web_v2.services.work import _persistence, closure_guard, wake
from bouzecode.web_v2.services.work import tickets as tickets_svc

SLUG = "projet-du-cout"
MANAGER_AGENT = "mgr-cout"


class _ParentAgent:
    def __init__(self, slug: str, ticket_id: str):
        self.ticket_slug, self.ticket_id = slug, ticket_id


@pytest.fixture()
def agent_reads(monkeypatch) -> list[str]:
    """Compte les lectures de fichiers agent / de sessions, puis délègue au vrai code."""
    reads: list[str] = []
    real_load_agent, real_load_session = runner.load_agent, store.load_session_json
    monkeypatch.setattr(runner, "load_agent",
                        lambda agent_id: reads.append(f"agent:{agent_id}") or real_load_agent(agent_id))
    monkeypatch.setattr(store, "load_session_json",
                        lambda path: reads.append(f"session:{path}") or real_load_session(path))
    return reads


@pytest.fixture()
def store_writes(monkeypatch) -> list[str]:
    """Compte les écritures de lignes de tickets, puis délègue au vrai code."""
    writes: list[str] = []
    real_upsert = _persistence._upsert_one
    monkeypatch.setattr(_persistence, "_upsert_one",
                        lambda conn, slug, ticket: writes.append(ticket["id"]) or real_upsert(conn, slug, ticket))
    return writes


@pytest.fixture()
def blocked_manager() -> tuple[dict, list[dict]]:
    """Un manager fini dont l'unique enfant a planté sans rien livrer."""
    manager = tickets_svc.create_ticket(SLUG, "pilotage", "orchestre")
    manager["typology"] = "manager"
    tickets_svc.update_ticket(SLUG, manager)
    tickets_svc.add_run(SLUG, manager, MANAGER_AGENT, "work", "opus", typology="manager")

    child = tickets_svc.create_ticket(SLUG, "stockage azure", "adapte le stockage")
    child["parent"] = MANAGER_AGENT
    tickets_svc.update_ticket(SLUG, child)
    tickets_svc.add_run(SLUG, child, "coder-mort", "work", "opus", typology="coder")
    child["crashed"] = True
    tickets_svc.update_ticket(SLUG, child)
    return manager, [child]


def test_the_guard_never_reopens_an_agent_file_or_a_session(blocked_manager, agent_reads):
    """Juger la livraison des enfants ne rouvre ni un fichier agent ni une session."""
    manager, children = blocked_manager

    assert closure_guard.refuse_closure(SLUG, manager, children)

    assert agent_reads == []


def test_a_standing_block_costs_no_store_write_on_the_next_ticks(blocked_manager, store_writes):
    """Un blocage inchangé n'est écrit qu'UNE fois : les ticks suivants n'écrivent plus rien."""
    manager, children = blocked_manager

    closure_guard.refuse_closure(SLUG, manager, children)
    writes_after_first_tick = list(store_writes)
    for _ in range(5):
        closure_guard.refuse_closure(SLUG, manager, children)

    assert writes_after_first_tick == [manager["id"]], "la trace doit coûter une seule écriture"
    assert store_writes == writes_after_first_tick, "les ticks suivants ont réécrit le store"


def test_finalizing_a_blocked_manager_costs_one_ticket_read_and_nothing_else(
        blocked_manager, agent_reads, store_writes, monkeypatch):
    """Un tick sur un manager déjà bloqué : aucune écriture, aucune session rouverte — le
    coût se réduit à la relecture du ticket manager que la finalisation faisait déjà."""
    manager, children = blocked_manager
    parent_agent = _ParentAgent(SLUG, manager["id"])
    wake._finalize_noncoding_parent(parent_agent, children)  # 1er tick : pose la trace
    store_writes.clear()
    agent_reads.clear()

    connections: list[str] = []
    real_connect = _persistence._connect
    monkeypatch.setattr(_persistence, "_connect",
                        lambda: connections.append("connexion") or real_connect())

    assert wake._finalize_noncoding_parent(parent_agent, children) is False

    assert store_writes == []
    assert agent_reads == []
    assert len(connections) == 1, "une seule requête store : la relecture du ticket manager"
