# [desc] `bouzecode tickets creer --cible rundeck` puis `tickets suivre` SANS serveur : la CLI fait elle-même suivre/recuperer comme le watchdog (faux Rundeck + faux share, paquet joué par vm_runner) jusqu'à la branche agent/<ticket>. [/desc]
from __future__ import annotations

import pytest

from bouzecode.web_v2.services.work import tickets
from bouzecode.web_v2.services.work.distant import suivi as suivi_distant
from bouzecode.web_v2.tests import faux_rundeck_vm
from bouzecode.web_v2.tests.cli_tickets_aides import cli, cli_json, depot_demo, git
from bouzecode.web_v2.tests.test_rundeck_bout_en_bout import AGENT_VM, _script_vm


@pytest.fixture()
def rundeck(monkeypatch):
    etat, serveur = faux_rundeck_vm.demarrer(monkeypatch)
    yield etat
    serveur.shutdown()


@pytest.fixture()
def horloge_qui_avance(monkeypatch):
    """Chaque lecture de l'horloge du suivi avance au-delà de la cadence : un pas = une lecture."""
    instant = [1000.0]

    def lire() -> float:
        instant[0] += suivi_distant.CADENCE_S + 1
        return instant[0]
    monkeypatch.setattr(suivi_distant, "HORLOGE", lire)
    suivi_distant.oublier_cadence()


def test_creer_sur_rundeck_puis_suivre_jusqu_a_la_branche_importee(
        tmp_path, capsys, rundeck, horloge_qui_avance):
    depot = depot_demo(tmp_path)
    code, corps = cli_json(capsys, "tickets", "creer", "--projet", "demo", "--titre",
                           "b sur la vm", "--prompt", "Ajoute b.txt", "--cible", "rundeck",
                           "--commande", _script_vm(tmp_path, AGENT_VM),
                           "--fichier", "notes/plan.md", "--fichier", ".env")
    assert code == 0, corps
    assert corps["via"] == "process" and corps["distant"]["ok"]
    assert ".env" in str(corps["distant"]["fichiers_refuses"]["demo"])
    ticket_id = corps["ticket_id"]
    ticket = tickets.get_ticket("demo", ticket_id)
    assert ticket["runs"][0]["kind"] == "remote" and ticket["distant"]["url"]

    code, texte, _ = cli(capsys, "tickets", "voir", "demo", ticket_id)
    assert "Rundeck : exécution" in texte and "REFUSÉS" in texte

    code, texte, _ = cli(capsys, "tickets", "suivre", "demo", ticket_id, "--intervalle", "0",
                         "--delai", "60")
    assert code == 0, texte
    assert "delivered" in texte
    assert git(depot, "show", f"agent/{ticket_id}:b.txt") == "ecrit sur la vm"
    run, = tickets.get_ticket("demo", ticket_id)["runs"]
    assert run["termine"] and run["issue"] == "livre"


def test_cible_rundeck_sans_lancement_est_refusee(tmp_path, capsys):
    depot_demo(tmp_path)
    code, corps = cli_json(capsys, "tickets", "creer", "--projet", "demo", "--titre", "t",
                           "--prompt", "p", "--cible", "rundeck", "--brouillon")
    assert code == 1 and corps["error"]["code"] == "options_distantes"
