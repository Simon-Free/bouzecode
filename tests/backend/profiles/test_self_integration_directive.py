"""L'agent codeur s'isole et intègre lui-même : la consigne vit dans le calque `default`.

Ce que ces tests protègent (dans l'ordre des reproches réels) :
  - la consigne existe et le profil de code (`coder`) en hérite ;
  - un profil LECTURE SEULE (`manager`, `inherit_default: false`) ne la reçoit PAS ;
  - elle est SHIPPÉE DANS LA WHEEL, donc lisible depuis n'importe quel dépôt et pas
    seulement depuis bouzecode (qui est le seul à avoir un `.bouzecode/profiles/`) ;
  - elle ne nomme AUCUNE branche en dur : `develop` n'existe pas sur les dépôts qui
    travaillent sur `master`, la base se LIT ;
  - son DÉCLENCHEUR ne dépend d'AUCUN ticket : « dépôt git + tu vas écrire du code »
    suffit. Un agent lancé à la main (sans `BOUZECODE_TICKET_*`) doit suivre le même
    processus qu'un agent lancé depuis un ticket — c'est le geste qui manquait, et son
    absence a produit des merges manuels dans l'arbre partagé.
"""
from pathlib import Path

import pytest

from bouzecode.backend.core import profile_extra
from bouzecode.backend.core.profile_extra import get_agent_profile_extra

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _profil_resolu_depuis_le_depot(monkeypatch):
    """`get_agent_profile_extra` mémorise par (profil, roots) et regarde `Path.cwd()`."""
    profile_extra._DEFAULT_PROFILE_EXTRA_CACHE.clear()
    monkeypatch.chdir(REPO_ROOT)
    yield
    profile_extra._DEFAULT_PROFILE_EXTRA_CACHE.clear()


def test_le_calque_default_porte_la_consigne_d_integration():
    extra = get_agent_profile_extra("default")
    assert "c'est TOI qui intègres ton travail" in extra
    assert "git merge --no-edit <base>" in extra
    assert "Environment(action='integrate')" in extra


def test_le_calque_default_prescrit_de_s_isoler_avant_d_ecrire():
    """Le worktree n'est plus « déjà là » : l'agent le demande LUI-MÊME, avant d'écrire."""
    extra = get_agent_profile_extra("default")
    assert "Environment(action='worktree')" in extra
    assert "DÉJÀ** dans ton worktree" not in extra


def test_le_codeur_herite_de_la_consigne_d_integration():
    extra = get_agent_profile_extra("coder")
    assert "c'est TOI qui intègres ton travail" in extra
    assert "git merge --no-edit <base>" in extra
    assert "Environment(action='worktree')" in extra


def test_le_manager_lecture_seule_n_herite_pas_de_la_consigne():
    extra = get_agent_profile_extra("manager")
    assert "c'est TOI qui intègres ton travail" not in extra
    assert "Environment(action='integrate')" not in extra


def test_la_consigne_vient_de_la_wheel_donc_vaut_pour_tout_depot(monkeypatch, tmp_path):
    """Depuis un dépôt SANS `.bouzecode/profiles/` : la consigne doit rester là.

    C'était le défaut de la première livraison — écrite dans l'override PROJET de
    bouzecode, elle n'existait pour aucun autre dépôt.
    """
    profile_extra._DEFAULT_PROFILE_EXTRA_CACHE.clear()
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / ".bouzecode").exists()
    extra = get_agent_profile_extra("default")
    assert "c'est TOI qui intègres ton travail" in extra


def test_la_consigne_ne_nomme_aucune_branche_en_dur():
    extra = get_agent_profile_extra("default")
    assert "dépôt git" in extra
    assert "git worktree list --porcelain" in extra
    assert "git merge --no-edit develop" not in extra


def test_le_declencheur_ne_depend_d_aucun_ticket():
    """Le processus s'applique dès qu'on est dans un dépôt git, ticket ou pas.

    Tant que la consigne renvoyait vers `POST /api/projects/<slug>/tickets/<id>/integrate` et vers
    `BOUZECODE_TICKET_*`, un agent lancé hors ticket n'avait AUCUN geste applicable : il
    mergeait à la main dans l'arbre partagé. L'outil `Environment` couvre les deux cas,
    donc plus aucune de ces mentions n'a de raison d'être ici.
    """
    extra = get_agent_profile_extra("default")
    assert "BOUZECODE_TICKET" not in extra
    assert "/api/tickets/" not in extra
    assert "n'est PAS un ticket" in extra
