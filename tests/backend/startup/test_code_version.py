# [desc] Version de code périmée : lecture de HEAD sans git.exe (dépôt, worktree, packed-refs, CRLF), dérive boot → HEAD, avertissement unique par process. [/desc]
"""Des process TUI/agents gardent leur code des jours (session e3b38f9d : process du 09/09
encore actifs le 21/09) ; l'utilisateur voit des bugs « déjà corrigés ». Le process doit
savoir sur quel commit il a démarré et remarquer, à coût quasi nul, que HEAD a bougé.

La lecture de HEAD se fait EN PYTHON (fichiers de .git) : pas de git.exe à lancer à chaque
prompt, et ça marche sous Windows même quand git n'est pas dans le PATH du process."""
from __future__ import annotations

import subprocess

import pytest

from bouzecode.backend.core import code_version as cv

SHA_A = "a" * 40
SHA_B = "b" * 40


def _depot(tmp_path, head="ref: refs/heads/main\n", refs=None, packed=None):
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_bytes(head.encode())
    for name, sha in (refs or {}).items():
        p = git / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(sha.encode())
    if packed is not None:
        (git / "packed-refs").write_bytes(packed.encode())
    return tmp_path


def test_head_symbolique_et_ref_libre(tmp_path):
    repo = _depot(tmp_path, refs={"refs/heads/main": SHA_A + "\n"})
    assert cv.read_head_sha(str(repo)) == SHA_A


def test_fins_de_ligne_crlf(tmp_path):
    """Dépôt manipulé sous Windows : HEAD et refs peuvent finir en CRLF."""
    repo = _depot(tmp_path, head="ref: refs/heads/main\r\n", refs={"refs/heads/main": SHA_A + "\r\n"})
    assert cv.read_head_sha(str(repo)) == SHA_A


def test_ref_dans_packed_refs(tmp_path):
    packed = f"# pack-refs with: peeled fully-peeled sorted\r\n{SHA_B} refs/heads/main\r\n"
    repo = _depot(tmp_path, packed=packed)
    assert cv.read_head_sha(str(repo)) == SHA_B


def test_head_detache(tmp_path):
    repo = _depot(tmp_path, head=SHA_B + "\n")
    assert cv.read_head_sha(str(repo)) == SHA_B


def test_worktree_git_fichier_et_commondir(tmp_path):
    """Un worktree : `.git` est un FICHIER « gitdir: … » ; ses refs de branche vivent dans
    le dépôt principal (commondir)."""
    principal = _depot(tmp_path / "principal", refs={"refs/heads/dev": SHA_A + "\n"})
    wt_gitdir = principal / ".git" / "worktrees" / "wt"
    wt_gitdir.mkdir(parents=True)
    (wt_gitdir / "HEAD").write_text("ref: refs/heads/dev\n")
    (wt_gitdir / "commondir").write_text("../..\n")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {wt_gitdir}\r\n")
    assert cv.read_head_sha(str(wt)) == SHA_A


def test_depot_absent_ou_illisible_rend_vide(tmp_path):
    assert cv.read_head_sha(str(tmp_path)) == ""
    assert cv.read_head_sha("") == ""


def test_derive_avertie_une_seule_fois_par_process(tmp_path):
    """develop avance plusieurs fois par jour : on prévient à la première dérive, puis plus
    jamais, même si HEAD rebouge — mais `state()` continue de suivre le HEAD réel."""
    repo = _depot(tmp_path, refs={"refs/heads/main": SHA_A + "\n"})
    sonde = cv.CodeVersion(str(repo))
    assert sonde.boot_sha == SHA_A
    assert sonde.drift_warning() is None
    (repo / ".git" / "refs" / "heads" / "main").write_text(SHA_B + "\n")
    message = sonde.drift_warning()
    assert message and SHA_A[:8] in message and SHA_B[:8] in message
    assert sonde.drift_warning() is None, "pas de répétition tant que HEAD ne rebouge pas"
    (repo / ".git" / "refs" / "heads" / "main").write_text("c" * 40 + "\n")
    assert sonde.drift_warning() is None, "un second changement de HEAD reste silencieux"
    assert sonde.state() == {"boot_sha": SHA_A, "current_head_sha": "c" * 40, "drift": True}


def test_pas_d_avertissement_sans_sha_de_boot(tmp_path):
    sonde = cv.CodeVersion(str(tmp_path))  # pas un dépôt : rien à comparer
    assert sonde.boot_sha == ""
    assert sonde.drift_warning() is None


def test_sha_de_boot_du_process_courant_est_celui_du_depot():
    """Le module capture le HEAD du dépôt bouzecode au chargement."""
    attendu = subprocess.run(["git", "-C", cv.REPO_ROOT, "rev-parse", "HEAD"],
                             capture_output=True, text=True).stdout.strip()
    if not attendu:
        pytest.skip("pas de dépôt git autour du paquet")
    assert cv.BOOT.boot_sha == attendu


def test_le_tui_affiche_l_avertissement_avant_le_prompt(tmp_path, capsys):
    from bouzecode.ui.repl import _print_code_drift_notice
    repo = _depot(tmp_path, refs={"refs/heads/main": SHA_A + "\n"})
    sonde = cv.CodeVersion(str(repo))
    _print_code_drift_notice(sonde)
    assert capsys.readouterr().out == ""
    (repo / ".git" / "refs" / "heads" / "main").write_text(SHA_B + "\n")
    _print_code_drift_notice(sonde)
    sortie = capsys.readouterr().out
    assert "ANCIEN code" in sortie and SHA_B[:8] in sortie
    _print_code_drift_notice(sonde)
    assert capsys.readouterr().out == ""
    (repo / ".git" / "refs" / "heads" / "main").write_text("c" * 40 + "\n")
    _print_code_drift_notice(sonde)
    assert capsys.readouterr().out == "", "HEAD rebouge : le fil de main reste silencieux"


def test_la_boucle_du_tui_verifie_la_derive_a_chaque_prompt():
    """Garde-fou de câblage : l'appel doit rester dans la boucle de saisie du REPL."""
    import inspect
    from bouzecode.ui import repl
    source = inspect.getsource(repl.repl)
    boucle = source[source.index("while True:\n        _print_code_drift_notice()"):]
    assert "_read_input(prompt)" in boucle
