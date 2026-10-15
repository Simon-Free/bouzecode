# [desc] Un seul serveur de référence par parc (verrou OS) : les autres instances, et tout create_app() de script, restent passives — ni watchdog, ni ménage, ni reprise auto. [/desc]
"""Le 2026-09-29, un serveur de fumée lancé par un agent (`create_app(); app.run(5099)`) sur les
vraies données armait son propre watchdog et balayait la flotte réelle en parallèle du serveur
de production. Cf. `web_v2/reference.py`.

Vrais process : le verrou est un verrou OS, on le vérifie donc entre deux process ; le serveur
passif est un vrai `python -m bouzecode.web_v2`, au HOME isolé.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import bouzecode
from bouzecode.web_v2 import reference
from bouzecode.web_v2.runtime.runner import agent_fiche
from bouzecode.web_v2.services.work import wake

SRC = str(Path(bouzecode.__file__).resolve().parents[1])


@pytest.fixture(autouse=True)
def _rendre_le_verrou():
    yield
    reference.relacher()


def _autre_process_acquiert(parc: Path) -> bool:
    code = ("import sys; from bouzecode.web_v2.runtime.runner import agent_fiche; "
            "from bouzecode.web_v2 import reference; from pathlib import Path; "
            f"agent_fiche.AGENTS_DIR = Path(r'{parc}'); sys.exit(0 if reference.acquerir(1) else 3)")
    fini = subprocess.run([sys.executable, "-c", code], env={**os.environ, "PYTHONPATH": SRC},
                          timeout=120)
    return fini.returncode == 0


def test_un_seul_process_tient_le_role_de_reference():
    assert reference.acquerir(5056) is True and reference.est_reference()
    assert reference.detenteur()["pid"] == os.getpid()
    assert _autre_process_acquiert(agent_fiche.AGENTS_DIR) is False, "deux références sur un parc"
    reference.relacher()
    assert _autre_process_acquiert(agent_fiche.AGENTS_DIR) is True, "le verrou tombe avec son détenteur"


def test_hors_reference_le_watchdog_ne_demarre_pas(monkeypatch):
    """`create_app()` appelle `wake.start_poller()` : dans un script, il ne doit rien armer."""
    monkeypatch.delenv("BOUZECODE_WAKE_POLLER", raising=False)
    monkeypatch.setattr(wake, "_poller_started", False)
    wake.start_poller()
    assert wake._poller_started is False
    assert "wake-poller" not in {t.name for t in threading.enumerate()}


def _port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_un_second_serveur_sur_le_meme_parc_se_declare_passif(tmp_path):
    home = tmp_path / "home"
    parc = home / ".bouzecode" / "web_agents"
    parc.mkdir(parents=True)
    runner_parc_du_test = agent_fiche.AGENTS_DIR
    agent_fiche.AGENTS_DIR = parc
    try:
        assert reference.acquerir(5056)  # « le serveur de production » tient ce parc
    finally:
        agent_fiche.AGENTS_DIR = runner_parc_du_test
    env = {**os.environ, "PYTHONPATH": SRC, "USERPROFILE": str(home), "HOME": str(home),
           "PYTHONIOENCODING": "utf-8"}
    for variable in ("BOUZECODE_WAKE_POLLER", "PYTEST_CURRENT_TEST"):
        env.pop(variable, None)
    serveur = subprocess.Popen([sys.executable, "-m", "bouzecode.web_v2", "--port",
                                str(_port_libre())], env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    lignes: list[str] = []
    try:
        limite = time.monotonic() + 90
        while time.monotonic() < limite and not any("PASSIVE" in ligne for ligne in lignes):
            ligne = serveur.stdout.readline()
            if not ligne:
                break
            lignes.append(ligne)
    finally:
        serveur.kill()
        serveur.wait(timeout=10)
    sortie = "".join(lignes)
    assert "instance PASSIVE" in sortie, sortie[-2000:]
    assert "reprise auto" not in sortie.split("instance PASSIVE")[0]
