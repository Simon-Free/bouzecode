# [desc] Une conversation lancée à la main garde son process chaud ; un sous-agent non. [/desc]
"""Le warm-pool existe pour les conversations où quelqu'un reviendra écrire. Il les excluait.

`ui/repl._web_keep_warm` décide de la résidence du process d'après `BOUZECODE_PARENT`, posé par
`runner._ticket_env`. Or une conversation lancée depuis l'UI porte `parent = MANUAL_PARENT`
(sentinelle « lancé à la main »), qui n'est PAS une parenté : le process était donc traité comme
un sous-agent et quittait après CHAQUE tour.

Constat du 2026-08-03 sur le parc réel : 54 conversations utilisateur, 54 process morts, 0 warm.
Conséquence : cold start complet au 1er message ET à chaque follow-up (~1,2 s de boot mesurées
sur la commande de spawn), là où la TUI garde son process entre les tours — très exactement
l'écart rapporté par l'utilisateur.
"""
from __future__ import annotations

import os

import pytest

from bouzecode.ui import repl
from bouzecode.web_v2.runtime.runner import agent_commande, agent_fiche

MANAGER_ID = "6b4a9ce79dc1"


def _agent(parent: str) -> agent_fiche.Agent:
    return agent_fiche.Agent(
        agent_id="a1b2c3d4e5f6",
        prompt="réponds PONG",
        model="opus",
        cwd="/tmp",
        pid=1234,
        started_at="2026-08-03T10:00:00Z",
        parent=parent,
    )


def test_une_conversation_lancee_a_la_main_n_annonce_aucune_parente():
    """La sentinelle « lancé à la main » ne doit pas voyager comme une parenté."""
    assert "BOUZECODE_PARENT" not in agent_commande._ticket_env(_agent(agent_commande.MANUAL_PARENT))


def test_un_sous_agent_annonce_bien_son_manager():
    """La règle d'origine tient : un vrai sous-agent reste identifié comme tel."""
    assert agent_commande._ticket_env(_agent(MANAGER_ID))["BOUZECODE_PARENT"] == MANAGER_ID


def test_un_agent_sans_parent_n_annonce_rien():
    assert "BOUZECODE_PARENT" not in agent_commande._ticket_env(_agent(""))


@pytest.mark.parametrize(
    "parent, doit_rester_chaud",
    [(agent_commande.MANUAL_PARENT, True), ("", True), (MANAGER_ID, False)],
)
def test_le_process_reste_resident_pour_les_conversations_utilisateur(
    parent, doit_rester_chaud, monkeypatch,
):
    """Bout en bout : l'env produit par le serveur décide la résidence côté process agent."""
    env = agent_commande._ticket_env(_agent(parent))
    monkeypatch.delenv("BOUZECODE_PARENT", raising=False)
    if "BOUZECODE_PARENT" in env:
        monkeypatch.setenv("BOUZECODE_PARENT", env["BOUZECODE_PARENT"])

    assert repl._web_keep_warm({"_web_agent_dir": "/tmp/ipc"}) is doit_rester_chaud


def test_hors_web_rien_ne_reste_chaud(monkeypatch):
    """La résidence ne concerne que les agents web : la TUI gère son process elle-même."""
    monkeypatch.delenv("BOUZECODE_PARENT", raising=False)
    assert repl._web_keep_warm({}) is False
    assert os.environ.get("BOUZECODE_PARENT") is None
