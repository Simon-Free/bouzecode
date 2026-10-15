"""Le constat de livraison (`delivery`, lot L5) — vrai git, vrai dépôt temporaire, aucun mock.

Ce constat tourne au tick du watchdog et se mémorise dans le ticket (`delivery`, qui remplace
`unmerged_*`), parce que `GET /api/board` interdit git dans son chemin de lecture.
"""
import subprocess

import pytest

from bouzecode.web_v2.services.work import unmerged
from bouzecode.web_v2.services.work._status import remaining_of
from tests.git_modeles import ecrire_commits
from tests.git_modeles import git as _git


def _construire(repo):
    _git(repo, "init", "-b", "develop")
    _git(repo, "config", "user.email", "t@t.io")
    _git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("1", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")


@pytest.fixture
def repo(tmp_path, depot_modele):
    """`develop` avec un commit de base, extraite."""
    return depot_modele(tmp_path / "repo", _construire)


def _commit_on(repo, branch, n):
    """`branch` repart de `develop` et reçoit `n` commits (f0.txt … f{n-1}.txt), en un seul
    lancement git ; `develop` reste extraite, comme après l'ancien `checkout develop`."""
    ecrire_commits(repo, branch, "develop",
                   [(f"work {i}", {f"f{i}.txt": str(i)}) for i in range(n)])


def _commits(ticket):
    return ticket["delivery"]["commits_ahead"]


def _ticket(repo, branch, tid="abc"):
    return {"id": tid, "state": "delivered",
            "worktree": {"repo_root": str(repo), "base": "develop", "branch": branch,
                         "worktree": str(repo)}}


def test_commits_non_integres_sont_comptes(repo):
    _commit_on(repo, "agent/abc", 2)
    t = _ticket(repo, "agent/abc")

    stats = unmerged.scan([t])

    assert _commits(t) == 2
    assert t["delivery"]["marker"]
    assert stats["with_commits"] == 1
    assert remaining_of(t)["unmerged_commits"] == 2


def test_branche_vide_ne_produit_aucun_acte(repo):
    _git(repo, "branch", "agent/vide", "develop")
    t = _ticket(repo, "agent/vide")

    unmerged.scan([t])

    assert _commits(t) == 0
    assert remaining_of(t) == {"unmerged_commits": 0, "open_points": 0}


def test_branche_absente_compte_zero_sans_exploser(repo):
    t = _ticket(repo, "agent/jamais-creee")

    unmerged.scan([t])

    assert _commits(t) == 0


def test_ticket_sans_worktree_ne_touche_pas_git(tmp_path):
    t = {"id": "sans-branche"}

    stats = unmerged.scan([t])

    assert _commits(t) == 0
    assert stats["scanned"] == 0
    assert stats["skipped"] == 1


def test_ticket_deja_integre_nest_pas_rescanne(repo):
    _commit_on(repo, "agent/fini", 3)
    t = _ticket(repo, "agent/fini")
    t.update(state="closed", state_reason={"code": "integre"})  # clos par un merge (lot L2)

    stats = unmerged.scan([t])

    assert _commits(t) == 0
    assert stats["scanned"] == 0


def test_second_tick_ne_recompte_pas_si_la_comparaison_na_pas_bouge(repo):
    _commit_on(repo, "agent/abc", 2)
    t = _ticket(repo, "agent/abc")

    unmerged.scan([t])
    stats = unmerged.scan([t])

    # "scanned" == 0 prouve la sortie AVANT le rev-list : aucun process git relancé.
    assert stats["scanned"] == 0
    assert stats["skipped"] == 1
    assert _commits(t) == 2


def test_une_base_qui_avance_fait_recompter(repo):
    """Un merge fait avancer la BASE sans toucher la branche agent : le compte doit retomber
    à 0, sinon une livraison déjà intégrée resterait éternellement « à décider »."""
    _commit_on(repo, "agent/abc", 2)
    t = _ticket(repo, "agent/abc")
    unmerged.scan([t])
    assert _commits(t) == 2

    _git(repo, "merge", "--no-ff", "-m", "merge agent/abc", "agent/abc")
    stats = unmerged.scan([t])

    assert _commits(t) == 0
    assert stats["scanned"] == 1


def test_un_commit_de_plus_est_vu_au_tick_suivant(repo):
    _commit_on(repo, "agent/abc", 1)
    t = _ticket(repo, "agent/abc")
    unmerged.scan([t])
    assert _commits(t) == 1

    _commit_on(repo, "agent/abc", 2)
    stats = unmerged.scan([t])

    assert _commits(t) == 2
    assert stats["scanned"] == 1


def _espionner_git(monkeypatch):
    appels = []
    vrai = unmerged._run

    def espion(cwd, *args):
        appels.append(args[0])
        return vrai(cwd, *args)

    monkeypatch.setattr(unmerged, "_run", espion)
    monkeypatch.setattr(unmerged.branch_rescue, "_run", espion)
    return appels


def test_une_passe_lit_les_refs_une_fois_et_ne_recompte_pas_un_couple_connu(repo, monkeypatch):
    """Cinq tickets du même dépôt : UN for-each-ref pour la passe (avant : deux rev-parse par
    ticket) ; des tickets relus sans leur repère (store rechargé) ne relancent aucun rev-list,
    le compte d'un couple (base, tip) étant immuable."""
    for i in range(5):
        _commit_on(repo, f"agent/t{i}", i + 1)
    unmerged._comptes.clear()
    unmerged._codes.clear()
    appels = _espionner_git(monkeypatch)
    tickets = [_ticket(repo, f"agent/t{i}", tid=f"t{i}") for i in range(5)]
    unmerged.scan(tickets)
    assert [_commits(t) for t in tickets] == [1, 2, 3, 4, 5]
    assert appels.count("for-each-ref") == 1 and "rev-parse" not in appels
    assert appels.count("rev-list") == 5 and appels.count("diff") == 5

    appels.clear()
    relus = [_ticket(repo, f"agent/t{i}", tid=f"t{i}") for i in range(5)]
    unmerged.scan(relus)
    assert [_commits(t) for t in relus] == [1, 2, 3, 4, 5]
    assert appels == ["for-each-ref"]


def test_hors_passe_scan_ticket_interroge_git_comme_avant(repo, monkeypatch):
    _commit_on(repo, "agent/abc", 2)
    appels = _espionner_git(monkeypatch)
    t = _ticket(repo, "agent/abc")
    assert unmerged.scan_ticket(t) in ("scanned", "skipped") and _commits(t) == 2
    assert t["delivery"]["code_files_ahead"] == 2
    assert "for-each-ref" not in appels and appels.count("rev-parse") == 2


def test_base_designee_par_remote_ou_sha_resolue_comme_git(repo):
    """La base peut être une remote-tracking ou un SHA : même repère qu'un rev-parse."""
    _commit_on(repo, "agent/abc", 2)
    sha_base = subprocess.run(["git", "-C", str(repo), "rev-parse", "develop"], capture_output=True,
                              text=True).stdout.strip()
    _git(repo, "update-ref", "refs/remotes/origin/develop", sha_base)
    for base in ("origin/develop", sha_base, "develop"):
        t = _ticket(repo, "agent/abc")
        t["worktree"]["base"] = base
        unmerged.scan([t])
        assert _commits(t) == 2
        assert t["delivery"]["marker"].startswith(f"{sha_base}..")


def test_un_residu_de_fichiers_de_meta_n_est_pas_du_travail(repo):
    """Des commits qui ne touchent que uv.lock / SYMBOLS.md : commits en avance, mais AUCUN
    fichier de code — ce n'est pas un acte restant (« résidu »)."""
    ecrire_commits(repo, "agent/meta", "develop", [("méta", {"uv.lock": "x", "SYMBOLS.md": "y"})])
    t = _ticket(repo, "agent/meta")

    unmerged.scan([t])

    assert _commits(t) == 1 and t["delivery"]["code_files_ahead"] == 0
    assert remaining_of(t) == {"unmerged_commits": 0, "open_points": 0}
