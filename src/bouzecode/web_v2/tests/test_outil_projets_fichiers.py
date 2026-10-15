# [desc] Outil `Projets` de l'assistant sur un VRAI depot git temporaire : etat git, commits non pousses, fichiers non suivis tries (pertinents, exclus, secrets). [/desc]
from __future__ import annotations

import json
import subprocess

import pytest

from bouzecode.backend.tools.bureau_projets import projets
from bouzecode.web_v2.services.work import projects


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture()
def depot(tmp_path):
    """Un depot pousse une fois vers un amont nu, puis un commit local de plus, puis des
    fichiers non suivis de toutes les sortes."""
    amont = tmp_path / "amont.git"
    _git(tmp_path, "init", "--bare", "-q", str(amont))
    racine = tmp_path / "scraper"
    racine.mkdir()
    _git(racine, "init", "-q", "-b", "main")
    _git(racine, "config", "user.email", "t@t")
    _git(racine, "config", "user.name", "t")
    (racine / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    (racine / "app.py").write_text("print(1)\n", encoding="utf-8")
    _git(racine, "add", ".gitignore", "app.py")
    _git(racine, "commit", "-q", "-m", "init")
    _git(racine, "remote", "add", "origin", str(amont))
    _git(racine, "push", "-q", "-u", "origin", "main")
    (racine / "app.py").write_text("print(2)\n", encoding="utf-8")
    _git(racine, "commit", "-q", "-am", "local seulement")
    (racine / "app.py").write_text("print(3)\n", encoding="utf-8")
    (racine / "notes_scraper.md").write_bytes(b"plan du scraper\n")
    (racine / "autre.txt").write_text("rien a voir\n", encoding="utf-8")
    (racine / ".env").write_text("TOKEN=abc\n", encoding="utf-8")
    (racine / "temp_essai_scraper.py").write_text("x = 1\n", encoding="utf-8")
    (racine / "capture_scraper.bin").write_bytes(b"\x00\x01\x02")
    (racine / "gros_scraper.csv").write_text("a" * 1_100_000, encoding="utf-8")
    (racine / ".venv").mkdir()
    (racine / ".venv" / "pyvenv.cfg").write_text("home=x\n", encoding="utf-8")
    projects.PROJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    projects.PROJECTS_PATH.write_text(json.dumps([{"slug": "scraper", "name": "scraper",
                                                   "path": str(racine),
                                                   "description": "le scraper"}]),
                                      encoding="utf-8")
    return racine


def test_lister_rend_branche_dernier_commit_et_venv(depot):
    rendu = projets("lister")
    (projet,) = rendu["projets"]
    assert projet["slug"] == "scraper" and projet["branche"] == "main"
    assert projet["dernier_commit"]["titre"] == "local seulement"
    assert projet["venv"] is True and projet["description"] == "le scraper"


def test_fichiers_trie_les_non_suivis_et_dit_l_etat_git(depot):
    rendu = projets("fichiers", "scraper", ["Scraper"])

    assert rendu["ok"]
    git = rendu["git"]
    assert git["branche"] == "main" and git["amont"] == "origin/main"
    assert [c.split(" ", 1)[1] for c in git["commits"]] == ["local seulement"]
    assert git["modifications_non_commitees"] == [" M app.py"]
    par_chemin = {f["chemin"]: f for f in rendu["non_suivis"]}
    assert ".venv/pyvenv.cfg" not in par_chemin  # ignore par .gitignore
    assert rendu["proposes"] == ["notes_scraper.md"]
    assert par_chemin["autre.txt"]["pertinent"] is False
    assert par_chemin[".env"]["exclu"] == "secret"
    assert par_chemin["temp_essai_scraper.py"]["exclu"] == "temporaire"
    assert par_chemin["capture_scraper.bin"]["exclu"] == "binaire"
    assert par_chemin["gros_scraper.csv"]["exclu"] == "trop_gros"
    assert rendu["secrets_signales"] == [".env"]
    assert par_chemin["notes_scraper.md"]["taille"] == len(b"plan du scraper\n")


def test_sans_indices_tout_ce_qui_n_est_pas_exclu_est_propose(depot):
    rendu = projets("fichiers", "scraper")
    assert sorted(rendu["proposes"]) == ["autre.txt", "notes_scraper.md"]


def test_projet_inconnu_nomme_les_projets_connus(depot):
    rendu = projets("fichiers", "nexistepas")
    assert rendu["ok"] is False and rendu["connus"] == ["scraper"]
