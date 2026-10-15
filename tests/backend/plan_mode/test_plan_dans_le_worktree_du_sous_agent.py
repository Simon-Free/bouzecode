# [desc] WritePlan d'un sous-agent en process : le plan va dans SON worktree (atelier), sous un nom propre a lui ; le principal sans atelier ecrit toujours dans son cwd. [/desc]
"""Symptome d'origine : un sous-agent du TUI isole dans
`~/.bouzecode/worktrees/demo_application/tui-ede3e4f6` appelle WritePlan et lit
`Plan saved to …/demo_application/.nano_claude/plans/default.md` — le checkout principal
(cwd du process), sous le nom partage `default.md` que le principal et chaque frere ecrasent.

Vrai outil (execute_tool, qui active l'atelier de la config comme pour un vrai sous-agent),
vrai disque ; seul le cwd du process est deplace (monkeypatch.chdir)."""
from __future__ import annotations

from pathlib import Path

import pytest

import bouzecode.backend.tools  # noqa: F401 — enregistre les outils (WritePlan)
from bouzecode.backend.core.dossier_agent import Atelier, dans
from bouzecode.backend.core.tool_registry import execute_tool
from bouzecode.backend.tools.plan_mode import _enter_plan_mode


@pytest.fixture
def principal_et_worktree(tmp_path, monkeypatch):
    principal, worktree = tmp_path / "principal", tmp_path / "worktrees" / "tui-ede3e4f6"
    principal.mkdir()
    worktree.mkdir(parents=True)
    monkeypatch.chdir(principal)
    return principal, worktree


def _ecrire_plan(config: dict, contenu: str) -> str:
    return execute_tool("WritePlan", {"content": contenu}, config)


def test_le_plan_d_un_sous_agent_va_dans_son_worktree_sous_son_nom(principal_et_worktree):
    principal, worktree = principal_et_worktree
    config = {"_tui_moi": "ede3e4f6", "_atelier": Atelier(dossier=str(worktree))}

    sortie = _ecrire_plan(config, "# Plan du sous-agent\n")

    attendu = worktree / ".nano_claude" / "plans" / "sous-agent-ede3e4f6.md"
    assert f"Plan saved to {attendu}" in sortie
    assert attendu.read_text(encoding="utf-8") == "# Plan du sous-agent\n"
    assert not (principal / ".nano_claude").exists()


def test_le_principal_sans_atelier_ecrit_toujours_dans_son_cwd(principal_et_worktree):
    principal, _worktree = principal_et_worktree

    sortie = _ecrire_plan({"_session_id": "s1"}, "# Plan du principal\n")

    attendu = principal / ".nano_claude" / "plans" / "s1.md"
    assert f"Plan saved to {attendu}" in sortie
    assert attendu.read_text(encoding="utf-8") == "# Plan du principal\n"


def test_principal_et_freres_ne_s_ecrasent_plus_leurs_plans(principal_et_worktree):
    principal, _worktree = principal_et_worktree
    #  Meme dossier pour tous (sous-agents sans worktree propre) : seul le nom les separe.
    _ecrire_plan({}, "principal")
    for frere in ("aaaa", "bbbb"):
        with dans(Atelier(dossier=str(principal))):
            _ecrire_plan({"_tui_moi": frere}, f"frere {frere}")

    plans = principal / ".nano_claude" / "plans"
    assert (plans / "default.md").read_text(encoding="utf-8") == "principal"
    assert (plans / "sous-agent-aaaa.md").read_text(encoding="utf-8") == "frere aaaa"
    assert (plans / "sous-agent-bbbb.md").read_text(encoding="utf-8") == "frere bbbb"


def test_enter_plan_mode_d_un_sous_agent_ouvre_le_plan_dans_son_worktree(principal_et_worktree):
    principal, worktree = principal_et_worktree
    config = {"_tui_moi": "ede3e4f6"}
    #  EnterPlanMode n'est pas dans le jeu d'outils par defaut : appel direct, sous l'atelier
    #  que le fil du sous-agent porte de bout en bout (multi_agent/en_process/execution.py).
    with dans(Atelier(dossier=str(worktree))):
        _enter_plan_mode({"task_description": "sonde"}, config)

    assert Path(config["_plan_file"]) == worktree / ".nano_claude" / "plans" / "sous-agent-ede3e4f6.md"
    assert not (principal / ".nano_claude").exists()
