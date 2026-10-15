"""Tests: Agent tool (web mode) = long tool call with 2 modes, not a turn end.

No mock.patch: dependencies (dispatch + wait_verdict) are injected via config as
pure in-memory fakes, exactly the seam the production code exposes.
"""
from bouzecode.backend.multi_agent.lancement_web import _spawn_web_ticket_agent
from bouzecode.backend.agent.loop_turn import _bg_agent_keeps_turn_open


def _fake_dispatch(result):
    """Return a dispatch callable recording the bodies it received."""
    calls = []

    def dispatch(body):
        calls.append(body)
        return result

    dispatch.calls = calls
    return dispatch


def _fake_wait(verdict):
    calls = []

    def wait_verdict(ticket_id, project_slug):
        calls.append((ticket_id, project_slug))
        return verdict

    wait_verdict.calls = calls
    return wait_verdict


ROUTED = {"routed": True, "ticket_id": "T42", "project_name": "demo", "typology": "feature",
          "project_slug": "demo-slug"}


# ---- Mode BACKGROUND (explicit) -------------------------------------------

def test_background_true_returns_immediately():
    dispatch = _fake_dispatch(ROUTED)
    wait_verdict = _fake_wait("SHOULD NOT BE CALLED")
    config = {"_web_dispatch": dispatch, "_web_wait_verdict": wait_verdict}

    msg = _spawn_web_ticket_agent({"prompt": "do X", "background": True}, config)

    assert len(dispatch.calls) == 1
    assert dispatch.calls[0]["prompt"] == "do X"
    assert dispatch.calls[0]["defer"] is True
    # wait_verdict MUST NOT run in background
    assert wait_verdict.calls == []
    # the manager is invited to keep going THIS turn
    assert "EN FOND" in msg
    assert "CE MÊME TOUR" in msg
    assert "T42" in msg
    # flag set so the turn-protocol keeps the turn open
    assert config.get("_bg_agent_launched") is True


def test_background_explicit_wait_false():
    dispatch = _fake_dispatch(ROUTED)
    wait_verdict = _fake_wait("nope")
    config = {"_web_dispatch": dispatch, "_web_wait_verdict": wait_verdict}

    _spawn_web_ticket_agent({"prompt": "p", "wait": False}, config)

    assert wait_verdict.calls == []
    assert config.get("_bg_agent_launched") is True


# ---- Mode wait=True --------------------------------------------------------

def test_wait_true_blocks_and_returns_verdict():
    dispatch = _fake_dispatch(ROUTED)
    wait_verdict = _fake_wait("VERDICT: OK — child finished")
    config = {"_web_dispatch": dispatch, "_web_wait_verdict": wait_verdict}

    msg = _spawn_web_ticket_agent({"prompt": "p", "wait": True}, config)

    assert wait_verdict.calls == [("T42", "demo-slug")]
    assert "VERDICT: OK — child finished" in msg
    assert "Verdict de l'enfant" in msg
    # in wait mode we do NOT keep the turn artificially open
    assert config.get("_bg_agent_launched") is not True


# ---- Dispatch error paths --------------------------------------------------

def test_projet_requis_message():
    """Projet indéterminé → ERREUR d'outil, pas un compte rendu qu'on relit comme un succès."""
    dispatch = _fake_dispatch({"routed": False, "code": "projet_requis"})
    config = {"_web_dispatch": dispatch, "_web_wait_verdict": _fake_wait("x")}

    msg = _spawn_web_ticket_agent({"prompt": "p"}, config)

    assert msg.startswith("Error:")
    assert "aucun enfant n'a été créé" in msg
    assert config.get("_bg_agent_launched") is not True


def test_not_routed_message():
    """Dispatch non routé → ERREUR d'outil, et la réponse serveur reste lisible."""
    dispatch = _fake_dispatch({"routed": False, "error": "boom"})
    config = {"_web_dispatch": dispatch, "_web_wait_verdict": _fake_wait("x")}

    msg = _spawn_web_ticket_agent({"prompt": "p"}, config)

    assert msg.startswith("Error:")
    assert "boom" in msg
    assert config.get("_bg_agent_launched") is not True


# ---- Turn-protocol neutralisation -----------------------------------------

def test_bg_flag_keeps_turn_open_without_final_answer():
    config = {"_bg_agent_launched": True}
    tool_calls = [{"name": "Agent"}, {"name": "Bash"}]

    assert _bg_agent_keeps_turn_open(config, tool_calls) is True
    # flag is consumed (reset each turn)
    assert "_bg_agent_launched" not in config


def test_bg_flag_honors_explicit_final_answer():
    config = {"_bg_agent_launched": True}
    tool_calls = [{"name": "Agent"}, {"name": "FinalAnswer"}]

    # explicit FinalAnswer is always honored -> do not force CONTINUE
    assert _bg_agent_keeps_turn_open(config, tool_calls) is False
    # flag still consumed
    assert "_bg_agent_launched" not in config


def test_no_bg_flag_is_noop():
    config = {}
    assert _bg_agent_keeps_turn_open(config, [{"name": "FinalAnswer"}]) is False
    assert _bg_agent_keeps_turn_open(config, []) is False
