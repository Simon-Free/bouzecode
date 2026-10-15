# [desc] Le garde du vrai HOME : HOME jetable par processus, et toute écriture dans le vrai HOME est relevée (sondée par sys.audit, sans aucune écriture réelle). [/desc]
"""Garde-fou de `bouzecode.web_v2.tests.pytest_home_etanche`, éprouvé sans toucher au vrai HOME :
`sys.audit` lève l'événement que CPython lèverait pour une vraie écriture, sans l'effectuer."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from bouzecode.web_v2.tests import pytest_home_etanche as garde


def _releve(evenement, *args):
    """Lève l'événement, rend ce que le garde en a retenu et l'oublie (le test ne doit pas échouer)."""
    sys.audit(evenement, *args)
    return [chemin for _t, _e, chemin in garde._vider()]


def test_chaque_test_a_son_home_et_les_constantes_figees_sont_hors_du_vrai_home(_home_du_test):
    """Path.home() est le HOME propre au test ; CONFIG_DIR, figé à l'import, est sur celui du worker."""
    from bouzecode.backend.core.config import CONFIG_DIR

    assert Path.home() == _home_du_test
    assert os.environ["XDG_CACHE_HOME"] == str(_home_du_test / ".cache")
    assert CONFIG_DIR.is_relative_to(garde.FAUX_HOME)
    # Sous Windows le dossier temporaire est DANS le profil (AppData\Local\Temp) : l'invariant
    # n'est pas « hors du préfixe du vrai HOME » mais « hors de ses zones surveillées ».
    for home in (_home_du_test, garde.FAUX_HOME):
        assert not garde.surveille(os.path.join(str(home), ".bouzecode", "config.json"))


def test_une_ecriture_sous_le_vrai_bouzecode_est_relevee():
    """Ouvrir en écriture ~/.bouzecode/… (vrai HOME) est relevé avec le chemin exact."""
    cible = os.path.join(garde.VRAI_HOME, ".bouzecode", "web_v2", "x.json")
    assert _releve("open", cible, "w", os.O_WRONLY | os.O_CREAT) == [cible]


def test_une_lecture_du_vrai_home_n_est_pas_relevee():
    """Lire n'est pas écrire : pas de faux positif."""
    cible = os.path.join(garde.VRAI_HOME, ".bouzecode", "x.json")
    assert _releve("open", cible, "r", os.O_RDONLY) == []


def test_les_exclusions_et_les_depots_ne_sont_pas_releves():
    """Cache des instantanés du bac et dépôts du HOME : hors champ ; ~/.local/bin : relevé."""
    assert _releve("os.mkdir", os.path.join(garde.VRAI_HOME, ".cache", "bz-sandbox", "a"), 0o777, None) == []
    assert _releve("os.mkdir", os.path.join(garde.VRAI_HOME, "bouzecode-wt-x", ".pytest_cache"), 0o777, None) == []
    rg = os.path.join(garde.VRAI_HOME, ".local", "bin", "rg")
    assert _releve("os.rename", "/tmp/rg", rg, None, None) == [rg]


def test_une_base_sqlite_en_memoire_n_est_pas_une_ecriture(monkeypatch, pytestconfig):
    """`sqlite3.connect(":memory:")` depuis le dépôt ne touche aucun fichier : pas de faux positif."""
    monkeypatch.chdir(pytestconfig.rootpath)
    assert _releve("sqlite3.connect", ":memory:") == []


def test_un_sous_processus_lance_avec_le_vrai_home_est_releve():
    """Rendre le vrai HOME à un enfant est une fuite, même si le test lui-même n'écrit rien."""
    env = {"HOME": garde.VRAI_HOME}
    assert _releve("subprocess.Popen", "git", ["git"], None, env) == [garde.VRAI_HOME]


def test_une_ecriture_dans_le_home_partage_du_worker_est_relevee():
    """Le HOME du worker sert à tous ses tests : y écrire pendant un test est une fuite."""
    cible = str(garde.FAUX_HOME / ".bouzecode" / "web_v2" / "index_cache.json")
    assert _releve("os.rename", cible + ".tmp", cible, None, None) == [cible + ".tmp", cible]


def test_un_depot_range_sous_un_dossier_cache_du_vrai_home_reste_un_depot(monkeypatch):
    """Les worktrees d'agents vivent sous ~/.bouzecode/worktrees : le dépôt testé y est DANS un
    dossier caché du vrai HOME. Son bytecode n'est pas une fuite vers le vrai HOME — le relever
    faisait échouer, sous -n 4, le test qui compilait un module le premier (ordre des workers).
    Une écriture ordinaire dans ce dépôt reste relevée, une seule fois, comme écriture au dépôt."""
    depot = os.path.join(garde.VRAI_HOME, ".bouzecode", "worktrees", "bouzecode", "x")
    monkeypatch.setattr(garde, "_PREFIXE_DEPOT", [depot + os.sep])
    pyc = os.path.join(depot, "src", "__pycache__", "m.cpython-312.pyc")
    assert _releve("os.rename", pyc + ".4242", pyc, None, None) == []
    fichier = os.path.join(depot, "main.py")
    assert _releve("open", fichier, "w", os.O_WRONLY | os.O_CREAT) == [fichier]


def test_le_bytecode_ecrit_par_l_import_n_est_jamais_releve():
    """Python écrit `….pyc.<n>` puis le renomme en `.pyc` sous `__pycache__` : ce n'est pas
    un test qui écrit dans le vrai HOME (460 faux positifs « hors d'un test » le 2026-10-07)."""
    pyc = os.path.join(garde.VRAI_HOME, ".bouzecode", "worktrees", "y", "src", "__pycache__",
                       "m.cpython-312.pyc")
    assert _releve("open", pyc + ".2820565722864", "wb", os.O_WRONLY | os.O_CREAT) == []
    assert _releve("os.rename", pyc + ".29428", pyc, None, None) == []
    voisin = os.path.join(garde.VRAI_HOME, ".bouzecode", "worktrees", "y", "src", "m.py")
    assert _releve("open", voisin, "w", os.O_WRONLY | os.O_CREAT) == [voisin]


def test_une_ecriture_dans_le_depot_est_relevee(pytestconfig):
    """Un chemin relatif au cwd retombe dans le dépôt, partagé par tous les workers : relevé."""
    cible = str(pytestconfig.rootpath / "main.py")
    assert _releve("open", cible, "w", os.O_WRONLY | os.O_CREAT | os.O_TRUNC) == [cible]
    assert _releve("open", str(pytestconfig.rootpath / "src" / "__pycache__" / "x.pyc"), "wb", os.O_WRONLY) == []


def test_un_sous_processus_lance_avec_le_vrai_userprofile_est_releve():
    """Sous Windows, `Path.home()` de l'enfant lit USERPROFILE : un HOME jetable ne suffit pas."""
    env = {"HOME": str(garde.FAUX_HOME), "USERPROFILE": garde.VRAI_HOME}
    assert _releve("subprocess.Popen", "git", ["git"], None, env) == [garde.VRAI_HOME]


def test_le_dossier_de_donnees_du_home_du_worker_est_cree_avant_le_premier_test(tmp_path):
    """Sans lui, le premier test qui crée paresseusement ~/.bouzecode (HOME du worker) faisait
    un os.mkdir relevé comme fuite : seul le premier test du fichier échouait."""
    assert garde.preparer_home_du_worker(tmp_path) == tmp_path / ".bouzecode"
    assert (tmp_path / ".bouzecode").is_dir()
    assert garde.preparer_home_du_worker(tmp_path).is_dir()  # idempotent


def test_creer_le_dossier_de_donnees_du_worker_pendant_un_test_n_est_pas_releve():
    """Après le démarrage de session, le mkdir paresseux de HOME_worker/.bouzecode n'écrit rien."""
    from bouzecode.paths import data_dir

    cible = str(data_dir(garde.FAUX_HOME))
    assert os.path.isdir(cible)
    assert _releve("os.mkdir", cible, 0o777, None) == []
