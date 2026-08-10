"""Le parcours d'un ticket de code, du branchement au merge sur develop.

Quand un manager confie du code à faire, le système équipe l'agent en codeur et,
si le manager l'a demandé, lui branche un worktree sur develop. Le reste — lancer un
validateur, intégrer — est déclenché explicitement, plus jamais tout seul.

Rien n'est simulé : vrai git sur des dépôts temporaires, et des fonctions de décision
pures pour le reste.
"""
from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from bouzecode.web_v2.services.work import dispatch, integration, tickets, worktrees  # noqa: F401


def _git(repo: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True
    )
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


@pytest.fixture()
def develop_repo(tmp_path: Path) -> Path:
    """A git repo whose default checkout has a `develop` branch and no origin/HEAD."""
    # WORKTREES_DIR is persistent (~/.bouzecode/worktrees) and keyed by repo dir NAME:
    # a shared "repo" name RACES/purges sibling tests under `-n auto` (same fix as
    # test_workflow.py's develop_repo). Unique name per test → no cross-worker collision.
    name = f"cfrepo_{uuid.uuid4().hex[:8]}"
    shutil.rmtree(worktrees.WORKTREES_DIR / name, ignore_errors=True)
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    # rename current branch to main, then create develop
    _git(repo, "branch", "-M", "main")
    _git(repo, "branch", "develop")
    return repo


def test_coder_profile_resolves() -> None:
    """Le codeur est équipé pour écrire du code et lancer les tests, mais pas pour déléguer."""
    from bouzecode.backend.profiles import resolve_agent_profile

    profile = resolve_agent_profile("coder")
    assert profile is not None
    assert "python-coding" in profile.skills
    # Coder equipment: edits code + runs tests, but does NOT spawn sub-agents.
    for tool in ("Read", "Write", "Edit", "Bash", "RunPythonTest", "FinalAnswer"):
        assert tool in profile.tools, f"{tool} missing from coder tools"
    assert "Agent" not in profile.tools


def test_project_coding_skill_registered_and_injectable() -> None:
    """Le codeur reçoit les conventions du projet, dont l'obligation de signaler ses correctifs hors scope."""
    from bouzecode.backend.tools.skill.loader import load_skills
    from bouzecode.backend.core.context import render_profile_skills

    names = {s.name for s in load_skills()}
    assert "python-coding" in names
    # Profile-skill preload path (render_profile_skills) surfaces its content.
    rendered = render_profile_skills(["python-coding"])
    assert "python-coding" in rendered
    assert "uv" in rendered and "unittest.mock" in rendered
    # FIX #4: the coder may fix pre-existing broken tests/files but MUST list each
    # out-of-scope fix in its FinalAnswer.
    assert "hors-scope" in rendered or "hors du scope" in rendered
    assert "PRÉEXISTANT" in rendered


def test_default_branch_develop_first(develop_repo: Path) -> None:
    """Un dépôt sans branche par défaut déclarée part de develop, pas de main."""
    # No origin/HEAD configured → fallback order must prefer develop.
    assert worktrees.default_branch(str(develop_repo)) == "develop"


def test_resolve_profile_direct_default_is_nu(develop_repo: Path) -> None:
    """Un agent lancé à la main reste nu : aucun profil codeur ne lui est imposé."""
    # Lancement DIRECT (managed=False) + typology absente/"default" sur un repo git :
    # l'agent reste NU (comme la TUI), PAS de défaut coder.
    assert dispatch.resolve_profile("", str(develop_repo), managed=False) == ""
    assert dispatch.resolve_profile("default", str(develop_repo), managed=False) == ""


def test_resolve_profile_managed_default_is_coder(develop_repo: Path) -> None:
    """Un agent dispatché par un manager sur un dépôt git devient un codeur d'office."""
    # Spawné par un manager (managed=True) + typology absente/"default" sur un repo git :
    # on force le profil coder (outils et conventions de code).
    assert dispatch.resolve_profile("", str(develop_repo), managed=True) == dispatch._CODER_PROFILE
    assert dispatch.resolve_profile("default", str(develop_repo), managed=True) == dispatch._CODER_PROFILE


def test_resolve_profile_explicit_typology_respected_even_direct() -> None:
    """Un lancement direct avec une typologie inconnue ne se voit pas imposer le profil codeur."""
    # Une typology EXPLICITE (non-default) est respectée telle quelle même en direct :
    # get_typology résout le profil ; typology inconnue → "" (pas de coder forcé).
    # On vérifie au minimum qu'un lancement direct avec typology inconnue ne force PAS coder.
    assert dispatch.resolve_profile("some-unknown-typology", "/tmp/not-a-repo", managed=False) == ""


def test_resolve_profile_managed_default_non_git_is_nu(tmp_path: Path) -> None:
    """Un projet qui n'est pas sous git ne reçoit pas le profil codeur, même dispatché."""
    # Même managé, un projet NON-git ne reçoit pas le défaut coder (pas de régression).
    assert dispatch.resolve_profile("", str(tmp_path), managed=True) == ""


def test_provision_base_develop(develop_repo: Path) -> None:
    """Isoler un ticket crée une branche agent/<ticket> partant du dernier commit de develop."""
    meta = worktrees.provision(
        str(develop_repo), "t-123", base_branch="develop", with_venv=False
    )
    assert meta["ok"]
    assert meta["base"] == "develop"
    assert meta["branch"] == "agent/t-123"
    assert Path(meta["worktree"]).exists()
    dev = _git(develop_repo, "rev-parse", "develop")
    agent = _git(develop_repo, "rev-parse", "agent/t-123")
    assert dev == agent
    worktrees.cleanup(meta)


def test_build_validator_prompt() -> None:
    """Le validateur reçoit la demande d'origine, le diff à juger, et le format de verdict attendu."""
    ticket = {"title": "T", "prompt": "implémente X"}
    p = tickets.build_validator_prompt(ticket, "diff --git a/f b/f\n+code")
    assert "implémente X" in p
    assert "DIFF À VALIDER" in p
    assert "diff --git" in p
    assert "VERDICT: OK" in p and "VERDICT: KO" in p
    # FIX #4: the validator is told not to KO reasonable, reported out-of-scope fixes.
    assert "hors du scope" in p and "NE mets PAS KO" in p


def test_build_validator_prompt_includes_report() -> None:
    """Le validateur reçoit aussi le rapport du codeur — et rien de tel si le codeur n'en a pas laissé."""
    # The validator must be fed the coder's FinalAnswer, not just the diff (spec).
    ticket = {"title": "T", "prompt": "implémente X"}
    p = tickets.build_validator_prompt(ticket, "diff", report="RAPPORT: fait X en 3 fichiers")
    assert "RAPPORT DU CODEUR" in p
    assert "RAPPORT: fait X en 3 fichiers" in p
    # Empty report → no report section.
    assert "RAPPORT DU CODEUR" not in tickets.build_validator_prompt(ticket, "diff")


def test_extract_final_answer() -> None:
    """Le rapport de fin du codeur est retrouvé quelle que soit la forme sous laquelle il l'a rendu."""
    messages = [
        {"role": "user", "content": "do X"},
        {"role": "assistant", "content": "working",
         "tool_calls": [{"name": "FinalAnswer", "input": {"answer": "RAPPORT: fait X"}}]},
    ]
    assert tickets.extract_final_answer(messages) == "RAPPORT: fait X"
    assert tickets.extract_final_answer([]) == ""
    # tool_result form is also recognized.
    tool_form = [{"role": "tool", "name": "FinalAnswer", "content": "RAPPORT via tool"}]
    assert tickets.extract_final_answer(tool_form) == "RAPPORT via tool"


def test_integrate_merges_to_develop(develop_repo: Path) -> None:
    """Intégrer un ticket vert ramène ses fichiers sur develop dans le dépôt d'origine."""
    meta = worktrees.provision(
        str(develop_repo), "t-merge", base_branch="develop", with_venv=False
    )
    assert meta["ok"]
    (Path(meta["worktree"]) / "feature.py").write_text("x = 1\n", encoding="utf-8")
    worktrees.harvest(meta, "T")
    _git(develop_repo, "checkout", "-q", "develop")
    result = worktrees.integrate(meta)
    assert result["ok"], result
    assert (develop_repo / "feature.py").exists()
    worktrees.cleanup(meta)
