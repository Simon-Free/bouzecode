# [desc] Tests that enforcement recovery crashes (methodology/snippet) don't kill the session. [/desc]
"""Regression for the live crash of 2026-06-09 (session_234238): an OpenRouter
429→400 raised inside recover_snippets propagated through loop.run and killed
the whole session. Recovery side-calls are best-effort."""
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM
from bouzecode.backend.agent import enforcement_call
from bouzecode.backend.agent.loop_detector import RecoveryFailed

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
BASH = '<tool_use name="Bash" id="b1"><param name="command">echo travail</param></tool_use>'
RECOVER = {"recover_memory": True, "test_enforcement": False}


def test_methodology_recovery_crash_does_not_kill_session(monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("OpenRouter request failed: HTTP 400")
    monkeypatch.setattr(enforcement_call, "recover_methodology", _boom)

    mock = MockLLM([
        BASH,              # no Methodology → recovery fires and crashes
        f"fini.\n{METH}",
    ])
    result = bouzecode(["fais la tâche"], mock_llm=mock, config_overrides=RECOVER)

    bash_results = [m for m in result.messages
                    if m.get("role") == "tool" and m.get("name") == "Bash"]
    assert bash_results, "the work batch must still execute after the failed side-call"
    assert any(isinstance(e, RecoveryFailed) and e.tool == "Methodology"
               for e in result.events), "a visible RecoveryFailed event must be emitted"


def test_snippet_recovery_crash_does_not_kill_session(monkeypatch, tmp_path):
    f = tmp_path / "test_lu.py"
    # File must be >= SNIPPET_MIN_LINES to trigger snippet recovery
    big_content = "\n".join(f"line {i}" for i in range(60))
    f.write_text(big_content, encoding="utf-8")
    target = str(f).replace("\\", "/")

    def _boom(*_a, **_k):
        raise RuntimeError("OpenRouter request failed: HTTP 429")
    monkeypatch.setattr(enforcement_call, "recover_snippets", _boom)

    read = (f'<tool_use name="Read" id="r1">'
            f'<param name="file_path">{target}</param></tool_use>')
    mock = MockLLM([
        f"{METH}\n{read}",        # Read leaves an unsnippeted result
        f"{METH}\n{BASH}",        # next turn: snippet recovery fires and crashes
        f"fini.\n{METH}",
    ])
    result = bouzecode(["lis le fichier"], mock_llm=mock, config_overrides=RECOVER)

    assert any(isinstance(e, RecoveryFailed) and e.tool == "Snippet"
               for e in result.events)
    closing = [m for m in result.messages
               if m.get("role") == "assistant" and "fini." in str(m.get("content", ""))]
    assert closing, "the session must reach its normal end"
