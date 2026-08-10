"""Les avertissements de PÉRIMÈTRE du serveur remontent jusqu'au manager.

Le serveur pose déjà un drapeau et un commentaire sur le ticket fautif (doublon de
périmètre, mandat READ-ONLY confié à une typologie qui écrit). Mais le manager ne lit ni
les tickets ni les commentaires : le seul canal qui l'atteint est le `tool_result` de son
appel `Agent`. Un avertissement qui n'y figure pas n'existe pas pour lui — c'est
exactement le trou qui existait pour le relèvement d'isolation.
"""
from bouzecode.backend.multi_agent import tools

DOUBLON = ("PÉRIMÈTRE EN DOUBLON — ce ticket recouvre le périmètre de : bed63826, a51cefa0. "
           "UN SEUL ticket d'implémentation par livrable.")
READ_ONLY = ("MANDAT READ-ONLY NON TENU — prompt en lecture seule mais typologie accordant "
             "Write, Edit, Bash.")


def _config(monkeypatch, warnings):
    """Le serveur répond un dispatch RÉUSSI porteur d'avertissements de périmètre."""
    def fake_dispatch(body):
        reponse = {"routed": True, "ticket_id": "29e03369", "project_name": "P",
                   "typology": "coder", "project_slug": "p"}
        if warnings:
            reponse["scope_warnings"] = warnings
        return reponse

    monkeypatch.setenv("BOUZECODE_WEB_IPC_DIR", "/agents/mgr123.ipc")
    return {"_web_dispatch": fake_dispatch}


def test_le_doublon_de_perimetre_est_rendu_au_manager(monkeypatch):
    config = _config(monkeypatch, [DOUBLON])

    sortie = tools._spawn_web_ticket_agent({"prompt": "x", "background": True}, config)

    assert "DOUBLON" in sortie
    assert "bed63826" in sortie  # le frère est NOMMÉ : sans son id, rien n'est actionnable


def test_le_mandat_read_only_non_tenu_est_rendu_au_manager(monkeypatch):
    config = _config(monkeypatch, [READ_ONLY])

    sortie = tools._spawn_web_ticket_agent({"prompt": "x", "background": True}, config)

    assert "READ-ONLY" in sortie and "Write" in sortie


def test_les_deux_avertissements_coexistent(monkeypatch):
    config = _config(monkeypatch, [DOUBLON, READ_ONLY])

    sortie = tools._spawn_web_ticket_agent({"prompt": "x", "background": True}, config)

    assert "DOUBLON" in sortie and "READ-ONLY" in sortie


def test_un_dispatch_sain_ne_gagne_aucun_avertissement(monkeypatch):
    """Le cas courant ne doit pas s'alourdir : pas d'anomalie, pas de bruit."""
    config = _config(monkeypatch, [])

    sortie = tools._spawn_web_ticket_agent({"prompt": "x", "background": True}, config)

    assert "⚠️" not in sortie
    assert "29e03369 dispatché" in sortie


def test_lavertissement_ne_transforme_pas_le_dispatch_en_echec(monkeypatch):
    """Le garde-fou SIGNALE, il ne refuse pas : le ticket existe, l'enfant est lancé.
    Un manager qui croirait à un échec redispatcherait — donc un doublon de plus."""
    config = _config(monkeypatch, [DOUBLON])

    sortie = tools._spawn_web_ticket_agent({"prompt": "x", "background": True}, config)

    assert not sortie.startswith("Error:")
    assert config["_bg_agent_launched"] is True
