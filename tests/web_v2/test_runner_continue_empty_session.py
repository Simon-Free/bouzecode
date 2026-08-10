# [desc] Garde anti-clobber : continue_agent sur une session JAMAIS persistée (agent mort
# au boot avant d'avoir sauvé son 1er tour) ne doit PAS injecter le message reçu sur du vide
# — sinon --resume-from repart d'une session vide et le prompt du ticket est perdu. Il rejoue
# le prompt d'ORIGINE. Sur une session avec au moins un tour, il continue normalement. [/desc]
from __future__ import annotations

import json

from bouzecode.web_v2.runtime import runner


def _agent(session_path: str, prompt: str = "Fais-moi un plan de modifications") -> runner.Agent:
    return runner.Agent(
        agent_id="deadbeef0001",
        prompt=prompt,
        model="",
        cwd="",
        pid=0,
        started_at="2026-07-08T13:45:50Z",
        session_path=session_path,
        stdout_path="",
        ipc_dir="",
    )


def _capture_respawn(monkeypatch) -> dict:
    """Remplace _respawn par un capteur (aucun subprocess) qui note extra_args."""
    captured: dict = {}

    def fake_respawn(agent, extra_args, banner, model=""):
        captured["extra_args"] = extra_args
        captured["banner"] = banner
        return agent

    monkeypatch.setattr(runner, "_respawn", fake_respawn)
    return captured


def test_session_has_persisted_turn(tmp_path):
    absent = tmp_path / "absent.json"
    assert runner._session_has_persisted_turn(str(absent)) is False

    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")
    assert runner._session_has_persisted_turn(str(empty)) is False

    no_msgs = tmp_path / "no_msgs.json"
    no_msgs.write_text(json.dumps({"messages": []}), encoding="utf-8")
    assert runner._session_has_persisted_turn(str(no_msgs)) is False

    with_turn = tmp_path / "with_turn.json"
    with_turn.write_text(json.dumps({"messages": [{"role": "user", "content": "x"}]}),
                         encoding="utf-8")
    assert runner._session_has_persisted_turn(str(with_turn)) is True


def test_continue_on_absent_session_reruns_original_prompt(monkeypatch, tmp_path):
    captured = _capture_respawn(monkeypatch)
    agent = _agent(str(tmp_path / "never_saved.session.json"))

    runner.continue_agent(agent, "continue stp")

    # Le message « continue stp » ne doit PAS clobber : on rejoue le prompt du ticket.
    assert captured["extra_args"] == ["Fais-moi un plan de modifications"]
    assert "continue stp" not in captured["banner"]


def test_continue_on_empty_file_reruns_original_prompt(monkeypatch, tmp_path):
    captured = _capture_respawn(monkeypatch)
    session = tmp_path / "empty.session.json"
    session.write_text(json.dumps({"messages": []}), encoding="utf-8")
    agent = _agent(str(session))

    runner.continue_agent(agent, "continue stp")

    assert captured["extra_args"] == ["Fais-moi un plan de modifications"]


def test_continue_on_persisted_session_uses_given_text(monkeypatch, tmp_path):
    captured = _capture_respawn(monkeypatch)
    session = tmp_path / "live.session.json"
    session.write_text(json.dumps({"messages": [{"role": "user", "content": "hi"},
                                                {"role": "assistant", "content": "ok"}]}),
                       encoding="utf-8")
    agent = _agent(str(session))

    runner.continue_agent(agent, "fais plutôt X")

    # Session réelle → le message utilisateur est bien transmis tel quel.
    assert captured["extra_args"] == ["fais plutôt X"]


def test_continue_empty_prompt_on_persisted_uses_resume_prompt(monkeypatch, tmp_path):
    # Bouton « Reprendre » (POST {text:""}) sur une session AVEC tours : passer "" au CLI
    # (-p ... --resume-from <s> "") faisait sys.exit(1) (cli.py guard prompt vide) → l'agent
    # « ne reprenait rien ». On substitue un prompt de reprise NON VIDE.
    captured = _capture_respawn(monkeypatch)
    session = tmp_path / "live.session.json"
    session.write_text(json.dumps({"messages": [{"role": "user", "content": "hi"},
                                                {"role": "assistant", "content": "ok"}]}),
                       encoding="utf-8")
    agent = _agent(str(session))

    runner.continue_agent(agent, "")

    assert captured["extra_args"] == [runner.RESUME_PROMPT]
    assert captured["extra_args"][0] != ""
