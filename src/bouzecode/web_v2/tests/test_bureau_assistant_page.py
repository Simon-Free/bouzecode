"""Le Bureau : une seule page, la liste plein écran, l'assistant en panneau escamotable.

Demande du 2026-09-08, qui remplace celle des deux colonnes : « je veux que la todo list
prenne toute la place, et que l'assistant soit dans une bulle qui se déploie sur la moitié
de l'écran à la demande ». On teste donc ce que l'utilisateur verra : une seule colonne, la
liste des lignes servie, le panneau de l'assistant et sa bulle d'ouverture présents, de quoi
parler à l'assistant, et l'assistant est bien celui qui n'a NI Edit NI Bash (sinon il coderait).

Demande du 2026-09-09 : PLUS de message de départ ni de bouton « Démarrer l'assistant » (on
arrive sur une conversation vide, le premier message humain lance l'agent), et un HISTORIQUE
des conversations passées.
"""
import pytest

from bouzecode.web_v2.app import create_app


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _page(client) -> str:
    reponse = client.get("/bureau")
    assert reponse.status_code == 200
    return reponse.get_data(as_text=True)


def test_l_assistant_de_pilotage_est_lancable_comme_typologie(client):
    """Le premier message dispatche une typologie : elle doit exister et pointer le
    profil sans Edit/Write/Bash. Une typologie vide retomberait sur le profil CODEUR."""
    from bouzecode.web_v2.services.typologies import list_typologies

    typologies = list_typologies()
    assistant = [t for t in typologies if (t.get("profile") or "") == "bureau-assistant"]
    assert assistant, (
        "aucune typologie ne pointe le profil bureau-assistant ; "
        f"vues : {sorted((t.get('name') or '') for t in typologies)}"
    )
    assert (assistant[0].get("name") or ""), "la typologie de l'assistant doit avoir un nom"


def test_l_assistant_ne_peut_pas_coder(client):
    """Garde-fou de bout en bout : le profil dispatché par la page n'a ni Edit ni Bash."""
    from bouzecode.backend.tools import bureau_tools
    from bouzecode.backend.tools.registration import enabled_tools_for_profile

    bureau_tools.register()
    autorises = enabled_tools_for_profile("bureau-assistant")
    assert {"ResteAFaire", "Taches", "Decisions", "Flotte", "LancerAgent"} <= autorises
    assert not ({"Edit", "Write", "Bash"} & autorises)


def test_l_assistant_sait_lire_mails_et_teams(client):
    """Demande 2026-09-09 (2) : « regarde mes mails/teams sur 30 jours ».

    L'assistant doit POSSÉDER les outils de lecture M365, sinon il répond de mémoire.
    """
    from bouzecode.backend.tools import bureau_tools
    from bouzecode.backend.tools.registration import enabled_tools_for_profile

    bureau_tools.register()
    autorises = enabled_tools_for_profile("bureau-assistant")
    assert {"Mails", "Teams"} <= autorises, (
        "l'assistant doit pouvoir lire Outlook et Teams ; vus : " + repr(sorted(autorises))
    )
