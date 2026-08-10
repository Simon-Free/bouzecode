"""Une conversation dont l'agent n'existe pas ENCORE doit dire ce que le serveur est en train
de faire, dans le canal que le corps de conversation lit déjà (`/blocks`, 1,5 s).

Le défaut : pendant tout le provisionnement il n'y a aucune session à résoudre, donc
`/api/sessions/launching/<id>/blocks` répondait 404 et le front se rabattait sur une phrase
FIGÉE (« Préparation de la conversation… ») qui ne bougeait pas d'une lettre pendant les 20 s
(à froid) à ~55 s que coûte `git worktree add` sur ce poste. La phase était pourtant connue du
serveur à la seconde près : elle n'atteignait que la sidebar, via l'arbre et son cache.

Aucun mock : de vrais tickets dans le store SQLite isolé par la fixture autouse de conftest,
les vraies phases posées par `launch_phase`, et la vraie route Flask.
"""
from __future__ import annotations

import pytest

from bouzecode.web_v2.services.work import launch_phase, tickets

SLUG = "projet-test"


@pytest.fixture()
def client():
    from bouzecode.web_v2.app import create_app

    with create_app().test_client() as c:
        yield c


@pytest.fixture()
def ticket_en_lancement():
    """Un ticket créé et marqué `launching` : exactement l'état d'une conversation qui vient
    d'être envoyée et dont le worktree se creuse en fond."""
    ticket = tickets.create_ticket(SLUG, "Déployer", "Déployer la branche develop")
    tickets.set_launching(SLUG, ticket)
    return ticket


def _status(client, ticket_id):
    resp = client.get(f"/api/sessions/launching/{ticket_id}/blocks")
    assert resp.status_code == 200
    return resp.get_json()


def test_la_creation_du_worktree_est_nommee_dans_le_corps_de_conversation(
        client, ticket_en_lancement):
    """Pendant `git worktree add`, la conversation annonce « création du worktree » et depuis
    quelle branche — au lieu d'une attente muette de près d'une minute."""
    launch_phase.set_phase(SLUG, ticket_en_lancement, launch_phase.PROVISIONING_WORKTREE,
                           detail="depuis develop")

    data = _status(client, ticket_en_lancement["id"])

    assert data["status"]["phase"] == launch_phase.PROVISIONING_WORKTREE
    assert data["status"]["phase_label"] == "création du worktree"
    assert data["status"]["phase_detail"] == "depuis develop"
    assert data["status"]["phase_at"]  # horodatée : « depuis 4 s » vs « depuis 4 min »
    # Rien à streamer, et c'est normal : l'agent n'existe pas encore.
    assert data["blocks"] == [] and data["total"] == 0


def test_l_etat_servi_est_celui_d_un_lancement_pas_une_session_vide(client,
                                                                   ticket_en_lancement):
    """L'état doit être `provisioning` — le même mot que l'arbre — et non le `cli` que rendait
    un `ref.agent` absent, qui faisait conclure au front « aucun contenu »."""
    launch_phase.set_phase(SLUG, ticket_en_lancement, launch_phase.PROVISIONING_WORKTREE)

    assert _status(client, ticket_en_lancement["id"])["status"]["state"] == "provisioning"


def test_un_essai_de_worktree_rate_est_dit_pendant_que_le_suivant_tourne(
        client, ticket_en_lancement):
    """`git worktree add` est rejoué jusqu'à 3 fois : la conversation dit qu'on en est au 2ᵉ
    essai, ce qui distingue un provisionnement lent d'un serveur bloqué."""
    launch_phase.set_phase(
        SLUG, ticket_en_lancement, launch_phase.PROVISIONING_WORKTREE,
        detail=launch_phase.attempt_detail(1, 3, "n'a pas rendu la main en 120 s"))

    detail = _status(client, ticket_en_lancement["id"])["status"]["phase_detail"]

    assert "essai 1/3 échoué" in detail
    assert "nouvelle tentative" in detail


def test_l_installation_de_l_environnement_uv_est_nommee(client, ticket_en_lancement):
    """`uv sync --all-extras` court jusqu'à 600 s : la conversation le dit aussi."""
    launch_phase.set_phase(SLUG, ticket_en_lancement, launch_phase.SYNCING_VENV)

    data = _status(client, ticket_en_lancement["id"])

    assert data["status"]["phase_label"] == "installation de l'environnement uv"


def test_un_ticket_sans_lancement_en_cours_reste_un_404(client):
    """Dès que l'agent est né (ou que le lancement a échoué), il n'y a plus de phase à servir :
    le front bascule alors l'onglet sur `agent/<id>` (remapLaunchingTabs)."""
    ticket = tickets.create_ticket(SLUG, "Déjà lancé", "Un prompt")

    resp = client.get(f"/api/sessions/launching/{ticket['id']}/blocks")

    assert resp.status_code == 404


def test_le_demarrage_de_l_agent_ferme_la_phase_de_preparation(client, ticket_en_lancement):
    """`add_run` retire le drapeau `launching` ET la phase : la conversation ne doit plus
    annoncer « création du worktree » sur un agent qui tourne déjà."""
    launch_phase.set_phase(SLUG, ticket_en_lancement, launch_phase.SPAWNING)
    assert _status(client, ticket_en_lancement["id"])["status"]["phase"] == "spawning"

    tickets.add_run(SLUG, ticket_en_lancement, "abc123", "work", "claude-sonnet")

    resp = client.get(f"/api/sessions/launching/{ticket_en_lancement['id']}/blocks")
    assert resp.status_code == 404
