"""lancer_sur_rundeck (mode agent) contre un faux Rundeck et un faux file share."""
import base64
import json
import subprocess
import uuid
from pathlib import Path

import pytest

from bouzecode.remote import lancer_sur_rundeck

JETON_LLM = f"jeton-{uuid.uuid4().hex}"  # genere : ce fichier voyage lui-meme dans le diff du paquet


def creer_depot(racine: Path) -> Path:
    racine.mkdir(parents=True)
    for commande in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.invalid"],
                     ["config", "user.name", "T"]):
        subprocess.run(["git", *commande], cwd=racine, check=True, capture_output=True)
    (racine / "a.py").write_bytes(b"x = 1\n")
    subprocess.run(["git", "add", "a.py"], cwd=racine, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=racine, check=True, capture_output=True)
    return racine


@pytest.fixture
def environnement_distant(monkeypatch, faux_rundeck, faux_share):
    variables = {"BOUZECODE_RUNDECK_URL": faux_rundeck, "RUNDECK_PRIVATE_TOKEN_REC": "jeton-test",
                 "AZURE_FILESHARE_URL": faux_share, "AZURE_FILESHARE_NAME": "share",
                 "AZURE_PRIVATE_TOKEN_REC": base64.b64encode(b"cle").decode(), "TRUSTED_HOST": "artefact.invalid",
                 "OPENAI_API_KEY_PP": JETON_LLM, "PREPROD_ENDPOINT": "https://preprod.gateway.invalid"}
    for nom, valeur in variables.items():
        monkeypatch.setenv(nom, valeur)


def lancer_agent(tmp_path: Path, modele: str = "claude-opus-5-5") -> dict:
    depot = creer_depot(tmp_path / "jouet")
    ticket = {"id": "t1234567", "prompt": "ajoute add(a, b)"}
    return lancer_sur_rundeck(ticket, {"cible": "rundeck", "mode": "agent", "projets": ["jouet"],
                                       "chemins": {"jouet": str(depot)}, "modele": modele})


def test_agent_transmet_le_jeton_en_option_jamais_dans_le_paquet(tmp_path, environnement_distant,
                                                                  etat_faux_rundeck, etat_faux_share):
    resultat = lancer_agent(tmp_path)

    assert resultat["ok"] is True, resultat
    # claude-opus-5-5 est servi par le gateway PREPROD : ce sont SES variables qui partent.
    assert etat_faux_rundeck.options_recues["LLM_OPENAI_API_KEY_PP"] == JETON_LLM
    assert etat_faux_rundeck.options_recues["LLM_PREPROD_ENDPOINT"] == "https://preprod.gateway.invalid"
    assert "-m claude-opus-5-5" in etat_faux_share_manifeste(etat_faux_share)["commande"]
    outils = {p["slug"]: p["outil"] for p in etat_faux_share_manifeste(etat_faux_share)["projets"]}
    assert outils == {"jouet": False, "bouzecode": True}
    assert all(JETON_LLM not in y for y in etat_faux_rundeck.yaml_importes)
    assert all(JETON_LLM.encode() not in bytes(c) for c in etat_faux_share.fichiers.values())
    deposes = {Path(c).name for c in etat_faux_share.fichiers}
    assert {"jouet.bundle", "bouzecode.bundle", "manifeste.json", "consigne.txt"} <= deposes


def test_lancement_refuse_ne_laisse_ni_job_ni_paquet(tmp_path, environnement_distant,
                                                     etat_faux_rundeck, etat_faux_share):
    etat_faux_rundeck.echouer_lancement = True

    resultat = lancer_agent(tmp_path)

    assert resultat["ok"] is False and resultat["code"] == "acces_rundeck_manquant"
    assert "HTTP 500" in resultat["message"]
    assert etat_faux_rundeck.jobs == {}
    assert etat_faux_share.fichiers == {}


def etat_faux_share_manifeste(etat_faux_share) -> dict:
    chemin, = [c for c in etat_faux_share.fichiers if c.endswith("/manifeste.json")]
    return json.loads(bytes(etat_faux_share.fichiers[chemin]))


def test_cle_du_fournisseur_absente_est_un_refus_explicite(tmp_path, environnement_distant, monkeypatch,
                                                         etat_faux_rundeck, etat_faux_share):
    monkeypatch.delenv("OPENAI_API_KEY_PP")

    resultat = lancer_agent(tmp_path)

    assert resultat == {"ok": False, "code": "jeton_llm_manquant",
                        "message": "modele claude-opus-5-5 : variables absentes ['OPENAI_API_KEY_PP']"}
    assert etat_faux_rundeck.appels == [] and etat_faux_share.fichiers == {}
