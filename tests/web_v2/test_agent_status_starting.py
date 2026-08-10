"""FIX 5a — agent_status ne doit PAS confondre 'jamais démarré' et 'finished'.

Un agent tout juste créé (worktree provisionné, subprocess pas encore lancé) a
returncode=None ET aucune session écrite. Avant le fix il tombait dans la branche
`else -> 'finished'`, ouvrant la FENÊTRE DE START qui déclenchait un validateur
prématuré sur worktree vide (no_diff verrouillé). Il doit être vu 'starting'.
"""
from pathlib import Path

from bouzecode.web_v2.services.sessions import store


class _FakeAgent:
    """Doit porter les MÊMES champs que `runner.Agent`, pas seulement ceux que le test lit.

    `store.agent_status` consulte désormais `runner.is_warm(agent)`, qui lit `pid` et
    `ipc_dir` — deux champs que le vrai `Agent` a TOUJOURS. Le faux ne les avait pas, et
    l'AttributeError qui en résultait ne disait rien du produit : elle disait que le double
    n'était plus un double.
    """

    def __init__(self, agent_id="agent01starting", returncode=None, session_path="",
                 pid=0, ipc_dir=""):
        self.agent_id = agent_id
        self.returncode = returncode
        self.session_path = session_path
        self.pid = pid
        self.ipc_dir = ipc_dir


def _wire(monkeypatch, *, running, ipc=None):
    monkeypatch.setattr(store.runner, "refresh_agent_status", lambda a: a)
    monkeypatch.setattr(store.runner, "get_ipc_state", lambda a: ipc or {})
    monkeypatch.setattr(store.runner, "is_running", lambda a: running)
    # neutraliser le cache mémoire pour un test déterministe
    store._status_cache.clear()


def test_never_started_is_starting_not_finished(monkeypatch, tmp_path):
    """returncode None + session inexistante + pas vivant → 'starting' (pas 'finished')."""
    _wire(monkeypatch, running=False)
    missing = str(tmp_path / "nope.session.json")
    agent = _FakeAgent(returncode=None, session_path=missing)

    assert store.agent_status(agent)["state"] == "starting"


def test_finished_agent_stays_finished(monkeypatch, tmp_path):
    """Contre-cas (non-régression) : un vrai agent fini (returncode défini) → 'finished'."""
    _wire(monkeypatch, running=False)
    agent = _FakeAgent(returncode=0, session_path=str(tmp_path / "nope.session.json"))

    assert store.agent_status(agent)["state"] == "finished"


def test_finished_when_session_written(monkeypatch, tmp_path):
    """Pas vivant mais session écrite → 'finished' (a réellement tourné)."""
    _wire(monkeypatch, running=False)
    sess = tmp_path / "done.session.json"
    sess.write_text("[]", encoding="utf-8")
    agent = _FakeAgent(returncode=None, session_path=str(sess))

    assert store.agent_status(agent)["state"] == "finished"


def test_running_without_session_is_starting(monkeypatch, tmp_path):
    """Vivant mais session pas encore écrite → 'starting' (comportement existant préservé)."""
    _wire(monkeypatch, running=True)
    agent = _FakeAgent(returncode=None, session_path=str(tmp_path / "nope.session.json"))

    assert store.agent_status(agent)["state"] == "starting"


def test_running_with_session_is_running(monkeypatch, tmp_path):
    """Vivant + session écrite → 'running'."""
    _wire(monkeypatch, running=True)
    sess = tmp_path / "live.session.json"
    sess.write_text("[]", encoding="utf-8")
    agent = _FakeAgent(returncode=None, session_path=str(sess))

    assert store.agent_status(agent)["state"] == "running"
