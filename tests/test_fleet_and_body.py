# [desc] Tests user-centric: json_body tolère les encodages accentués + Fleet tool (list/kill) via fakes injectés. [/desc]
"""Tests user-centric pour les 2 features anti-400-encodage du manager.

- json_body : on lui passe un faux request qui expose get_data() renvoyant des
  octets bruts (comme Flask), et on vérifie que tout body accentué mal encodé est
  accepté au lieu de lever une 400.
- Fleet : on exécute la VRAIE fonction _fleet_tool, en injectant des fakes purs
  (monkeypatch.setattr, PAS unittest.mock) pour la flotte et le runner.
"""
from __future__ import annotations

import json

from bouzecode.web_v2.routes._body import json_body


class _FakeReq:
    """Imite l'API Flask consommée par json_body : get_data(cache, as_text) -> bytes."""

    def __init__(self, raw: bytes) -> None:
        self._raw = raw

    def get_data(self, cache: bool = True, as_text: bool = False):
        return self._raw


def _req_from(obj, encoding: str) -> _FakeReq:
    return _FakeReq(json.dumps(obj, ensure_ascii=False).encode(encoding))


# ── json_body ─────────────────────────────────────────────────────────────────

def test_json_body_utf8_accents():
    body = {"title": "café crème", "prompt": "à décoder"}
    assert json_body(_req_from(body, "utf-8")) == body


def test_json_body_utf8_sig_bom():
    body = {"title": "naïve", "prompt": "œuf"}
    assert json_body(_req_from(body, "utf-8-sig")) == body


def test_json_body_latin1_accents():
    # PowerShell réencode volontiers un body accentué en latin-1 : ne doit PAS 400.
    body = {"title": "élan", "prompt": "hôpital où"}
    result = json_body(_req_from(body, "latin-1"))
    # latin-1 est décodé sans exception ; les accents survivent tels quels.
    assert result == body


def test_json_body_empty_returns_dict():
    assert json_body(_FakeReq(b"")) == {}


def test_json_body_non_object_json_returns_dict():
    assert json_body(_FakeReq(b"[1, 2, 3]")) == {}
    assert json_body(_FakeReq(b'"scalar"')) == {}


def test_json_body_garbage_returns_dict():
    assert json_body(_FakeReq(b"not json at all {{{")) == {}


# ── Fleet tool ──────────────────────────────────────────────────────────────

from bouzecode.backend.multi_agent import outils_flotte
from bouzecode.backend.tools import interaction as _interaction
from bouzecode.web_v2.runtime.runner import agent_arret, agent_fiche, agent_registre
from bouzecode.web_v2.services.work import fleet as _fleet_service


class _FakeAgent:
    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id


def _enable_web(monkeypatch):
    monkeypatch.setattr(_interaction, "is_web_ipc_active", lambda: True)


def test_fleet_requires_web_mode(monkeypatch):
    monkeypatch.setattr(_interaction, "is_web_ipc_active", lambda: False)
    out = outils_flotte._fleet_tool({"action": "list"}, {})
    assert "web" in out.lower()


def test_fleet_invalid_action(monkeypatch):
    _enable_web(monkeypatch)
    out = outils_flotte._fleet_tool({"action": "bogus"}, {})
    assert "'list' ou 'kill'" in out


def test_fleet_list_renders_nodes(monkeypatch):
    _enable_web(monkeypatch)
    nodes = {
        "nodes": [
            {"agent_id": "abc123", "state": "busy", "project_name": "demo",
             "parent": "", "title": "fix bug", "suspect_dead": True},
            {"agent_id": "def456", "state": "done", "project_slug": "web",
             "parent": "abc123", "title": "review"},
        ]
    }
    monkeypatch.setattr(_fleet_service, "agent_tree", lambda: nodes)
    out = outils_flotte._fleet_tool({"action": "list"}, {})
    assert "2 agent(s)" in out
    assert "abc123" in out and "def456" in out
    assert "suspect_dead" in out
    assert "demo" in out


def test_fleet_list_empty(monkeypatch):
    _enable_web(monkeypatch)
    monkeypatch.setattr(_fleet_service, "agent_tree", lambda: {"nodes": []})
    out = outils_flotte._fleet_tool({"action": "list"}, {})
    assert "Aucun agent" in out


def test_fleet_kill_requires_agent_id(monkeypatch):
    _enable_web(monkeypatch)
    out = outils_flotte._fleet_tool({"action": "kill"}, {})
    assert "agent_id" in out


def test_fleet_kill_not_found(monkeypatch):
    _enable_web(monkeypatch)
    monkeypatch.setattr(agent_registre, "list_agents", lambda: [_FakeAgent("other")])
    out = outils_flotte._fleet_tool({"action": "kill", "agent_id": "ghost"}, {})
    assert "introuvable" in out
    assert "ghost" in out


def test_fleet_kill_success(monkeypatch):
    _enable_web(monkeypatch)
    target = _FakeAgent("victim")
    monkeypatch.setattr(agent_registre, "list_agents", lambda: [_FakeAgent("other"), target])
    killed = []
    monkeypatch.setattr(agent_arret, "kill_agent", lambda a: killed.append(a))
    out = outils_flotte._fleet_tool({"action": "kill", "agent_id": "victim"}, {})
    assert killed == [target]
    assert "victim" in out


# ── fleet._node : heuristique suspect_dead ───────────────────────────────────
#
# Régression e5b6c622 : un agent finished + returncode=0 était flaggé
# suspect_dead (dot rouge « mort » injustifié). rc=0 = succès propre → jamais
# suspect. On teste la SOURCE (fleet._node), pas le rendu.


def _NodeAgent(*, returncode, run_kind="work", agent_id="ag1"):
    """Vrai runner.Agent pour fleet._node, plutôt qu'un sosie à champs figés.

    Un stub maison redevient périmé dès qu'`Agent` gagne un champ que `_node` lit
    (c'est ce qui est arrivé avec pid/ipc_dir/finished_at). pid=0 => jamais « warm »,
    ce qui est bien l'état d'un agent fabriqué de toutes pièces ici.
    """
    return agent_fiche.Agent(
        agent_id=agent_id, prompt="", model="", cwd="", pid=0, started_at="",
        returncode=returncode, run_kind=run_kind,
    )


def _node_of(agent, *, state="finished", turns=0):
    meta = {"status": {"state": state}, "turn_count": turns}
    return _fleet_service._node(agent, meta, [])


def test_node_finished_rc0_not_suspect():
    # Cas e5b6c622 : fini proprement (rc=0) sans tour → PAS suspect.
    n = _node_of(_NodeAgent(returncode=0), state="finished", turns=0)
    assert n["suspect_dead"] is False


def test_node_finished_rc_nonzero_is_suspect():
    # Vrai mort anormal : fini sans tour ET rc non nul.
    n = _node_of(_NodeAgent(returncode=1), state="finished", turns=0)
    assert n["suspect_dead"] is True


def test_node_finished_rc_none_is_suspect():
    # rc absent (None) + fini sans tour → suspect.
    n = _node_of(_NodeAgent(returncode=None), state="finished", turns=0)
    assert n["suspect_dead"] is True


def test_node_finished_with_turns_not_suspect():
    # A produit des tours → jamais suspect, même rc non nul.
    n = _node_of(_NodeAgent(returncode=1), state="finished", turns=5)
    assert n["suspect_dead"] is False


def test_node_ne_porte_plus_de_verdict():
    """Le validateur de tickets a été retiré (D1) : même un ancien agent `validate` n'a
    plus de verdict dans l'arbre."""
    n = _node_of(_NodeAgent(returncode=1, run_kind="validate"), state="finished")
    assert "verdict" not in n


# ── fleet._agent_tree_uncached : tri par DERNIÈRE INTERACTION (saved_at) ──────
#
# La liste /conversations doit remonter l'activité la PLUS RÉCENTE en tête, pas la
# date de création. Le tri suit saved_at (dernière sauvegarde ≈ dernière activité),
# fallback started_at pour les sessions jamais sauvées. On teste la SOURCE
# (fleet._agent_tree_uncached), pas le rendu.


def test_agent_tree_sorts_by_last_interaction(monkeypatch):
    # A créé TÔT (started_at ancien) mais interagi RÉCEMMENT (saved_at récent).
    # B créé TARD (started_at récent) mais interagi il y a longtemps (saved_at ancien).
    # Tri par création → B devant. Tri par dernière interaction → A devant (attendu).
    agent_a = _NodeAgent(returncode=0, agent_id="A")
    agent_a.started_at = "2026-07-01T00:00:00"
    agent_b = _NodeAgent(returncode=0, agent_id="B")
    agent_b.started_at = "2026-07-09T00:00:00"

    monkeypatch.setattr(agent_registre, "list_agents", lambda: [agent_a, agent_b])
    monkeypatch.setattr(_fleet_service.purge, "load_deleted", lambda: set())
    monkeypatch.setattr(_fleet_service.projects, "list_projects", lambda: [])
    monkeypatch.setattr(
        _fleet_service.store,
        "list_agent_sessions",
        lambda: [
            {"key": "agent/A", "saved_at": "2026-07-09T12:00:00",
             "status": {"state": "finished"}, "turn_count": 3},
            {"key": "agent/B", "saved_at": "2026-07-02T00:00:00",
             "status": {"state": "finished"}, "turn_count": 3},
        ],
    )

    nodes = _fleet_service._agent_tree_uncached()["nodes"]
    # A a interagi le plus récemment (saved_at) → doit être en tête, malgré une
    # création antérieure à celle de B.
    assert [n["agent_id"] for n in nodes] == ["A", "B"]
    assert nodes[0]["saved_at"] == "2026-07-09T12:00:00"


def test_agent_tree_awaiting_floats_above_more_recent(monkeypatch):
    # Un agent en attente d'input (awaiting_input) remonte AU-DESSUS d'un agent plus
    # récent par saved_at mais non bloqué. Prouve que le float awaiting_* survit au
    # changement de clé de tri (saved_at).
    agent_recent = _NodeAgent(returncode=0, agent_id="R")
    agent_recent.started_at = "2026-07-09T00:00:00"
    agent_await = _NodeAgent(returncode=0, agent_id="W")
    agent_await.started_at = "2026-07-01T00:00:00"

    monkeypatch.setattr(agent_registre, "list_agents", lambda: [agent_recent, agent_await])
    monkeypatch.setattr(_fleet_service.purge, "load_deleted", lambda: set())
    monkeypatch.setattr(_fleet_service.projects, "list_projects", lambda: [])
    monkeypatch.setattr(
        _fleet_service.store,
        "list_agent_sessions",
        lambda: [
            {"key": "agent/R", "saved_at": "2026-07-09T12:00:00",
             "status": {"state": "finished"}, "turn_count": 3},
            {"key": "agent/W", "saved_at": "2026-07-05T00:00:00",
             "status": {"state": "awaiting_input"}, "turn_count": 3},
        ],
    )

    nodes = _fleet_service._agent_tree_uncached()["nodes"]
    # W (awaiting_input, saved_at plus ancien) flotte au-dessus de R (plus récent).
    assert nodes[0]["agent_id"] == "W"
    assert nodes[1]["agent_id"] == "R"
