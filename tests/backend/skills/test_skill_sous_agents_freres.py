# [desc] Deux sous-agents en process, chacun dans SON worktree du meme depot : chacun ne voit que ses skills (jamais celles du worktree d'un frere), et la copie du checkout principal masquee par celle du worktree n'est pas un avertissement. [/desc]
"""Symptome d'origine : un sous-agent dans `tui-a8fb8fc9` voyait chaque skill trois fois —
la sienne, celle de son frere `tui-90a972a9` et celle du checkout principal — et le terminal
recevait un « masquée par » par skill et par copie.

Cause : LoadProjectConfig enregistrait le `.bouzecode/` charge dans un registre GLOBAL au
process (`core/paths.py`), partage par tous les agents du TUI. Vrai git, vrais worktrees,
vrai outil LoadProjectConfig."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from bouzecode.backend.core import paths
from bouzecode.backend.core.dossier_agent import Atelier, dans
from bouzecode.backend.tools.ops.project_config import _load_project_config
from bouzecode.backend.tools.skill.loader import resolve_skills
from bouzecode.backend.tools.skill.shadow_report import same_repo_file

NOM = "freres-probe"


def _git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                   check=True, capture_output=True)


@pytest.fixture
def depot_et_deux_worktrees(tmp_path, monkeypatch):
    depot = tmp_path / "depot"
    skill = depot / ".bouzecode" / "skills" / NOM / "skill.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(f"---\nname: {NOM}\ndescription: sonde\n---\n\nsonde\n", encoding="utf-8")
    _git("init", "-q", "-b", "develop", cwd=depot)
    _git("add", ".", cwd=depot)
    _git("commit", "-q", "-m", "depart", cwd=depot)
    freres = []
    for nom in ("tui-aaaa", "tui-bbbb"):
        chemin = tmp_path / "worktrees" / nom
        _git("worktree", "add", "-q", "-b", f"agent/{nom}", str(chemin), cwd=depot)
        freres.append(chemin)
    #  Registres du process neufs, rendus intacts apres le test.
    monkeypatch.setattr(paths, "_extra_dirs", [])
    monkeypatch.setattr(paths, "_loaded_projects", [])
    monkeypatch.chdir(tmp_path)
    return depot, freres


def _candidats(resolution) -> list[Path]:
    return [Path(s.file_path).resolve() for s in resolution.candidates_for(NOM)]


def test_un_sous_agent_ne_voit_pas_les_skills_du_worktree_de_son_frere(
        depot_et_deux_worktrees, capsys):
    depot, (wt_a, wt_b) = depot_et_deux_worktrees
    atelier_a, atelier_b = Atelier(dossier=str(wt_a)), Atelier(dossier=str(wt_b))
    _load_project_config(str(depot))            # main (sans atelier) charge le checkout principal
    with dans(atelier_a):
        _load_project_config(str(wt_a))
    with dans(atelier_b):
        _load_project_config(str(wt_b))

    with dans(atelier_a):
        resolution = resolve_skills(include_builtins=False)

    candidats = _candidats(resolution)
    assert candidats[0] == (wt_a / ".bouzecode" / "skills" / NOM / "skill.md").resolve()
    assert not any(wt_b.resolve() in c.parents for c in candidats), candidats
    # Ce que B a charge reste a B : rien n'a fui dans les registres du process.
    assert (wt_b / ".bouzecode").resolve() not in paths._extra_dirs
    assert wt_b.resolve() not in paths._loaded_projects
    # La copie du checkout principal masquee par celle du worktree : meme fichier, meme depot.
    assert "masquée par" not in capsys.readouterr().err


def test_meme_fichier_du_meme_depot_reconnu_entre_checkouts(depot_et_deux_worktrees, tmp_path):
    depot, (wt_a, wt_b) = depot_et_deux_worktrees
    relatif = Path(".bouzecode") / "skills" / NOM / "skill.md"
    assert same_repo_file(str(depot / relatif), str(wt_a / relatif))
    assert same_repo_file(str(wt_a / relatif), str(wt_b / relatif))
    autre = tmp_path / "ailleurs" / relatif
    autre.parent.mkdir(parents=True)
    autre.write_text("x", encoding="utf-8")
    assert not same_repo_file(str(depot / relatif), str(autre))
