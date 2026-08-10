# [desc] La phase d'un agent change dans la sidebar au moment où le serveur la connaît, pas au TTL. [/desc]
"""Le badge de la sidebar disait, avec 6,5 s de retard, ce que le serveur savait déjà.

MESURÉ le 2026-08-04 sur un vrai lancement, serveur réel : `store.demarrage_phase` rendait
« attente_modele » à t+7,94 s ; `/api/agents/tree` — la source du badge — ne l'a servi qu'à
t+14,50 s, et l'état `idle` qui a suivi n'a JAMAIS été affiché. La page d'arbre est mémorisée
10 s par `fleet_cache`, et la phase voyageait dedans.

L'arbre reste mémorisé (il est dominé par des subprocess git, des prompts et des agents
terminés). Seuls les champs qu'un agent change plusieurs fois par tour sont relus par-dessus,
à chaque lecture, pour les seuls agents vivants — cf. `fleet_live`.

Aucun mock : un vrai process d'agent (un dormeur, pour ne pas rejouer un agent complet), de
vrais fichiers de session, et les vraies fonctions de lecture de l'arbre.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2.services.work import fleet, fleet_cache
from bouzecode.web_v2.tests.production_isolation import autoriser_la_destruction

PAGE = {"offset": 0, "limit": 12}


@pytest.fixture()
def agent_qui_demarre(monkeypatch, tmp_path):
    """Un agent dont le process VIT et dont la session n'est pas encore écrite.

    C'est l'état exact d'un lancement pendant ses premières secondes : `store.agent_status`
    le dit « starting », donc en phase « demarrage ». Le process cible est fabriqué par le
    test lui-même, dans un parc isolé : la levée du garde-fou de destruction ne peut atteindre
    aucun agent réel."""
    fleet_cache.clear()
    autoriser_la_destruction(monkeypatch)
    dormeur = [sys.executable, "-c", "import time; time.sleep(60)"]
    monkeypatch.setattr(runner, "_bouzecode_launch_cmd", lambda: dormeur)
    monkeypatch.setattr(runner, "check_provider_env", lambda *_, **__: None)
    agent = runner.create_agent("réponds PONG", "opus", str(tmp_path))
    yield agent
    runner.kill_agent(agent)
    fleet_cache.clear()


def _phase_dans_la_sidebar(agent_id: str) -> str:
    """La phase telle que la sidebar la lit : par l'arbre, sans rien vider entre deux appels."""
    noeud = next(n for n in fleet.agent_tree(**PAGE)["nodes"] if n["agent_id"] == agent_id)
    return noeud["phase"]


def _ecrire_session(agent, avec_reponse_partielle: str = "") -> None:
    """Écrit la session de l'agent — et, si demandé, le début de réponse du modèle.

    Ces deux fichiers SONT les preuves que `demarrage_phase` lit : la session existe dès que
    le tour est ouvert, la réponse partielle dès que le premier token arrive."""
    session = Path(agent.session_path)
    session.write_text(json.dumps({"messages": []}), encoding="utf-8")
    partielle = session.with_suffix(session.suffix + ".partial.json")
    if avec_reponse_partielle:
        partielle.write_text(json.dumps({"text": avec_reponse_partielle}), encoding="utf-8")
    elif partielle.is_file():
        partielle.unlink()


def test_la_sidebar_suit_les_phases_sans_attendre_le_ttl(agent_qui_demarre):
    """Chaque phase apparaît dans l'arbre au coup d'après, pas dix secondes plus tard."""
    agent = agent_qui_demarre
    assert _phase_dans_la_sidebar(agent.agent_id) == "demarrage"

    # Le tour s'ouvre : la session existe, aucun token n'est encore revenu du modèle.
    _ecrire_session(agent)
    assert _phase_dans_la_sidebar(agent.agent_id) == "attente_modele", (
        "la sidebar sert encore la phase mémorisée : elle attend l'expiration du cache"
    )

    # Le modèle répond : il n'y a plus d'attente à expliquer, la phase s'efface.
    _ecrire_session(agent, avec_reponse_partielle="Bonjour")
    assert _phase_dans_la_sidebar(agent.agent_id) == "", (
        "« le modèle lit votre demande… » reste affiché alors que le modèle a répondu"
    )


def test_un_agent_qui_n_est_plus_vivant_perd_sa_phase(agent_qui_demarre):
    """Une phase qui ment est pire qu'une phase en retard : un agent mort n'en porte plus.

    Sans cette règle, le badge « démarrage de l'agent… » survivrait à l'agent jusqu'à
    l'expiration du cache."""
    agent = agent_qui_demarre
    assert _phase_dans_la_sidebar(agent.agent_id) == "demarrage"

    runner.kill_agent(agent)
    limite = time.time() + 10
    while time.time() < limite and runner.is_running(agent):
        time.sleep(0.05)

    assert _phase_dans_la_sidebar(agent.agent_id) == ""
