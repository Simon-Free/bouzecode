# [desc] Fin d'un sous-agent en arrière-plan : silence dans le fil de main quand la barre des sous-agents du TUI est active, notice + aperçu sinon. [/desc]
"""L'utilisateur (2026-10-14) : la fin d'un sous-agent imprimait dans le fil de main une
ligne « ✓ Background agent … completed » et 200 caractères de sa réponse finale. Avec la
barre des sous-agents (`_tui_agents`), elle montre déjà ✓/✗ et la réponse se lit en ouvrant
l'agent aux flèches : main ne doit rien imprimer. Sans barre, le comportement reste."""
from __future__ import annotations

import uuid

import pytest

from bouzecode.backend.commands import _print_background_notifications
from bouzecode.backend.multi_agent import gestionnaire
from bouzecode.backend.multi_agent.manager import SubAgentManager
from bouzecode.backend.multi_agent.task import SubAgentTask


@pytest.fixture
def sous_agent_termine(monkeypatch):
    """Un gestionnaire neuf portant un sous-agent en arrière-plan qui vient de finir."""
    manager = SubAgentManager(max_concurrent=1)
    monkeypatch.setattr(gestionnaire, "_agent_manager", manager)
    tache = SubAgentTask(id=uuid.uuid4().hex, prompt="rends le ticket", status="completed",
                         name="rendu-humain-ticket", worktree_branch="agent/tui-dd99f233",
                         result="## 1. Résumé\nL'onglet « Rendu » est en place.")
    manager.tasks[tache.id] = tache
    yield tache
    manager._pool.shutdown(wait=False)


def test_barre_active_main_n_imprime_rien_a_la_fin_d_un_sous_agent(sous_agent_termine, capsys):
    """Barre des sous-agents active : ni notice ni aperçu de réponse dans le fil de main."""
    _print_background_notifications({"_tui_agents": object()})
    assert capsys.readouterr().out == ""


def test_sans_barre_la_fin_d_un_sous_agent_reste_annoncee(sous_agent_termine, capsys):
    """Sans barre (non interactif, ancien mode terminal) : notice et aperçu, une seule fois."""
    _print_background_notifications({})
    sortie = capsys.readouterr().out
    assert "Background agent 'rendu-humain-ticket' completed [branch: agent/tui-dd99f233]" in sortie
    assert "L'onglet « Rendu » est en place." in sortie
    _print_background_notifications({})
    assert capsys.readouterr().out == ""
