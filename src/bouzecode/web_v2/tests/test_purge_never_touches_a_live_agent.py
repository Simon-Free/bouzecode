# [desc] La purge ne doit JAMAIS déplacer les artefacts d'un agent vivant. [/desc]
"""Déplacer le dossier d'un agent en vol le rend INTROUVABLE, pas « rangé ».

Mesuré le 2026-07-28 sur le manager `0123456789ab` : ses artefacts (dont 1,45 Mo de
session) ont été déplacés dans `_trash/` à 12:25 alors qu'il tournait encore. Dès lors
`runner.load_agent` renvoyait None → `POST /api/agents/<id>/continue` répondait 404,
l'agent avait disparu de l'arbre de flotte, et les messages envoyés depuis l'interface
étaient perdus en silence. Il est resté près de quatre heures injoignable.

CES TESTS NE VISENT AUCUN ARTEFACT NI PROCESS RÉEL : parc isolé par le conftest, et les
seuls process vivants sont des python jetables fabriqués ici et tués ici.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time

import psutil
import pytest

from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2.services.sessions import purge
from bouzecode.web_v2.tests.production_isolation import autoriser_la_destruction


@pytest.fixture()
def process_jetable():
    """Fabrique des process python À NOUS, tués ici quoi qu'il arrive."""
    lances: list[subprocess.Popen] = []

    def lancer(marqueur: str) -> subprocess.Popen:
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)", marqueur])
        fin = time.time() + 5
        while time.time() < fin and not runner.session_process_running(marqueur):
            time.sleep(0.05)
        assert runner.session_process_running(marqueur), "process témoin invisible"
        lances.append(proc)
        return proc

    yield lancer

    for proc in lances:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)


def _poser_un_agent(agent_id: str, *, prompt: str = "test purge", **etat) -> runner.Agent:
    """Écrit un vrai agent dans le parc ISOLÉ et renvoie l'objet chargé."""
    session_path = str(runner.AGENTS_DIR / f"{agent_id}.session.json")
    donnees = {
        "agent_id": agent_id, "prompt": prompt, "model": "", "cwd": "",
        "pid": 0, "started_at": "2026-07-27T13:16:36Z", "returncode": None,
        "session_path": session_path, "stdout_path": "", "ipc_dir": "",
        **etat,
    }
    (runner.AGENTS_DIR / f"{agent_id}.json").write_text(json.dumps(donnees),
                                                        encoding="utf-8")
    (runner.AGENTS_DIR / f"{agent_id}.session.json").write_text(
        json.dumps({"messages": []}), encoding="utf-8")
    runner._list_agents_cache.clear()
    return runner.load_agent(agent_id)


def test_un_agent_dont_le_process_tourne_n_est_jamais_purge(process_jetable, monkeypatch):
    """Le scénario exact de l'incident : les champs du .json disent « terminé », le
    process dit le contraire — et c'est le process qui a raison.

    `returncode`/`finished_at` sont renseignés (c'est `refresh_agent_status` qui les a
    écrits, deux millisecondes avant le déplacement fatal). Seule l'autorité OS empêche
    la destruction."""
    autoriser_la_destruction(monkeypatch)
    agent = _poser_un_agent("vivant01", returncode=0,
                            finished_at="2026-07-28T10:25:53.899593Z")
    process_jetable(agent.session_path)  # un process porte encore SA session

    resultat = purge.purge_agents(["vivant01"])

    assert resultat["purged"] == []
    assert [s["reason"] for s in resultat["skipped"]] == ["agent vivant"]
    assert (runner.AGENTS_DIR / "vivant01.json").exists()
    assert runner.load_agent("vivant01") is not None, "l'agent est devenu introuvable"


def test_un_agent_qui_attend_une_reponse_humaine_n_est_pas_un_dechet(monkeypatch):
    """Process éteint mais question posée : une conversation en pause n'est pas un déchet,
    quel que soit l'âge de ses fichiers."""
    autoriser_la_destruction(monkeypatch)
    agent = _poser_un_agent("attente01", returncode=0, finished_at="2026-07-28T10:00:00Z")
    monkeypatch.setattr(purge.store, "agent_status",
                        lambda a: {"state": "awaiting_input"})

    assert purge.est_vivant(agent) is True
    assert purge.purge_agents(["attente01"])["purged"] == []
    assert (runner.AGENTS_DIR / "attente01.json").exists()


def test_un_agent_reellement_mort_est_bien_purge(monkeypatch):
    """Contre-preuve indispensable : la garde n'a pas simplement tout gelé.

    Sans elle, les assertions « rien n'a bougé » ci-dessus seraient vraies pour une
    mauvaise raison — une purge cassée les satisferait toutes."""
    autoriser_la_destruction(monkeypatch)
    _poser_un_agent("mort01", returncode=-1, finished_at="2026-07-28T10:00:00Z")
    monkeypatch.setattr(purge.store, "agent_status", lambda a: {"state": "finished"})

    resultat = purge.purge_agents(["mort01"])

    assert resultat["purged"] == ["mort01"]
    assert not (runner.AGENTS_DIR / "mort01.json").exists()
    assert (purge.TRASH_DIR / "mort01" / "mort01.json").exists()  # déplacé, jamais effacé


def test_archiver_ne_rend_jamais_un_agent_introuvable(monkeypatch):
    """Archiver = cacher des listes, PAS déplacer les fichiers.

    C'est la régression qui a coûté quatre heures : l'archivage déplaçait les artefacts,
    donc `load_agent` renvoyait None et l'interface répondait 404 « agent inconnu »."""
    autoriser_la_destruction(monkeypatch)
    _poser_un_agent("archive01", prompt="une vraie conversation utilisateur")

    resultat = purge.archive_agents(["archive01"])

    assert resultat["archived"] == ["archive01"]
    assert purge.is_deleted("agent/archive01"), "la clé doit être au registre"
    assert runner.load_agent("archive01") is not None, "404 « agent inconnu » de retour"
    assert (runner.AGENTS_DIR / "archive01.session.json").exists()


def test_aucune_purge_n_est_possible_depuis_un_test():
    """Le garde-fou de production : SANS levée explicite, aucun artefact ne bouge.

    Tout est réuni pour une purge légitime — agent de test, mort, non répondant. Elle
    n'a quand même pas lieu, parce qu'on est sous pytest. C'est le filet qui aurait
    évité l'incident : avant le 2026-07-28 14:16, aucun conftest n'isolait `AGENTS_DIR`,
    `TRASH_DIR` ni `DELETED_PATH`."""
    _poser_un_agent("sousPytest01", returncode=-1, finished_at="2026-07-28T10:00:00Z")

    resultat = purge.purge_agents(["sousPytest01"])

    assert resultat["purged"] == []
    assert (runner.AGENTS_DIR / "sousPytest01.json").exists()


def test_la_vivacite_ne_se_deduit_jamais_des_champs_du_json(process_jetable, monkeypatch):
    """`est_vivant` ne conclut pas « mort » sur la foi de `returncode`/`finished_at`.

    Ces champs sont écrits par un AUTRE process et peuvent être périmés ; l'autorité OS,
    elle, ne ment pas. Sans process témoin le même agent est déclaré mort : la différence
    vient donc bien du process, pas des champs."""
    monkeypatch.setattr(purge.store, "agent_status", lambda a: {"state": "finished"})
    agent = _poser_un_agent("preuve01", returncode=0, finished_at="2026-07-28T10:00:00Z")

    assert purge.est_vivant(agent) is False

    process_jetable(agent.session_path)

    assert purge.est_vivant(agent) is True
