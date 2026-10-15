# [desc] Coexistence `bouzecode tickets` / serveur web : serveur de référence vivant → écritures par son API (jeton local) et suivi en lecture seule ; absent → en process ; un serveur qui démarre pendant un pas de suivi de la CLI attend la fin du pas. [/desc]
"""Le verrou de référence est un verrou OS ENTRE process : un sous-process le tient (« le
serveur »), pendant que l'app Flask de test sert l'API sur un vrai port dans ce process —
celui qu'annonce la fiche du verrou. La CLI tourne en process, comme en production."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from werkzeug.serving import make_server

import bouzecode
from bouzecode.ui.tickets_cli import suivi
from bouzecode.web_v2 import reference
from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.runtime.runner import agent_fiche
from bouzecode.web_v2.services.work import tickets
from bouzecode.web_v2.tests.cli_tickets_aides import cli_json, depot_demo

SRC = str(Path(bouzecode.__file__).resolve().parents[1])


@pytest.fixture(autouse=True)
def _rendre_le_verrou():
    yield
    reference.relacher()


def _autre_process(code: str) -> subprocess.Popen:
    """Un process qui exécute `code` sur le parc du test, écrit « pret » puis dort."""
    programme = ("import sys, time; from pathlib import Path; "
                 "from bouzecode.web_v2.runtime.runner import agent_fiche; "
                 "from bouzecode.web_v2 import reference; "
                 f"agent_fiche.AGENTS_DIR = Path(r'{agent_fiche.AGENTS_DIR}'); {code}")
    process = subprocess.Popen([sys.executable, "-c", programme], stdout=subprocess.PIPE,
                               text=True, env={**os.environ, "PYTHONPATH": SRC})
    assert process.stdout.readline().strip() == "pret"
    return process


@pytest.fixture()
def serveur_vivant():
    """L'API Flask sur un vrai port, et un AUTRE process qui tient le verrou de référence en
    annonçant ce port (ce que fait `app.main` du serveur de production)."""
    serveur = make_server("127.0.0.1", 0, create_app(), threaded=True)
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    port = serveur.server_address[1]
    detenteur = _autre_process(f"assert reference.acquerir({port}); print('pret', flush=True); "
                               "time.sleep(120)")
    yield port
    detenteur.kill()
    detenteur.wait()
    serveur.shutdown()


def _creer(capsys) -> dict:
    code, corps = cli_json(capsys, "tickets", "creer", "--projet", "demo", "--titre", "t",
                           "--prompt", "p", "--brouillon")
    assert code == 0, corps
    return corps


def test_serveur_absent_la_cli_agit_en_process(tmp_path, capsys):
    depot_demo(tmp_path)
    assert reference.serveur_vivant() is False
    assert _creer(capsys)["via"] == "process"


def test_serveur_vivant_les_ecritures_passent_par_son_api(tmp_path, capsys, serveur_vivant):
    depot_demo(tmp_path)
    assert reference.serveur_vivant() is True
    corps = _creer(capsys)
    assert corps["via"] == "serveur" and corps["project_slug"] == "demo"
    ticket_id = corps["ticket_id"]
    code, corps = cli_json(capsys, "tickets", "clore", "demo", ticket_id, "--abandon")
    assert code == 0 and corps["via"] == "serveur"
    assert tickets.get_ticket("demo", ticket_id)["state"] == "abandoned"
    code, corps = cli_json(capsys, "tickets", "lancer", "demo", ticket_id)
    assert code == 1 and corps["error"]["code"] in ("transition_refusee", "deja_actif")


def test_serveur_vivant_le_pas_de_suivi_ne_fait_que_lire(tmp_path, serveur_vivant):
    with reference.pour_un_pas_cli() as seul:
        assert seul is False
    assert not reference.marque_du_pas_cli().exists()


def test_sans_serveur_le_pas_de_suivi_tient_le_verrou_puis_le_rend(tmp_path):
    with reference.pour_un_pas_cli() as seul:
        assert seul is True
        assert reference.marque_du_pas_cli().is_file()
    assert reference.serveur_vivant() is False
    assert reference.acquerir(5056) is True


def test_un_serveur_qui_demarre_pendant_un_pas_cli_attend_la_fin_du_pas(tmp_path):
    cli_en_cours = _autre_process("ctx = reference.pour_un_pas_cli(); assert ctx.__enter__(); "
                                  "print('pret', flush=True); time.sleep(1.5); "
                                  "ctx.__exit__(None, None, None); time.sleep(120)")
    try:
        debut = time.monotonic()
        assert reference.acquerir(5056) is True, "le serveur est resté passif"
        assert time.monotonic() - debut >= 1.0
    finally:
        cli_en_cours.kill()
        cli_en_cours.wait()


def test_code_de_fin_suit_la_table_de_cloture_cli():
    assert suivi.code_de_fin({"state": "running"}) is None
    assert suivi.code_de_fin({"state": "delivered"}) == 0
    assert suivi.code_de_fin({"state": "closed"}) == 0
    assert suivi.code_de_fin({"state": "idle_no_delivery",
                              "state_reason": {"code": "content_refusal"}}) == 3
    assert suivi.code_de_fin({"state": "idle_no_delivery",
                              "state_reason": {"code": "final_answer_never_called"}}) == 4
    assert suivi.code_de_fin({"state": "stopped", "state_reason": {"code": "crashed"}}) == 5
    assert suivi.code_de_fin({"state": "awaiting_input"}) == suivi.EXIT_QUESTION
