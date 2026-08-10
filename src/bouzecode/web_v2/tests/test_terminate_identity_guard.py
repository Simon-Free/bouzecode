# [desc] Preuve d'identité avant terminate() : un pid recyclé ne doit jamais être tué. [/desc]
"""Tuer un pid sans vérifier que c'est ENCORE le bon process détruit le travail d'autrui.

Un pid est recyclé par l'OS dès que son process meurt. L'agent visé lors de l'incident
portait `returncode=0` et `finished_at` : il était fini depuis longtemps, et le pid tracké
désignait un process TIERS arbitraire de la machine. Le `terminate()` n'a été refusé que
par les ACL Windows.

CES TESTS NE VISENT AUCUN PROCESS RÉEL : les seules cibles vivantes sont des process
python jetables fabriqués ici et tués ici.
"""
from __future__ import annotations

import subprocess
import sys
import time

import psutil
import pytest

from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2.services.work import fleet, warm_pool
from bouzecode.web_v2.tests.production_isolation import autoriser_la_destruction


@pytest.fixture()
def process_jetable():
    """Fabrique des process python À NOUS et les tue en fin de test, quoi qu'il arrive.

    L'argument passé sur la ligne de commande sert de marqueur : c'est ce que la preuve
    d'identité lit (le `--session-file` d'un vrai agent joue ce rôle)."""
    lances: list[subprocess.Popen] = []

    def lancer(marqueur: str = "aucun-marqueur") -> subprocess.Popen:
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)", marqueur])
        fin = time.time() + 5
        while time.time() < fin and not _cmdline_visible(proc.pid):
            time.sleep(0.05)
        assert _cmdline_visible(proc.pid), "psutil ne voit pas encore le process témoin"
        lances.append(proc)
        return proc

    yield lancer

    for proc in lances:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)


def _cmdline_visible(pid: int) -> bool:
    return bool(psutil.Process(pid).cmdline())


def _agent_visant(pid: int, session_path: str, **etat) -> runner.Agent:
    """Un agent dont le pid tracké est `pid` et dont la session est `session_path`."""
    return runner.Agent(agent_id="cible01", prompt="p", model="", cwd="", pid=pid,
                        started_at="2026-07-28T10:00:00Z", session_path=session_path,
                        **etat)


def test_un_pid_recycle_n_est_pas_tue(process_jetable, monkeypatch, tmp_path):
    """Même pid, AUTRE process : la terminaison est refusée et le process survit.

    C'est le scénario exact de l'incident : l'agent est parti, l'OS a redonné son pid à
    un process étranger, et le balayage visait ce dernier."""
    autoriser_la_destruction(monkeypatch)
    etranger = process_jetable("un-process-qui-n-est-pas-un-agent")
    session = str(tmp_path / "cible01.session.json")

    tue = runner.terminate_agent_process(_agent_visant(etranger.pid, session))

    assert tue is False
    assert etranger.poll() is None, "un process TIERS a été terminé"


def test_le_process_de_l_agent_est_bien_tue(process_jetable, monkeypatch, tmp_path):
    """Contre-preuve indispensable : quand le pid est ENCORE celui de l'agent, on tue.

    Sans elle, le refus ci-dessus serait vrai pour une mauvaise raison — une preuve
    d'identité toujours fausse satisferait tous les autres tests de ce fichier."""
    autoriser_la_destruction(monkeypatch)
    session = str(tmp_path / "cible01.session.json")
    agent_vivant = process_jetable(session)  # sa command line PORTE la session

    tue = runner.terminate_agent_process(_agent_visant(agent_vivant.pid, session))

    assert tue is True
    assert agent_vivant.wait(timeout=5) is not None


def test_un_agent_deja_termine_n_est_jamais_candidat(process_jetable, monkeypatch, tmp_path):
    """Un agent avec `returncode`/`finished_at` renseignés ne peut plus rien faire tuer.

    Son pid est libre depuis son extinction : c'est le point de départ du recyclage. Ici
    le process porte pourtant le BON marqueur — seul l'état « déjà fini » le sauve."""
    autoriser_la_destruction(monkeypatch)
    session = str(tmp_path / "cible01.session.json")
    homonyme = process_jetable(session)
    fini = _agent_visant(homonyme.pid, session,
                         returncode=0, finished_at="2026-07-28T11:00:00Z")

    tue = runner.terminate_agent_process(fini)

    assert tue is False
    assert homonyme.poll() is None


def test_aucune_terminaison_n_est_possible_depuis_un_test(process_jetable, tmp_path):
    """Le garde-fou de production : SANS levée explicite, rien ne peut être terminé.

    Le process porte le bon marqueur, l'agent est en vol : tout est réuni pour un kill
    légitime. Il n'a quand même pas lieu, parce qu'on est sous pytest."""
    session = str(tmp_path / "cible01.session.json")
    parfaitement_identifie = process_jetable(session)

    assert runner.destruction_permitted() is False
    tue = runner.terminate_agent_process(_agent_visant(parfaitement_identifie.pid, session))

    assert tue is False
    assert parfaitement_identifie.poll() is None


def test_le_balayage_du_warm_pool_est_inerte_sous_pytest(monkeypatch):
    """Le chemin de l'incident, fermé à la source : `sweep_warm_pool` n'évince RIEN
    depuis un test, même si un futur conftest oubliait d'isoler le parc d'agents.

    Le parc contient un agent CHAUD et le pool est plein à zéro : sans le garde-fou,
    la politique d'éviction le désignerait et `kill_agent` serait appelé (vérifié par
    mutation). On ENREGISTRE les appels au lieu de les faire lever : `sweep_warm_pool`
    attrape désormais toute exception pour ne pas interrompre la boucle d'éviction, et
    avalerait donc une sentinelle qui lève — le test passerait pour une mauvaise raison."""
    _ecrire_un_agent_chaud("evincable")
    appels = []

    monkeypatch.setattr(runner, "is_warm", lambda agent: True)
    monkeypatch.setattr(runner, "kill_agent", lambda agent: appels.append(agent.agent_id))
    monkeypatch.setattr(warm_pool, "WARM_POOL_MAX", 0)  # tout le parc est « en trop »

    assert fleet.sweep_warm_pool() == []
    assert appels == [], "kill_agent a été appelé depuis un test"


def test_un_refus_d_eviction_n_interrompt_pas_les_suivantes(monkeypatch):
    """Un agent impossible à évincer ne prive plus les AUTRES agents en trop du leur.

    Le refus réellement observé est `psutil.AccessDenied`, qui dérive de
    `psutil.Error(Exception)` et NON d'`OSError`. Attrapé par le mauvais type, il
    remontait jusqu'à `wake._sweep_warm_pool` et avortait la boucle ENTIÈRE : une seule
    éviction refusée et le warm-pool ne se vidait plus. Le refus est donc jeté sur le
    PREMIER agent balayé, et on vérifie que tous les suivants ont bien été tentés."""
    for numero in range(3):
        _ecrire_un_agent_chaud(f"chaud{numero}")
    autoriser_la_destruction(monkeypatch)
    tentatives, tues = [], []

    def _kill(agent):
        tentatives.append(agent.agent_id)
        if len(tentatives) == 1:
            raise psutil.AccessDenied(pid=agent.pid)
        tues.append(agent.agent_id)

    monkeypatch.setattr(runner, "is_warm", lambda agent: True)
    monkeypatch.setattr(runner, "kill_agent", _kill)
    monkeypatch.setattr(warm_pool, "WARM_POOL_MAX", 0)

    evinces = fleet.sweep_warm_pool()

    assert len(tentatives) == 3, "la boucle d'éviction s'est arrêtée au premier refus"
    assert set(evinces) == set(tues) == set(tentatives[1:])


def _ecrire_un_agent_chaud(agent_id: str) -> None:
    """Un vrai artefact d'agent dans le parc ISOLÉ (redirigé par le conftest autouse)."""
    import json

    (runner.AGENTS_DIR / f"{agent_id}.json").write_text(json.dumps({
        "agent_id": agent_id, "prompt": "une conversation", "model": "", "cwd": "",
        "pid": 999_999_999, "started_at": "2026-06-01T10:00:00Z", "returncode": None,
        "session_path": str(runner.AGENTS_DIR / f"{agent_id}.session.json"),
        "stdout_path": "", "ipc_dir": "",
    }), encoding="utf-8")
    runner._list_agents_cache.clear()


def test_le_garde_fou_s_efface_hors_pytest(monkeypatch):
    """Hors d'un test, le garde ne bloque rien : c'est bien pytest qu'il détecte, et le
    serveur (lancé par bouzeui.ps1) garde ses évictions."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    assert runner.destruction_permitted() is True
