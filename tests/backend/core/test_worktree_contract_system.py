# [desc] Vérifie que le contrat worktree est injecté dans le system prompt (volatile) via l'env BOUZECODE_WORKTREE_ROOT. [/desc]
"""Le contrat worktree ne préfixe plus le prompt user (voir
tests/web_v2/test_dispatch_prompt_intact.py) : il fait désormais partie du system prompt.
build_system_prompt_parts lit l'env BOUZECODE_WORKTREE_ROOT (armée au spawn par le runner)
et, si non vide, ajoute le contrat dans la moitié volatile (celle qui dépend du cwd/session)."""
from bouzecode.backend.core.context import build_system_prompt_parts


def test_worktree_contract_in_system_when_isolated(monkeypatch):
    wt = r"C:\some\worktree\child"
    monkeypatch.setenv("BOUZECODE_WORKTREE_ROOT", wt)
    stable, volatile = build_system_prompt_parts({})
    # Le contrat est dans le SYSTEM prompt (volatile), pas ailleurs.
    assert "worktree isolé" in volatile
    assert wt in volatile
    assert "n'est PAS récolté" in volatile
    assert "git -C" in volatile


def test_no_worktree_contract_when_not_isolated(monkeypatch):
    monkeypatch.delenv("BOUZECODE_WORKTREE_ROOT", raising=False)
    stable, volatile = build_system_prompt_parts({})
    assert "worktree isolé" not in volatile
    assert "worktree isolé" not in stable


def test_no_worktree_contract_when_env_empty(monkeypatch):
    monkeypatch.setenv("BOUZECODE_WORKTREE_ROOT", "")
    stable, volatile = build_system_prompt_parts({})
    assert "worktree isolé" not in volatile
