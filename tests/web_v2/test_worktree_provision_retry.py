# [desc] Le provisionnement d'un worktree est RÉCUPÉRABLE : reprise bornée, tracée, et un
# dépassement de délai ne traverse plus le dispatch en exception. [/desc]
"""Mesuré sur ce poste le 2026-07-28 : `git worktree add` coûte 50 s à vide (1209 fichiers,
antivirus d'entreprise), pour un délai de garde de 120 s — 2,4× de marge seulement. Quand il
est dépassé, `subprocess.run` lève `TimeoutExpired` : l'exception remontait jusqu'au dispatch
et le ticket restait mort-né. Ces tests travaillent sur un dépôt git JETABLE, jamais sur un
dépôt du parc."""
import subprocess
from pathlib import Path

import pytest

from bouzecode.web_v2.services.work import worktrees


@pytest.fixture()
def depot_jetable(tmp_path, monkeypatch):
    """Un vrai petit dépôt git, créé pour ce test seul, avec ses worktrees sous tmp."""
    repo = tmp_path / "depot"
    repo.mkdir()
    (repo / "fichier.txt").write_text("bonjour", encoding="utf-8")
    for args in (["init", "-b", "principale"], ["add", "fichier.txt"],
                 ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "base"]):
        subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True)
    monkeypatch.setattr(worktrees, "WORKTREES_DIR", tmp_path / "worktrees")
    return str(repo)


def _compter_les_ajouts(monkeypatch) -> list[str]:
    """Espionne `git worktree add` en déléguant à la vraie implémentation."""
    essais: list[str] = []
    vrai_run = worktrees._run

    def espion(cwd, *args, **kwargs):
        if args[:2] == ("worktree", "add"):
            essais.append(" ".join(args))
        return vrai_run(cwd, *args, **kwargs)

    monkeypatch.setattr(worktrees, "_run", espion)
    return essais


def test_un_provisionnement_qui_marche_ne_reessaie_pas(depot_jetable, monkeypatch):
    """Cas nominal : un seul appel à git, un worktree utilisable."""
    essais = _compter_les_ajouts(monkeypatch)

    meta = worktrees.provision(depot_jetable, "tk-ok", base_branch="principale",
                               with_venv=False)

    assert meta["ok"] is True
    assert len(essais) == 1, "le cas nominal ne doit déclencher aucune reprise"
    assert (Path(meta["worktree"]) / "fichier.txt").is_file()


def test_un_echec_transitoire_est_rattrape_par_la_reprise(depot_jetable, monkeypatch):
    """Le premier `worktree add` échoue, le second réussit : le ticket est provisionné
    pour de bon au lieu de rester mort-né."""
    vrai_run = worktrees._run
    essais: list[str] = []

    def premier_essai_rate(cwd, *args, **kwargs):
        if args[:2] == ("worktree", "add"):
            essais.append(" ".join(args))
            if len(essais) == 1:
                raise subprocess.TimeoutExpired(cmd="git worktree add", timeout=120)
        return vrai_run(cwd, *args, **kwargs)

    monkeypatch.setattr(worktrees, "_run", premier_essai_rate)

    meta = worktrees.provision(depot_jetable, "tk-retry", base_branch="principale",
                               with_venv=False)

    assert meta["ok"] is True, "la reprise n'a pas rattrapé un échec pourtant transitoire"
    assert len(essais) == 2
    assert (Path(meta["worktree"]) / "fichier.txt").is_file()


def _toujours_trop_lent(monkeypatch) -> list[str]:
    """Chaque `git worktree add` dépasse le délai de garde ; le reste de git répond vrai."""
    essais: list[str] = []
    vrai_run = worktrees._run

    def espion(cwd, *args, **kwargs):
        if args[:2] == ("worktree", "add"):
            essais.append(" ".join(args))
            raise subprocess.TimeoutExpired(cmd="git worktree add", timeout=120)
        return vrai_run(cwd, *args, **kwargs)

    monkeypatch.setattr(worktrees, "_run", espion)
    return essais


def test_un_depassement_de_delai_ne_traverse_plus_le_dispatch(depot_jetable, monkeypatch):
    """LE bug : `TimeoutExpired` sortait de `provision`, traversait le dispatch, et le ticket
    restait sans run. Une panne PERSISTANTE ne boucle pas non plus : essais bornés et tracés."""
    essais = _toujours_trop_lent(monkeypatch)

    meta = worktrees.provision(depot_jetable, "tk-lent", base_branch="principale",
                               with_venv=False)

    assert meta["ok"] is False, "un dépassement de délai doit devenir un échec, pas une exception"
    assert len(essais) == worktrees._PROVISION_ATTEMPTS, "le nombre d'essais n'est pas borné"
    assert meta["error"].count("essai ") == worktrees._PROVISION_ATTEMPTS, \
        "chaque essai doit laisser sa trace dans le motif final"
    assert "essai 3/3" in meta["error"]
    assert "120 s" in meta["error"], "le motif doit dire que le délai a été dépassé"


def test_un_echec_deterministe_nest_pas_rejoue(depot_jetable, monkeypatch):
    """Une base inconnue rendra le même verdict à chaque essai : le rejouer ne serait que du
    temps perdu, et la purge d'entre-deux réclamerait un état qu'on ne nous demande pas de
    détruire (c'est le rôle de `discard_stale` / `reisolate`)."""
    essais = _compter_les_ajouts(monkeypatch)

    meta = worktrees.provision(depot_jetable, "tk-ko", base_branch="branche-inexistante",
                               with_venv=False)

    assert meta["ok"] is False
    assert len(essais) == 1
    assert "invalid reference" in meta["error"]


def test_la_reprise_nettoie_avant_de_rejouer(depot_jetable, monkeypatch):
    """Un `worktree add` tué en route laisse dossier, entrée git et branche derrière lui :
    sans purge, l'essai suivant échouerait sur « already exists »."""
    purges: list[str] = []
    vraie_purge = worktrees.discard_stale

    def purge_espionnee(repo, tid, base_branch=""):
        purges.append(tid)
        return vraie_purge(repo, tid, base_branch)

    monkeypatch.setattr(worktrees, "discard_stale", purge_espionnee)
    _toujours_trop_lent(monkeypatch)

    worktrees.provision(depot_jetable, "tk-sale", base_branch="principale", with_venv=False)

    assert purges == ["tk-sale", "tk-sale"], "une purge doit précéder CHAQUE nouvel essai"
