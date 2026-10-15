"""L'utilisateur enrichit le system prompt de SON assistant depuis le Bureau.

Demande du 2026-09-21 : « je voudrais pouvoir enrichir le system prompt de mon assistant
pour lui signaler des elements de contexte qu'il ne possede pas, pour mon usage perso, donc
par user, pas dans le code ».

Le test qui compte est le dernier : ce qu'on ecrit depuis l'UI doit ressortir dans la prose
que l'agent recoit reellement (`get_agent_profile_extra("bureau-assistant")`). Sinon l'UI
ecrirait dans un fichier que personne ne lit.

Aucun mock : vrai client Flask, vrais fichiers, vraie composition de prompt.
"""
import pytest

from bouzecode.backend.core import config, context, profile_extra
from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services.work import bureau_contexte

URL = "/api/bureau/assistant/contexte"


@pytest.fixture()
def maison(tmp_path, monkeypatch):
    """Un ~/.bouzecode jetable + un cwd de projet vide, pour ne pas polluer le vrai poste."""
    config_dir = tmp_path / "config"
    (config_dir / "profiles").mkdir(parents=True)
    projet = tmp_path / "projet"
    projet.mkdir()
    monkeypatch.setattr(config, "CONFIG_DIR", config_dir)
    monkeypatch.chdir(projet)
    profile_extra._DEFAULT_PROFILE_EXTRA_CACHE.clear()
    return config_dir


@pytest.fixture()
def client(maison):
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_sans_contexte_l_ui_recoit_une_zone_vide(client, maison):
    """Premiere visite : pas de fichier, mais l'endpoint repond et dit OU il ecrira."""
    reponse = client.get(URL)
    assert reponse.status_code == 200
    data = reponse.get_json()
    assert data["contenu"] == ""
    assert data["chemin"].endswith("bureau-assistant.local.md")
    assert data["profil"] == "bureau-assistant"


def test_ce_qu_on_enregistre_se_relit(client, maison):
    texte = "Mon equipe s'appelle Demo. Les urgences passent par Teams."
    ecriture = client.put(URL, json={"contenu": texte})
    assert ecriture.status_code == 200, ecriture.get_data(as_text=True)
    assert ecriture.get_json()["ok"] is True

    fichier = maison / "profiles" / "bureau-assistant.local.md"
    assert fichier.exists(), "le contexte doit vivre a cote du profil, dans la config user"
    assert texte in fichier.read_text(encoding="utf-8")

    relecture = client.get(URL).get_json()
    assert texte in relecture["contenu"]


def test_le_contexte_enregistre_arrive_dans_le_prompt_de_l_assistant(client, maison):
    """LE test de la demande : l'UI et l'agent visent le MEME fichier.

    On ecrit par l'endpoint (ce que fait le navigateur), puis on demande la prose composee
    telle que le subprocess de l'agent la recevra. Le texte doit y etre, et en DERNIER.
    """
    texte = "Contexte perso : je suis en charge du lot DEMODB."
    assert client.put(URL, json={"contenu": texte}).status_code == 200

    profile_extra._DEFAULT_PROFILE_EXTRA_CACHE.clear()
    prose = context.get_agent_profile_extra("bureau-assistant")
    assert texte in prose, (
        "le contexte perso enregistre depuis le Bureau doit arriver dans le prompt de "
        "l'assistant ; prose vue : " + prose[-400:]
    )
    #  Il est lu APRES le role : le specialise, puis le perso, donc le perso en dernier.
    assert prose.rindex(texte) > 0


def test_un_contenu_vide_efface_le_contexte(client, maison):
    assert client.put(URL, json={"contenu": "quelque chose"}).status_code == 200
    assert client.put(URL, json={"contenu": ""}).status_code == 200
    assert bureau_contexte.lire_contexte() == ""

    profile_extra._DEFAULT_PROFILE_EXTRA_CACHE.clear()
    prose = context.get_agent_profile_extra("bureau-assistant")
    assert "Contexte local" not in prose, (
        "un contexte vide ne doit laisser AUCUN en-tete parasite dans le prompt"
    )


def test_un_contenu_non_textuel_est_refuse(client, maison):
    reponse = client.put(URL, json={"contenu": {"pas": "du texte"}})
    assert reponse.status_code == 400
