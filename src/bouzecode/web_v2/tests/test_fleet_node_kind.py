"""§1 — le tree expose `kind` (work/validate/merge/dispatch/manual) sur chaque node.

Dérivé structurellement de agent.run_kind (stocké à la création de l'agent), plus
fiable que deviner via le titre. Sert au front à ne JAMAIS promouvoir un validateur
orphelin (parent archivé) au rang de racine standard dans /conversations.
"""
from bouzecode.web_v2.runtime.runner import Agent
from bouzecode.web_v2.services.work import fleet


def _agent(run_kind, returncode=0):
    # Vrai `Agent` (pas un SimpleNamespace) : _node lit aussi pid/ipc_dir/finished_at via
    # runner.is_warm, et une fixture partielle cassait avec un AttributeError sans que rien
    # ne soit faux dans le code produit.
    # cwd="" court-circuite repos/worktrees (pas de repo réel à sonder).
    return Agent(
        agent_id="dcd72724",
        parent="402a41074631",
        session_path="",
        prompt="valide la PR",
        cwd="",
        model="sonnet",
        profile="",
        run_kind=run_kind,
        returncode=returncode,
        started_at="2026-07-07T10:00:00Z",
        pid=0,
    )


def _meta(state="finished"):
    # meta.status renseigné → _node n'appelle pas store.agent_status (pas de session).
    return {"status": {"state": state}, "turn_count": 3}


def test_node_exposes_kind_validate():
    node = fleet._node(_agent("validate"), _meta(), [])
    assert node["kind"] == "validate"


def test_node_exposes_kind_work():
    node = fleet._node(_agent("work"), _meta(), [])
    assert node["kind"] == "work"


def test_node_kind_empty_when_run_kind_none():
    node = fleet._node(_agent(None), _meta(), [])
    assert node["kind"] == ""
