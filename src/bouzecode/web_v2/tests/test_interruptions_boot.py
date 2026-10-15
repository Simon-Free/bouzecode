# [desc] Au redémarrage, un sous-agent interrompu est SIGNALÉ à son parent (ou à l'humain), jamais relancé d'office. [/desc]
"""Spec ticketing §11 D4 + principe B4 : la reprise automatique au boot (`auto_resume`) est
remplacée par un ÉVÉNEMENT. Le serveur constate l'interruption et prévient qui décide :
  * le parent manager joignable → un message mis en file (« relance-le si besoin ») ;
  * pas de parent joignable → un signalement pour l'humain.
Aucun agent n'est relancé, et un second boot ne re-signale pas. Vrais fichiers d'agent (PID
du process de test pour un parent vivant), vrai store, aucun mock."""
from __future__ import annotations

import json
import os

import pytest

from bouzecode.web_v2.runtime.runner import agent_fiche
from bouzecode.web_v2.services.sessions import store
from bouzecode.web_v2.services.work import (arret, file_messages, interruptions_boot,
                                             signalements)
from bouzecode.web_v2.services.work import tickets as tickets_svc

SLUG = "proj"
PARENT = "manager00001"
ENFANT = "enfant000001"
PID_INEXISTANT = 4_000_000


@pytest.fixture()
def agents_dir(tmp_path, monkeypatch):
    directory = tmp_path / "agents"
    directory.mkdir()
    monkeypatch.setattr(agent_fiche, "AGENTS_DIR", directory)
    return directory


def _fiche(agents_dir, agent_id: str, pid: int, returncode=None) -> None:
    (agents_dir / f"{agent_id}.json").write_text(json.dumps({
        "agent_id": agent_id, "prompt": "travaille", "model": "opus", "cwd": str(agents_dir),
        "pid": pid, "returncode": returncode, "started_at": "2026-10-05T10:00:00",
        "session_path": str(agents_dir / f"{agent_id}.session.json"),
    }), encoding="utf-8")
    (agents_dir / f"{agent_id}.session.json").write_text('{"messages": []}', encoding="utf-8")
    store.invalidate_status(agent_id)
    agent_fiche._list_agents_cache.clear()


def _enfant_interrompu(agents_dir) -> dict:
    """Le serveur redémarre : l'enfant d'un manager est mort sans clore son tour."""
    ticket = tickets_svc.create_ticket(SLUG, "sous-tâche", "fais X")
    ticket["parent"] = PARENT
    tickets_svc.update_ticket(SLUG, ticket)
    tickets_svc.add_run(SLUG, ticket, ENFANT, "work", "opus")
    _fiche(agents_dir, ENFANT, PID_INEXISTANT, returncode=-1)
    return ticket


def _runs(ticket: dict) -> list[dict]:
    return tickets_svc.get_ticket(SLUG, ticket["id"])["runs"]


def test_le_parent_vivant_est_prevenu_et_rien_n_est_relance(agents_dir):
    _fiche(agents_dir, PARENT, os.getpid())
    ticket = _enfant_interrompu(agents_dir)

    emis = interruptions_boot.signaler_les_interruptions()

    assert emis == [{"slug": SLUG, "ticket": ticket["id"], "agent_id": ENFANT, "a": PARENT}]
    [message] = file_messages.lister(PARENT)
    assert ENFANT in message["text"] and "redémarrage du serveur" in message["text"]
    assert "relance-le si besoin" in message["text"]
    runs = _runs(ticket)
    assert len(runs) == 1 and runs[0]["interruption_signalee"]["a"] == PARENT  # aucun run neuf
    assert agent_fiche.load_agent(ENFANT).returncode == -1  # l'enfant est toujours arrêté


def test_un_second_boot_ne_re_signale_pas(agents_dir):
    _fiche(agents_dir, PARENT, os.getpid())
    _enfant_interrompu(agents_dir)
    interruptions_boot.signaler_les_interruptions()

    assert interruptions_boot.signaler_les_interruptions() == []
    assert len(file_messages.lister(PARENT)) == 1


def test_sans_parent_joignable_l_humain_recoit_un_signalement(agents_dir):
    _fiche(agents_dir, PARENT, PID_INEXISTANT, returncode=-1)  # le manager est mort aussi
    ticket = _enfant_interrompu(agents_dir)

    [emis] = interruptions_boot.signaler_les_interruptions()

    assert emis["a"] == "signalement"
    assert file_messages.lister(PARENT) == []
    [signal] = [s for s in signalements.ouverts() if s["ticket_id"] == ticket["id"]]
    assert ENFANT in signal["titre"] and "/runs" in signal["action_attendue"]


def test_un_agent_arrete_volontairement_n_est_pas_signale(agents_dir):
    _fiche(agents_dir, PARENT, os.getpid())
    ticket = _enfant_interrompu(agents_dir)
    arret.poser(SLUG, tickets_svc.get_ticket(SLUG, ticket["id"]), "utilisateur")

    assert interruptions_boot.signaler_les_interruptions() == []
    assert file_messages.lister(PARENT) == []
