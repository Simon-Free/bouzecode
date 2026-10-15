# [desc] Lot L6 (reste de L0) : lire le fil d'un agent (/blocks, fiche, liste) ne LIVRE pas sa file de messages et ne DRAINE pas ses vérifications différées ; seul le tick du watchdog le fait. [/desc]
"""Avant : `GET /api/sessions/<key>/blocks` livrait en fond la file de messages d'un agent au
repos, et `refresh_agent_status` (appelé par toute lecture du parc) exécutait les vérifications
différées d'une clôture `final_answer_deferred` — commandes lancées, agent relancé, depuis un
GET. Ces deux gestes vivent désormais dans `wake.tick`."""
from __future__ import annotations

import os

import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.runtime import deferred
from bouzecode.web_v2.runtime.runner import agent_fiche, agent_reprise
from bouzecode.web_v2.services.work import file_messages, tick_annexes
from bouzecode.web_v2.tests.aides_tickets import fiche_agent

FINI, VIVANT = "f1ee00000001", "f1ee00000002"


class _Differees:
    answer = "réponse"
    checks = [{"command": "echo ok", "timeout": 5}]


@pytest.fixture()
def gestes(monkeypatch):
    """Ce qui relancerait un agent ou exécuterait ses vérifications : consigné, jamais fait."""
    faits: list[tuple] = []
    monkeypatch.setattr(agent_reprise, "_maybe_drain_deferred", lambda a: faits.append(("drain", a.agent_id)))
    monkeypatch.setattr(agent_reprise, "continue_agent", lambda a, t, **_: faits.append(("continue", t)))
    monkeypatch.setattr(agent_reprise, "resume_pending_agent", lambda a, t: faits.append(("resume", t)))
    return faits


def _agent_fini_avec_file_et_differes() -> agent_fiche.Agent:
    agent = fiche_agent(FINI, close_reason="final_answer_deferred")
    deferred.save(agent.session_path, _Differees())
    file_messages.mettre_en_file(FINI, "et les tests ?", "")
    return agent


def test_lire_le_fil_ne_livre_ni_ne_draine_rien(gestes):
    agent = _agent_fini_avec_file_et_differes()
    client = create_app().test_client()
    file_avant = file_messages.lister(FINI)

    for _ in range(10):
        for url in (f"/api/sessions/agent/{FINI}/blocks", f"/api/agents/{FINI}", "/api/agents",
                    f"/api/sessions/agent/{FINI}/recap", "/api/agents/tree"):
            assert client.get(url).status_code == 200, url

    assert gestes == []
    assert deferred.exists(agent.session_path)
    assert file_messages.lister(FINI) == file_avant


def test_le_tick_draine_les_differes_d_un_agent_fini_et_pas_d_un_agent_vivant(gestes):
    import time
    fini = _agent_fini_avec_file_et_differes()
    vivant = fiche_agent(VIVANT, close_reason="final_answer_deferred", pid=os.getpid())
    deferred.save(vivant.session_path, _Differees())

    assert tick_annexes.drainer_les_verifications_differees() == [FINI]
    limite = time.monotonic() + 5
    while ("drain", FINI) not in gestes and time.monotonic() < limite:
        time.sleep(0.02)
    assert gestes == [("drain", FINI)]
    assert deferred.exists(fini.session_path)  # le drain est consigné ici, pas exécuté
