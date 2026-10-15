# [desc] Ce que les Bash d'un agent ont lancé (background=true ou `cmd &`) s'arrête quand l'agent clôt, et au plus tard quand son worktree est supprimé. [/desc]
"""Cas réel (2026-09-25) : `python3 server.py --port 8010 &`, lancé par le Bash d'un agent de
l'essai précédent, tournait encore 3 h après la fin de l'agent, dans un worktree supprimé.

Chaque test lance des `sleep <nombre unique>` : on ne regarde QUE ses propres processus,
retrouvés par leur ligne de commande, et on les tue en sortie quoi qu'il arrive.
"""
from __future__ import annotations

import subprocess
import sys
import time
import uuid

import psutil
import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="`sleep` et `&` : shell POSIX")


def _duree_unique() -> str:
    return str(900000 + uuid.uuid4().int % 90000)


def _sleeps(duree: str) -> list[psutil.Process]:
    trouves = []
    for proc in psutil.process_iter(["cmdline"]):
        if (proc.info.get("cmdline") or [])[-2:] == ["sleep", duree]:
            trouves.append(proc)
    return trouves


def _attendre_absence(duree: str, limite: float = 10.0) -> list[psutil.Process]:
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        restants = [p for p in _sleeps(duree) if p.status() != psutil.STATUS_ZOMBIE]
        if not restants:
            return []
        time.sleep(0.05)
    return _sleeps(duree)


def _attendre_presence(duree: str, limite: float = 10.0) -> list[psutil.Process]:
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        if _sleeps(duree):
            return _sleeps(duree)
        time.sleep(0.05)
    return []


@pytest.fixture
def menage():
    durees: list[str] = []
    yield durees
    for duree in durees:
        for proc in _sleeps(duree):
            proc.kill()


def _bash(ident: str, commande: str, fond: bool = False) -> str:
    extra = '<param name="background">true</param>' if fond else ""
    return (f'<tool_use name="Bash" id="{ident}"><param name="command">{commande}</param>'
            f'{extra}</tool_use>')


def test_la_cloture_de_l_agent_arrete_les_processus_lances_par_ses_bash(menage):
    """Un serveur lancé en background=true et un autre lancé par `&` meurent à la clôture."""
    fond, esperluette = _duree_unique(), _duree_unique()
    menage.extend([fond, esperluette])
    mock = MockLLM([
        _bash("b1", f"sleep {fond}", fond=True)
        + _bash("b2", f"sleep {esperluette} > /dev/null 2>&1 &"),
        "Les deux serveurs tournent, j'ai fini.",
    ])

    bouzecode(["lance deux serveurs de test puis termine"], mock_llm=mock)

    assert _attendre_absence(fond) == [], "le Bash background=true survit à la clôture"
    assert _attendre_absence(esperluette) == [], "le `cmd &` survit à la clôture"


def test_un_processus_etranger_aux_bash_de_l_agent_survit_a_sa_cloture(menage):
    """Contrôle : seul ce que les Bash de l'agent ont lancé est visé, pas un voisin."""
    etranger = _duree_unique()
    menage.append(etranger)
    voisin = subprocess.Popen(["sleep", etranger], start_new_session=True)
    mock = MockLLM([_bash("b1", "echo prêt"), "Fini."])

    bouzecode(["dis prêt puis termine"], mock_llm=mock)

    assert voisin.poll() is None
    voisin.kill()
    voisin.wait()


def test_supprimer_le_worktree_arrete_le_processus_orphelin_qui_y_tourne(menage, tmp_path):
    """Agent tué sans clôture : son `cmd &` orphelin s'arrête quand son worktree est rangé."""
    from bouzecode.backend.tools.ops.bash_bg import MARQUEUR
    from bouzecode.web_v2.services.work import worktrees

    depot = tmp_path / "depot"
    depot.mkdir()
    for args in (["init", "-b", "main"], ["commit", "--allow-empty", "-m", "init"]):
        subprocess.run(["git", "-C", str(depot), "-c", "user.name=t", "-c", "user.email=t@t",
                        *args], check=True, capture_output=True)
    meta = worktrees.provision(str(depot), "ab12cd34", base_branch="main")
    orphelin = _duree_unique()
    menage.append(orphelin)
    #  Ce qu'un Bash d'agent aurait laissé : un shell parti, un `sleep` reparenté, marqué.
    env = {"PATH": "/usr/bin:/bin", MARQUEUR: "12345-1"}
    subprocess.run(f"sleep {orphelin} > /dev/null 2>&1 &", shell=True, cwd=meta["worktree"],
                   env=env, start_new_session=True, check=True)
    assert _attendre_presence(orphelin), "le processus de l'essai n'a pas démarré"

    worktrees.reap(meta)

    assert _attendre_absence(orphelin) == []
