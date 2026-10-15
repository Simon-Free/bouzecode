# [desc] Les deux trous laissés par les demandes du 2026-09-09 : la fenêtre que l'assistant doit passer à Mails/Teams, et l'historique servi par le serveur.
"""Ce que les tests de page ne pouvaient pas prouver.

`test_bureau_assistant_page.py` vérifie la PAGE : plus de bouton « Démarrer », les ancres
de l'historique sont là, l'assistant possède bien `Mails` et `Teams`. Deux choses restaient
invérifiées, et ce sont précisément celles qui font échouer la demande de l'utilisateur
« regarde mes mails/teams sur les 30 derniers jours » :

1. LA FENÊTRE. `Mails(fenetre)` n'accepte pas une durée libre : c'est un énuméré
   (`2j`, `7j`, `30j`) et son défaut est `7j`. Un assistant qui appelle `Mails()` sans
   argument lit donc SEPT jours puis répond « voilà tes tâches des 30 derniers jours » :
   une réponse fausse que rien ne signale — le pire cas, bien pire qu'une erreur. La seule
   protection possible est une consigne explicite dans le prompt du profil, et c'est ce
   qu'on vérifie ici.
2. L'HISTORIQUE CÔTÉ SERVEUR. La page portait les ancres, mais aucun test n'appelait
   `GET /api/bureau/assistant/conversations`. Le filtre par typologie pouvait donc casser
   (ou tout rendre) sans que rien ne l'attrape.

Aucun mock : le prompt est lu sur le disque, la route est appelée par le client HTTP réel,
et la validation de fenêtre est locale (aucun accès Microsoft Graph n'est déclenché par une
fenêtre invalide).
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

PROFIL = (Path(__file__).resolve().parents[2]
          / "backend" / "profiles" / "builtin" / "bureau-assistant.yaml")

URL_HISTORIQUE = "/api/bureau/assistant/conversations"
TYPOLOGIE = "bureau-assistant"


def _prompt() -> str:
    """Le system_prompt_extra du profil, tel que l'assistant le recevra."""
    charge = yaml.safe_load(PROFIL.read_text(encoding="utf-8"))
    return charge.get("system_prompt_extra") or ""


# --------------------------------------------------------------- (2) la fenêtre

def test_le_prompt_dit_quelle_fenetre_passer_pour_trente_jours():
    """Demande 2026-09-09 (2) : « sur les 30 derniers jours ».

    Le prompt doit contenir la valeur LITTÉRALE `30j` et prévenir que la fenêtre a un
    défaut : sans ça, l'assistant appelle `Mails()` et croit lire un mois.
    """
    prompt = _prompt()
    assert "30j" in prompt, "le prompt doit citer la valeur exacte à passer : 30j"
    assert "7j" in prompt, "le prompt doit nommer le défaut de fenêtre (7j)"
    minuscules = prompt.lower()
    assert "defaut" in minuscules or "défaut" in minuscules or "par default" in minuscules, (
        "le prompt doit DIRE qu'un appel sans fenêtre retombe sur un défaut ; sinon "
        "l'assistant répondra « 30 derniers jours » après n'en avoir lu que sept"
    )


def test_le_defaut_de_fenetre_reste_court():
    """Le défaut n'est PAS 30j : c'est pour ça que la consigne du prompt est nécessaire.

    Si ce test tombe un jour, c'est que le défaut a bougé — il faudra relire la consigne
    du prompt plutôt que de supprimer ce test.
    """
    from bouzecode.backend.tools import bureau_tools

    assert bureau_tools.FENETRE_DEFAUT != "30j"


@pytest.mark.parametrize("mauvaise", ["30d", "30 jours", "30"])
def test_une_fenetre_mal_ecrite_est_nommee_et_jamais_silencieuse(mauvaise):
    """Une fenêtre hors énuméré doit RÉPONDRE, pas lever, et dire les valeurs admises.

    C'est ce qui rend l'erreur récupérable en un tour : l'assistant lit `30j` dans le
    message et recommence. Aucun appel réseau : la fenêtre est validée localement.
    """
    from bouzecode.backend.tools import bureau_tools

    for outil in (bureau_tools.mails, bureau_tools.teams):
        rendu = outil(mauvaise)
        assert rendu["ok"] is False, f"{outil.__name__}({mauvaise!r}) devrait refuser"
        assert rendu["erreur"] == "fenetre_invalide", (
            f"l'erreur doit être NOMMÉE, vu : {rendu!r}"
        )
        assert "30j" in rendu["message"], (
            "le message doit lister les fenêtres admises pour que l'assistant se corrige"
        )


def test_la_fenetre_de_trente_jours_est_acceptee_par_les_deux_outils():
    """`30j` doit être un mot accepté du vocabulaire, indépendamment de tout réseau.

    On ne teste pas le contenu de la boîte (il dépend de l'humain et de son consentement) :
    on teste que la valeur demandée par l'utilisateur n'est jamais refusée COMME FORMAT.
    Un refus d'accès (`authentification`) ou une panne (`transport`) sont des réponses
    légitimes ici ; `fenetre_invalide`, non.
    """
    from bouzecode.backend.tools import bureau_tools
    from bouzecode.web_v2.services.work import ms_activite

    #  FAUX Teams : sans transport injecté, l'outil lançait le vrai `graph_activite.ps1`,
    #  qui, sous le HOME jetable des tests, ouvrait une connexion Microsoft à chaque run.
    faux_graph = ms_activite.ActiviteTransport(
        runner=lambda args: (0, '{"value": []}', ""), cache=False)
    for outil in (bureau_tools.mails, bureau_tools.teams):
        rendu = outil("30j", transport=faux_graph)
        assert rendu.get("erreur") != "fenetre_invalide", (
            f"{outil.__name__} refuse la fenêtre que l'utilisateur demande : {rendu!r}"
        )
        if rendu["ok"]:
            assert rendu["fenetre"] == "30j", "la fenêtre servie doit être celle demandée"
            assert isinstance(rendu["total"], int)


@pytest.fixture()
def client():
    """Le vrai client HTTP de l'app : l'historique se teste par sa route, pas par sa fonction.

    Fixture LOCALE : `web_v2/tests` n'a pas de conftest qui la fournisse — chaque fichier
    de test HTTP construit son app (constaté en la cherchant : elle est définie à
    l'identique dans test_bureau_assistant_page.py).
    """
    from bouzecode.web_v2.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


# ------------------------------------------------------------- (3) l'historique

def test_l_historique_des_conversations_est_servi_par_le_serveur(client):
    """Demande 2026-09-09 (3), côté serveur : la route existe et ne casse jamais.

    Elle est volontairement tolérante (elle rend une liste vide plutôt qu'un 500), donc
    le contrat à tenir est : 200, une clé `conversations`, une liste.
    """
    reponse = client.get(URL_HISTORIQUE)

    assert reponse.status_code == 200, f"vu {reponse.status_code}"
    charge = reponse.get_json()
    assert isinstance(charge, dict) and "conversations" in charge, repr(charge)
    assert isinstance(charge["conversations"], list)


def _semer_un_agent(agent_id, *, profil, titre, debut, ticket_id=""):
    """Un agent web sur disque, dans le parc ISOLÉ du test (fixture autouse de la conftest)."""
    import json

    from bouzecode.web_v2.runtime.runner import agent_fiche

    parc = agent_fiche.AGENTS_DIR
    session = parc / f"{agent_id}.session.json"
    session.write_text(json.dumps({"messages": [{"role": "user", "content": titre}],
                                   "close_reason": "final_answer"}), encoding="utf-8")
    (parc / f"{agent_id}.json").write_text(json.dumps({
        "agent_id": agent_id, "prompt": titre, "model": "m", "cwd": str(parc),
        "pid": 999_999_999, "started_at": debut, "returncode": 0, "profile": profil,
        "session_path": str(session), "ticket_slug": "demo", "ticket_id": ticket_id,
    }), encoding="utf-8")
    agent_fiche._list_agents_cache.clear()


@pytest.fixture()
def parc_seme():
    """Deux conversations d'assistant (dont la plus récente en second) et un agent de code."""
    _semer_un_agent("a55157a1", profil=TYPOLOGIE, titre="Range mes tâches de la semaine",
                    debut="2026-09-01T09:00:00Z", ticket_id="t-ancienne")
    _semer_un_agent("a55157a2", profil=TYPOLOGIE, titre="Lance la tâche d'export",
                    debut="2026-09-20T09:00:00Z", ticket_id="t-recente")
    _semer_un_agent("c0de0001", profil="coder", titre="Corrige le parseur",
                    debut="2026-09-21T09:00:00Z", ticket_id="t-code")


def test_l_historique_ne_contient_que_des_conversations_d_assistant(client, parc_seme):
    """Le filtre par profil est TOUT ce qui distingue l'historique de la flotte entière :
    les deux conversations d'assistant sont servies, l'agent de code ne l'est pas."""
    conversations = client.get(URL_HISTORIQUE).get_json()["conversations"]

    assert [c["key"] for c in conversations] == ["agent/a55157a2", "agent/a55157a1"]


def test_chaque_conversation_de_l_historique_est_reprenable(client, parc_seme):
    """Le front reprend une conversation par son `key` et continue d'y écrire par son
    `ticket_id` ; la plus récente est en tête du tiroir."""
    conversations = client.get(URL_HISTORIQUE).get_json()["conversations"]

    assert conversations, "l'historique semé n'est pas servi"
    for item in conversations:
        for clef in ("key", "ticket_id", "title", "started_at", "state", "need_input"):
            assert clef in item, f"clé manquante {clef} dans {item!r}"
        assert item["key"], f"conversation sans clé, donc non reprenable : {item!r}"
        assert item["title"], f"conversation sans titre, donc illisible : {item!r}"
    assert conversations[0]["ticket_id"] == "t-recente", "la plus récente doit être en tête"
