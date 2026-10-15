# [desc] Le hook de fin d'un agent annonce sa fin sur la route INTERNE avec le jeton propre à son run ; sans jeton (agent d'avant L3), il n'appelle rien : le watchdog constate sa fin. [/desc]
from __future__ import annotations

from bouzecode.backend.agent.hooks.completion import run_completion_chain
from bouzecode.backend.agent.hooks.context import HookContext


class _Contexte(HookContext):
    """Le vrai HookContext, dont seul l'appel HTTP est consigné au lieu d'être émis."""

    def http_post(self, path, body, timeout=60, headers=None):
        self.appels.append((path, body, headers))
        return {}


def _fin(monkeypatch, jeton: str):
    monkeypatch.setenv("BOUZECODE_TICKET_SLUG", "proj")
    monkeypatch.setenv("BOUZECODE_TICKET_ID", "t1")
    if jeton:
        monkeypatch.setenv("BOUZECODE_RUN_TOKEN", jeton)
    else:
        monkeypatch.delenv("BOUZECODE_RUN_TOKEN", raising=False)
    ctx = _Contexte(event="on_completion", self_id="ag1", close_reason="final_answer")
    ctx.appels = []
    run_completion_chain(ctx)
    return ctx.appels


def test_avec_jeton_la_fin_part_sur_la_route_interne(monkeypatch):
    (chemin, corps, en_tetes), = _fin(monkeypatch, "secret")
    assert chemin == "/internal/runs/ag1/ended"
    assert en_tetes == {"X-Bouzecode-Run-Token": "secret"}
    assert corps["close_reason"] == "final_answer"


def test_sans_jeton_la_fin_n_appelle_aucune_route(monkeypatch):
    """L'alias `/completed` est retiré (L6) : le watchdog constate la fin d'un tel agent."""
    assert _fin(monkeypatch, "") == []
