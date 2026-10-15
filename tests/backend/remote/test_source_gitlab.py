"""Source GitLab : bundle incremental minimal, clone en cache puis fetch, worktree au SHA local exact
(commits non pousses + diff + non suivis presents), nettoyage du cache ; repli bundle complet."""
import subprocess
import sys
from pathlib import Path

import pytest

from bouzecode.remote.paquet import source_git
from bouzecode.remote.paquet.paquet_transfert import construire_paquet
from bouzecode.remote.vm.vm_runner import executer_paquet


def git(depot: Path, *arguments: str) -> str:
    return subprocess.run(["git", *arguments], cwd=depot, check=True, capture_output=True, text=True).stdout.strip()


def commit(depot: Path, chemin: str, contenu: str, message: str) -> str:
    (depot / chemin).write_bytes(contenu.encode())
    git(depot, "add", chemin)
    git(depot, "-c", "user.email=t@example.invalid", "-c", "user.name=T", "commit", "-q", "-m", message)
    return git(depot, "rev-parse", "HEAD")


@pytest.fixture
def depots(tmp_path, monkeypatch):
    """« GitLab » = depot nu local ; le poste a un commit NON POUSSE, un diff et un non suivi."""
    monkeypatch.setenv("BZ_CACHE_DEPOTS", str(tmp_path / "cache_vm"))
    gitlab = tmp_path / "gitlab" / "jouet.git"
    gitlab.mkdir(parents=True)
    git(gitlab, "init", "-q", "--bare", "-b", "main")
    local = tmp_path / "poste" / "jouet"
    git(tmp_path, "clone", "-q", str(gitlab), str(local))
    git(local, "config", "core.autocrlf", "false")
    pousse = commit(local, "a.txt", "a\n", "pousse")
    git(local, "push", "-q", "origin", "main")
    for numero in range(30):  # historique deja sur GitLab : ne doit PAS voyager
        commit(local, f"h{numero}.txt", "x" * 2000 + str(numero), f"historique {numero}")
    git(local, "push", "-q", "origin", "main")
    base = git(local, "rev-parse", "HEAD")
    non_pousse = commit(local, "local.txt", "commit local\n", "non pousse")
    (local / "a.txt").write_bytes(b"a modifie\n")
    (local / "notes.txt").write_bytes(b"non suivi\n")
    return {"gitlab": gitlab, "local": local, "pousse": pousse, "base": base, "non_pousse": non_pousse,
            "cache": tmp_path / "cache_vm"}


def test_bundle_incremental_ne_porte_que_les_commits_non_pousses(depots, tmp_path):
    source = source_git.analyser(depots["local"])
    complet = tmp_path / "complet.bundle"
    git(depots["local"], "bundle", "create", str(complet), "main")

    ref = source_git.ecrire_bundle(depots["local"], "main", source, tmp_path / "inc.bundle")

    assert source["source"] == "remote" and source["base"] == depots["base"] and source["commits_a_envoyer"] == 1
    assert ref == "refs/heads/main"
    verification = subprocess.run(["git", "bundle", "verify", str(tmp_path / "inc.bundle")], cwd=depots["local"],
                                  capture_output=True, text=True)
    assert depots["base"] in verification.stdout + verification.stderr  # prerequis = la base GitLab
    assert (tmp_path / "inc.bundle").stat().st_size * 10 < complet.stat().st_size


def _script(tmp_path: Path, code: str) -> str:
    (tmp_path / "vm.py").write_text(code, encoding="utf-8")
    return f'"{sys.executable}" "{tmp_path / "vm.py"}"'


VERIFIE_ET_COMMITE = (
    "import pathlib, subprocess\n"
    "assert pathlib.Path('local.txt').read_text() == 'commit local\\n'\n"
    "assert pathlib.Path('a.txt').read_text() == 'a modifie\\n'\n"
    "assert pathlib.Path('notes.txt').read_text() == 'non suivi\\n'\n"
    "print('BRANCHE', subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], capture_output=True, text=True).stdout)\n"
    "pathlib.Path('agent.txt').write_text('par la vm\\n')\n"
    "subprocess.run(['git', 'add', 'agent.txt'], check=True)\n"
    "subprocess.run(['git', 'commit', '-q', '-m', 'vm: agent'], check=True)\n")


def test_vm_clone_puis_fetch_le_cache_et_travaille_dans_un_worktree(depots, tmp_path):
    commande = _script(tmp_path, VERIFIE_ET_COMMITE)
    bilans = []
    for passe in (1, 2):
        construire_paquet(f"bz_{passe}", "agent", commande, {"jouet": depots["local"]}, {"jouet": ["notes.txt"]},
                          tmp_path / f"paquet{passe}", branche_travail="agent/t1")
        bilans.append(executer_paquet(tmp_path / f"paquet{passe}", tmp_path / f"travail{passe}",
                                      tmp_path / f"resultat{passe}"))

    assert [b["code"] for b in bilans] == [0, 0]
    assert [b["sources"]["jouet"] for b in bilans] == ["clone", "fetch"]
    assert "BRANCHE agent/t1" in (tmp_path / "resultat1" / "sortie.log").read_text(encoding="utf-8")
    info = bilans[0]["projets"]["jouet"]
    assert info["sha_depart"] == depots["non_pousse"] and info["bundle"] == "jouet.resultat.bundle"
    cache = depots["cache"] / source_git.analyser(depots["local"])["cache"]
    assert len(git(cache, "worktree", "list").splitlines()) == 1  # worktrees retires
    assert "agent/t1" not in git(cache, "branch", "--list") and not git(cache, "for-each-ref", "refs/bz")
    assert git(cache, "rev-parse", "refs/remotes/origin/main") == depots["base"]


def test_repli_bundle_complet_sans_remote_ou_remote_injoignable(tmp_path):
    seul = tmp_path / "seul"
    seul.mkdir()
    git(seul, "init", "-q", "-b", "main")
    commit(seul, "a.txt", "a\n", "initial")
    assert source_git.analyser(seul) == {"source": "bundle_complet", "raison": "pas de remote origin"}
    git(seul, "remote", "add", "origin", str(tmp_path / "nulle_part.git"))
    analyse = source_git.analyser(seul)
    assert analyse["source"] == "bundle_complet" and "injoignable" in analyse["raison"]


@pytest.mark.parametrize("url, attendu", [
    ("https://user:jeton@gitlab.example/g/p.git", "https://gitlab.example/g/p.git"),
    ("git@gitlab.example:g/p.git", "https://gitlab.example/g/p.git"),
    ("https://gitlab.example/g//p.git", "https://gitlab.example/g//p.git"),
])
def test_url_sans_identifiants(url, attendu):
    assert source_git.url_sans_identifiants(url) == attendu
    assert "jeton" not in source_git.nom_de_cache(source_git.url_sans_identifiants(url))
