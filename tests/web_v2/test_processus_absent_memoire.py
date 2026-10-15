"""`runner.processus_absent` : une absence constatée est définitive et mémorisée par identité de
process (pid, instant de création) ; une présence est revérifiée à chaque appel.

Sous Windows, vérifier un pid recyclé énumère tous les process : l'arbre des agents le faisait
trois fois par agent et par requête. Faux psutil minimal : on compte les appels système."""
import os
from types import SimpleNamespace

import psutil
import pytest

from bouzecode.web_v2.runtime.runner import agent_vivacite


@pytest.fixture(autouse=True)
def memoire_vide():
    agent_vivacite._absences.clear()
    yield
    agent_vivacite._absences.clear()


class _Espion:
    def __init__(self, monkeypatch, vivants: dict):
        """`vivants` : {pid: instant de création réel}."""
        self.appels = []
        self.vivants = vivants
        monkeypatch.setattr(agent_vivacite.psutil, "pid_exists", self.pid_exists)
        monkeypatch.setattr(agent_vivacite.psutil, "Process", self.process)

    def pid_exists(self, pid):
        self.appels.append(("pid_exists", pid))
        return pid in self.vivants

    def process(self, pid):
        espion = self

        class _Proc:
            def create_time(self):
                espion.appels.append(("create_time", pid))
                return espion.vivants[pid]

            def status(self):
                espion.appels.append(("status", pid))
                return psutil.STATUS_RUNNING

            def name(self):
                return "autre.exe"

        return _Proc()


def _agent(pid, instant=0.0):
    return SimpleNamespace(pid=pid, pid_create_time=instant)


def test_process_disparu_constate_une_fois(monkeypatch):
    espion = _Espion(monkeypatch, {})
    raisons = [agent_vivacite.processus_absent(_agent(4242, 100.0)) for _ in range(5)]
    assert raisons == ["processus disparu (pid 4242)"] * 5
    assert len(espion.appels) == 1


def test_pid_recycle_constate_une_fois(monkeypatch):
    espion = _Espion(monkeypatch, {4242: 999.0})
    raisons = {agent_vivacite.processus_absent(_agent(4242, 100.0)) for _ in range(5)}
    assert raisons == {"pid 4242 réutilisé par un autre programme (autre.exe)"}
    assert len(espion.appels) == 2  # pid_exists + create_time, une seule fois


def test_process_vivant_reverifie_a_chaque_appel(monkeypatch):
    """Une présence n'est jamais mémorisée : un agent mort entre deux appels est vu mort."""
    espion = _Espion(monkeypatch, {4242: 100.0})
    agent = _agent(4242, 100.0)
    assert agent_vivacite.processus_absent(agent) == ""
    assert agent_vivacite.processus_absent(agent) == ""
    del espion.vivants[4242]
    assert agent_vivacite.processus_absent(agent) == "processus disparu (pid 4242)"
    assert sum(1 for nom, _ in espion.appels if nom == "pid_exists") == 3


def test_nouveau_spawn_meme_pid_nouvelle_identite(monkeypatch):
    """Un respawn qui retombe sur le même pid porte un autre instant de création : l'absence
    mémorisée de l'ancien process ne le condamne pas."""
    espion = _Espion(monkeypatch, {})
    assert agent_vivacite.processus_absent(_agent(4242, 100.0))
    espion.vivants[4242] = 200.0
    assert agent_vivacite.processus_absent(_agent(4242, 200.0)) == ""


def test_statut_non_lu_sous_windows(monkeypatch):
    """Pas de zombie sous Windows, et y lire le statut énumère tous les process."""
    espion = _Espion(monkeypatch, {4242: 100.0})
    monkeypatch.setattr(agent_vivacite, "_ZOMBIES_POSSIBLES", False)
    assert agent_vivacite.processus_absent(_agent(4242, 100.0)) == ""
    assert ("status", 4242) not in espion.appels
    monkeypatch.setattr(agent_vivacite, "_ZOMBIES_POSSIBLES", True)
    assert agent_vivacite.processus_absent(_agent(4242, 100.0)) == ""
    assert ("status", 4242) in espion.appels


def test_vrai_process_courant_vivant():
    moi = psutil.Process(os.getpid())
    assert agent_vivacite.processus_absent(_agent(os.getpid(), moi.create_time())) == ""
