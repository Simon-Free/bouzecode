"""Régression fleet hiérarchique : quand un sous-agent (descendant à n'importe quelle
profondeur) tourne, TOUS ses ancêtres doivent apparaître « running » dans l'arbre de la
fleet. Avant le fix, `_node` posait `liveness = classify_agent_run(...)` qui est SELF-ONLY
(regarde seulement le pid/ipc/close_reason de CET agent) — donc un grand-parent terminé
dont l'enfant tourne encore restait « delivered », ce qui est faux.

On teste la dérivation via `_agent_tree_uncached()` (contourne le cache 2 s) avec 3 agents
grand-parent → parent → enfant, seul l'enfant étant classé « running ». On isole EXACTEMENT
la logique de propagation en fakant `classify_agent_run` (self-only) : le test échoue AVANT
le fix (gp/p = delivered) et passe APRÈS (gp/p = running). Zéro unittest.mock, deps pilotées
par monkeypatch.setattr comme le reste du dossier."""
from __future__ import annotations

from bouzecode.web_v2.runtime.runner import Agent
from bouzecode.web_v2.services.work import fleet


def _agent(agent_id: str, parent: str) -> Agent:
    # Vrai `Agent` (pas un SimpleNamespace) : _node lit aussi pid/ipc_dir/finished_at via
    # runner.is_warm, et une fixture partielle cassait avec un AttributeError sans que rien
    # ne soit faux dans le code produit.
    # cwd="" court-circuite toutes les branches `if agent.cwd` de _node (repos/branch/project).
    return Agent(
        agent_id=agent_id,
        parent=parent,
        cwd="",
        session_path="",
        prompt=f"prompt {agent_id}",
        model="m",
        profile="p",
        returncode=0,
        started_at="2026-07-15T00:00:00",
        run_kind="work",
        pid=0,
    )


def _wire(monkeypatch, running_ids: set[str]):
    agents = [
        _agent("gp", ""),      # grand-parent (racine)
        _agent("p", "gp"),     # parent
        _agent("c", "p"),      # enfant : le seul qui tourne
    ]
    monkeypatch.setattr(fleet.runner, "list_agents", lambda: agents)
    monkeypatch.setattr(fleet.projects, "list_projects", lambda: [])
    monkeypatch.setattr(fleet.store, "list_agent_sessions", lambda: [])
    monkeypatch.setattr(fleet.store, "agent_status", lambda a: {"state": "finished"})
    monkeypatch.setattr(fleet.purge, "load_deleted", lambda: set())
    # classify_agent_run est SELF-ONLY dans le vrai code : on reproduit ce contrat exact
    # (running uniquement pour les agents effectivement vivants), ce que le fix doit ensuite
    # propager aux ancêtres.
    monkeypatch.setattr(
        fleet.liveness, "classify_agent_run",
        lambda ticket, run: "running" if str(run.get("agent_id")) in running_ids else "delivered",
    )


def _by_id(tree: dict) -> dict[str, dict]:
    return {n["agent_id"]: n for n in tree["nodes"]}


def test_ancestors_running_when_deep_descendant_runs(monkeypatch):
    # Seul l'enfant (2 niveaux sous le grand-parent) tourne.
    _wire(monkeypatch, running_ids={"c"})

    nodes = _by_id(fleet._agent_tree_uncached())

    assert nodes["c"]["liveness"] == "running"   # self-only : l'enfant tourne
    assert nodes["p"]["liveness"] == "running"   # parent direct → propagé
    assert nodes["gp"]["liveness"] == "running"  # grand-parent (transitif) → propagé


def test_ancestors_not_running_when_no_descendant_runs(monkeypatch):
    # Non-régression : aucun descendant ne tourne → aucun ancêtre n'est faussement « running ».
    _wire(monkeypatch, running_ids=set())

    nodes = _by_id(fleet._agent_tree_uncached())

    assert nodes["c"]["liveness"] == "delivered"
    assert nodes["p"]["liveness"] == "delivered"
    assert nodes["gp"]["liveness"] == "delivered"
