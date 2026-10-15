# [desc] Tests des routes /api/server/restart et /shutdown avec hooks injectés (aucun process tué, ordre spawn puis quit) [/desc]
"""Redémarrage/arrêt du serveur par lui-même.

Aucun process n'est tué ici et aucun port n'est touché : `server_control` accepte des
hooks INJECTÉS (`set_hooks`) à la place du vrai lancement détaché et du vrai `os._exit`.
C'est ce qui rend la fonctionnalité testable sans se suicider en cours de test.
"""
import os
import sys

import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services import server_control


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture(autouse=True)
def journal():
    """Remplace lancement et arrêt par un journal ordonné, puis remet les vrais hooks."""
    trace = {"ordre": [], "commandes": []}

    def _spawn(commande):
        trace["ordre"].append("spawn")
        trace["commandes"].append(list(commande))

    def _quit():
        trace["ordre"].append("quit")

    server_control.set_hooks(spawn=_spawn, quit=_quit)
    yield trace
    server_control.reset_hooks()


def test_la_commande_de_relance_reprend_l_executable_courant(journal):
    plan = server_control.plan_restart(port=5056)

    assert plan["pid"] == os.getpid()
    assert plan["port"] == 5056
    commande = plan["commande"]
    assert commande[0] == sys.executable
    assert "-m" in commande
    assert "bouzecode.web_v2" in commande
    assert "--port" in commande
    assert "5056" in commande


def test_le_restart_relance_avant_de_quitter(journal):
    server_control.plan_restart(port=5056)

    #  L'ordre n'est pas cosmétique : quitter d'abord laisserait le port occupé par un
    #  process mourant et le relanceur échouerait.
    assert journal["ordre"] == ["spawn", "quit"]


def test_l_arret_ne_relance_rien(journal):
    plan = server_control.plan_shutdown()

    assert plan["pid"] == os.getpid()
    assert journal["ordre"] == ["quit"]
    assert journal["commandes"] == []


def test_la_route_restart_repond_avant_de_mourir(client, journal):
    reponse = client.post("/api/server/restart")

    #  202 et non 200 : la demande est ACCEPTÉE, l'effet arrive après la réponse.
    assert reponse.status_code == 202
    corps = reponse.get_json()
    assert corps["restarting"] is True
    assert corps["pid"] == os.getpid()
    assert corps["commande"]
    assert journal["ordre"] == ["spawn", "quit"]


def test_la_route_restart_accepte_un_port_explicite(client, journal):
    reponse = client.post("/api/server/restart", json={"port": 5099})

    assert reponse.status_code == 202
    assert reponse.get_json()["port"] == 5099
    assert "5099" in journal["commandes"][0]


def test_le_bandeau_de_derive_porte_un_bouton_redemarrer(client):
    """Le redemarrage doit etre CLIQUABLE, pas seulement appelable en curl."""
    page = client.get("/bureau")

    assert page.status_code == 200
    html = page.get_data(as_text=True)
    #  Le bouton vit dans le bandeau de derive (base.html) : c'est la que l'utilisateur
    #  apprend que le code du boot a devie, donc la qu'il doit pouvoir relancer.
    assert 'id="server-restart"' in html
    assert "Redémarrer" in html
    #  Et il doit viser la vraie route, pas bouzeui.ps1.
    assert "/api/server/restart" in html
    assert "bouzeui.ps1 pour voir les changements" not in html


def test_la_route_shutdown_arrete_sans_relancer(client, journal):
    reponse = client.post("/api/server/shutdown")

    assert reponse.status_code == 202
    corps = reponse.get_json()
    assert corps["stopping"] is True
    assert corps["pid"] == os.getpid()
    assert journal["ordre"] == ["quit"]
    assert journal["commandes"] == []
