# [desc] Hors web (thread en process, fenêtre de terminal), Agent honore `background` comme en web : true rend la main, défaut = attente, `wait` ancien alias inverse prioritaire. [/desc]
"""TODO §4 (2026-09-25) : le schéma d'Agent documente `background`, mais seuls les
tickets web le lisaient ; les chemins thread et terminal ne lisaient que `wait` (défaut
True). `background=true` y était donc IGNORÉ : le parent attendait quand même chaque
enfant. Aucun vrai LLM ni vraie fenêtre : gestionnaire et lanceur sont des faux.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from bouzecode.backend.multi_agent import gestionnaire as module_gestionnaire
from bouzecode.backend.multi_agent import lancement_terminal, outil_agent


class _FauxGestionnaire:
    """Le strict nécessaire de SubAgentManager : spawn/create_task/wait, et on note les attentes."""

    def __init__(self):
        self.attentes = []
        self.tasks = {}

    def _tache(self, name=""):
        tache = SimpleNamespace(id=f"t{len(self.tasks)}", name=name or "enfant", status="running",
                                result="", worktree_branch="", agent_type="", model="")
        self.tasks[tache.id] = tache
        return tache

    def spawn(self, prompt, config, system_prompt, **kw):
        return self._tache(kw.get("name", ""))

    def create_task(self, prompt, depth=0, name=""):
        return self._tache(name)

    def wait(self, task_id, timeout=None):
        self.attentes.append(task_id)
        self.tasks[task_id].status = "completed"
        self.tasks[task_id].result = "fini"


@pytest.fixture
def gestionnaire(monkeypatch):
    faux = _FauxGestionnaire()
    monkeypatch.setattr(module_gestionnaire, "get_agent_manager", lambda: faux)
    monkeypatch.setattr(outil_agent, "_is_terminal_mode", lambda: False)
    monkeypatch.setattr("bouzecode.backend.tools.interaction.is_web_ipc_active", lambda: False)
    return faux


@pytest.mark.parametrize("params, attend", [
    ({"background": True}, False),
    ({}, True),                                    # défaut : le parent attend
    ({"background": False}, True),
    ({"wait": False}, False),                      # ancien alias, inverse
    ({"background": True, "wait": True}, True),    # `wait` fourni prime
])
def test_thread_en_process_honore_background(gestionnaire, params, attend):
    res = outil_agent._agent_tool({"prompt": "fais X", **params}, {})
    assert bool(gestionnaire.attentes) is attend, res
    if not attend:
        assert "Task ID" in res


@pytest.mark.parametrize("params, attend", [
    ({"background": True}, False),
    ({}, True),
    ({"wait": False}, False),
])
def test_fenetre_de_terminal_honore_background(gestionnaire, monkeypatch, tmp_path, params, attend):
    # Le lanceur de fenêtre écrit tout de suite le fichier résultat : en attente, on le lit.
    def faux_lanceur(prompt, result_file, eff_config, env_extra=None):
        from pathlib import Path
        Path(result_file).write_text("rapport", encoding="utf-8")

    monkeypatch.setattr("bouzecode.backend.multi_agent.terminal.spawn_in_terminal", faux_lanceur)
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(lancement_terminal, "_TERMINAL_WAIT_INTERVAL", 0.01)
    res = lancement_terminal._spawn_terminal_agent({"prompt": "fais X", **params}, {})
    # L'attente passe par le gestionnaire (suivi du fichier résultat par un thread).
    assert bool(gestionnaire.attentes) is attend, res
    if not attend:
        assert "Task ID" in res
