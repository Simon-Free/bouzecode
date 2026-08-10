# [desc] dispatch._launch : prompt user transmis intact sans reroot, contrat worktree migré vers le system prompt. [/desc]
"""Remplace test_dispatch_reroot.py : le reroot silencieux des chemins absolus du prompt
(_reroot_prompt_to_child / _reroot_paths) a falsifié 5 missions git cross-repo (KO à tort,
indébogable). Décision utilisateur : ne plus réécrire le prompt, le transmettre INTACT. Le
contrat explicite « worktree isolé » ne préfixe PLUS le message user — il est injecté dans le
SYSTEM prompt de l'agent (via l'env BOUZECODE_WORKTREE_ROOT, voir
tests/backend/core/test_worktree_contract_system.py).

Ces tests jouent le VRAI point d'entrée dispatch._launch (spawn réel d'un subprocess via
runner.create_agent, capturé par un fake runner injecté — pas de mock.patch) et vérifient
le prompt effectivement remis à l'agent."""
import os

import pytest

from bouzecode.web_v2.services.work import dispatch


class _FakeAgent:
    def __init__(self, prompt, cwd, worktree_root):
        self.agent_id = "fakeagent01"
        self.prompt = prompt
        self.cwd = cwd
        self.worktree_root = worktree_root


class _CaptureRunner:
    """Fake runner en mémoire : capture les arguments réels de create_agent (le prompt
    remis à l'agent, le worktree_root armé) sans lancer de subprocess."""

    def __init__(self):
        self.captured = None

    def create_agent(self, prompt, model, cwd, profile="", parent="",
                      ticket_slug="", ticket_id="", worktree_root="", **kw):
        self.captured = {
            "prompt": prompt, "cwd": cwd, "worktree_root": worktree_root,
            "profile": profile, "parent": parent,
        }
        return _FakeAgent(prompt, cwd, worktree_root)

    def load_agent(self, agent_id):
        return None


class _NoopTickets:
    def add_run(self, *a, **kw):
        return None


@pytest.fixture
def wired(monkeypatch, tmp_path):
    """Injecte un runner/tickets fakes + neutralise l'isolation git : _launch reçoit
    un cwd (worktree enfant) ≠ project_path, exactement comme en prod pour un agent isolé."""
    runner = _CaptureRunner()
    monkeypatch.setattr(dispatch, "runner", runner)
    monkeypatch.setattr(dispatch, "tickets", _NoopTickets())
    child_wt = str(tmp_path / "wt" / "child")
    os.makedirs(child_wt, exist_ok=True)
    # `_maybe_isolate(…, with_venv)` a été remplacé par `_provision_worktree(…, isolation,
    # work_branch)` : le venv n'est plus un booléen mais un mode d'isolation à part entière.
    monkeypatch.setattr(
        dispatch, "_provision_worktree",
        lambda slug, ticket, project_path, resume_branch="", isolation=dispatch.WORKTREE,
        work_branch="": child_wt)
    return runner, child_wt


def _ticket(prompt):
    return {"id": "t1", "prompt": prompt, "title": "T", "typology": ""}


def test_isolated_prompt_transmitted_intact(wired):
    """(a) Le prompt du ticket porte des chemins absolus du repo/parent : ils doivent être
    transmis SANS AUCUNE réécriture (fin du reroot silencieux qui falsifiait cross-repo)."""
    runner, child_wt = wired
    original = (r"Modifie C:\repo\bouzecode\src\bouzecode\web_v2\static\app.css "
                r"puis git -C C:\repo\other rev-parse HEAD")
    dispatch._launch("slug", _ticket(original), project_path=r"C:\repo\bouzecode",
                     profile="coder", model="", isolation=dispatch.WORKTREE,
                     parent="dispatcher:manual")
    delivered = runner.captured["prompt"]
    # Le prompt ORIGINAL est présent tel quel — aucun chemin réécrit vers le worktree enfant.
    assert original in delivered
    assert r"C:\repo\bouzecode\src\bouzecode\web_v2\static\app.css" in delivered
    assert child_wt not in original  # sanity : le worktree enfant n'était pas dans l'original
    # worktree_root armé = chemin du worktree enfant (active le signalement non bloquant + le
    # contrat worktree dans le system prompt côté agent).
    assert runner.captured["worktree_root"] == child_wt


def test_isolated_prompt_has_no_worktree_contract(wired):
    """(d) Le contrat « worktree isolé » ne fait PLUS partie du prompt user : il a migré dans
    le system prompt. Le prompt délivré est STRICTEMENT le prompt du ticket, rien de plus."""
    runner, child_wt = wired
    dispatch._launch("slug", _ticket("fais le boulot"), project_path=r"C:\repo\bouzecode",
                     profile="coder", model="", isolation=dispatch.WORKTREE,
                     parent="dispatcher:manual")
    delivered = runner.captured["prompt"]
    # Aucun fragment du contrat ne doit polluer le message user.
    assert "worktree isolé" not in delivered
    assert "n'est PAS récolté" not in delivered
    assert child_wt not in delivered
    # Le prompt du ticket est transmis tel quel, sans préfixe ni suffixe.
    assert delivered == "fais le boulot"
    # worktree_root reste armé (il alimente le contrat côté system prompt via l'env).
    assert runner.captured["worktree_root"] == child_wt


def test_non_isolated_prompt_untouched(wired):
    """Agent NON isolé (cwd == project_path) : prompt strictement intact, aucun contrat,
    worktree_root vide (pas de signalement hors-worktree pour un agent non isolé)."""
    runner, _ = wired
    monkeypatch_project = r"C:\repo\bouzecode"
    # isolation=shared → cwd = project_path, pas de contrat.
    dispatch._launch("slug", _ticket("tache simple"), project_path=monkeypatch_project,
                     profile="coder", model="", isolation=dispatch.SHARED,
                     parent="dispatcher:manual")
    assert runner.captured["prompt"] == "tache simple"
    assert runner.captured["worktree_root"] == ""
