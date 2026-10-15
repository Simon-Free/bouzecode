# [desc] Tests du journal des dossiers écartés : trois états, comparaison exacte, levée par AddProject. [/desc]
"""Registre de projets à trois états.

Un dossier est soit désigné projet, soit explicitement écarté, soit inconnu.
Ces tests décrivent le comportement vu de l'utilisateur : « j'ai dit non une
fois, on ne me repose plus la question », et « dire non sur un dossier ne dit
rien de ce qu'il contient ».
"""
import json

import pytest

from bouzecode.web_v2.services.work import dismissed_paths, projects


@pytest.fixture()
def registre(tmp_path, monkeypatch):
    """Isole les deux fichiers du registre dans un dossier temporaire."""
    monkeypatch.setattr(dismissed_paths, "DISMISSED_PATH", tmp_path / "dismissed_paths.json")
    monkeypatch.setattr(projects, "PROJECTS_PATH", tmp_path / "projects.json")
    return tmp_path


def test_un_dossier_jamais_evoque_est_inconnu(registre):
    assert dismissed_paths.is_dismissed(registre) is False
    assert dismissed_paths.list_dismissed() == []


def test_ecarter_un_dossier_le_rend_definitivement_connu(registre):
    conteneur = registre / "demo"
    conteneur.mkdir()

    dismissed_paths.dismiss(conteneur, reason="conteneur de depots")

    assert dismissed_paths.is_dismissed(conteneur) is True
    entree = dismissed_paths.find_dismissal(conteneur)
    assert entree["reason"] == "conteneur de depots"
    assert entree["by"] == "user"
    assert entree["dismissed_at"]


def test_ecarter_un_dossier_ne_dit_rien_de_ses_enfants(registre):
    """La comparaison est exacte, pas par préfixe : sinon écarter `demo/`
    condamnerait tous les projets qu'il contient."""
    conteneur = registre / "demo"
    enfant = conteneur / "demo_application"
    enfant.mkdir(parents=True)

    dismissed_paths.dismiss(conteneur)

    assert dismissed_paths.is_dismissed(conteneur) is True
    assert dismissed_paths.is_dismissed(enfant) is False


def test_ecarter_deux_fois_ne_duplique_pas(registre):
    dossier = registre / "demo"
    dossier.mkdir()

    dismissed_paths.dismiss(dossier, reason="premiere fois")
    dismissed_paths.dismiss(dossier, reason="seconde fois")

    assert len(dismissed_paths.list_dismissed()) == 1
    assert dismissed_paths.find_dismissal(dossier)["reason"] == "premiere fois"


def test_annuler_un_ecart_remet_le_dossier_a_inconnu(registre):
    dossier = registre / "demo"
    dossier.mkdir()
    dismissed_paths.dismiss(dossier)

    assert dismissed_paths.undismiss(dossier) is True
    assert dismissed_paths.is_dismissed(dossier) is False
    assert dismissed_paths.undismiss(dossier) is False


def test_la_comparaison_ignore_la_casse_et_le_separateur(registre):
    """Sous Windows `C:\\X` et `c:/x` sont le même dossier : un écart posé sur
    l'un doit valoir pour l'autre, sinon la question revient."""
    dossier = registre / "Demo"
    dossier.mkdir()
    dismissed_paths.dismiss(dossier)

    variante = str(dossier).replace("\\", "/")
    assert dismissed_paths.is_dismissed(variante) is True


def test_designer_un_dossier_ecarte_comme_projet_leve_l_ecart(registre):
    """Se raviser doit fonctionner : si l'utilisateur enregistre finalement le
    dossier, il ne doit pas rester marqué « pas un projet »."""
    dossier = registre / "demo_ingestion"
    dossier.mkdir()
    dismissed_paths.dismiss(dossier)

    cree = projects.add_project("demo_ingestion", str(dossier))

    assert isinstance(cree, dict)
    assert dismissed_paths.is_dismissed(dossier) is False


def test_le_journal_est_un_fichier_separe_de_projects_json(registre):
    """Les non-projets ne doivent jamais atterrir dans la liste de lancement."""
    dossier = registre / "demo"
    dossier.mkdir()
    dismissed_paths.dismiss(dossier)

    assert projects.list_projects() == []
    contenu = json.loads((registre / "dismissed_paths.json").read_text(encoding="utf-8"))
    assert len(contenu) == 1
