"""pytest progress of a sub-agent goes to its own conversation, not the shared stderr."""
import subprocess
import sys
from types import SimpleNamespace

from bouzecode.backend.multi_agent.en_process.fiche import FicheAgent
from bouzecode.backend.multi_agent.en_process.registre import RegistreAgents
from bouzecode.backend.tools.ops.test_runner import _stream_with_progress
from bouzecode.backend.tools.registration import _progression_sous_agent

_PYTEST_OUTPUT = (
    "collected 3 items\n"
    "tests/test_a.py::test_one PASSED\n"
    "tests/test_a.py::test_two FAILED\n"
    "tests/test_a.py::test_three SKIPPED\n"
)


def _proc():
    script = f"import sys; sys.stdout.write({_PYTEST_OUTPUT!r})"
    return subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8")


def test_progress_callback_replaces_tqdm_on_stderr(capsys):
    recu = []
    lines, timed_out = _stream_with_progress(_proc(), 30, progression=recu.append)
    assert not timed_out
    assert len(lines) == 4
    assert recu, "the callback must receive the progress"
    assert "3/3" in recu[-1] and "✅1" in recu[-1] and "❌1" in recu[-1] and "⏭1" in recu[-1]
    assert "pytest" not in capsys.readouterr().err  # no tqdm bar in the main terminal


def _registre_avec_sous_agent():
    registre = RegistreAgents()
    registre.ajouter(FicheAgent(id="a1", state=SimpleNamespace(messages=[])))
    return registre


def test_sub_agent_config_routes_progress_to_its_fiche():
    registre = _registre_avec_sous_agent()
    callback = _progression_sous_agent({"_tui_agents": registre, "_tui_moi": "a1"})
    _stream_with_progress(_proc(), 30, progression=callback)
    assert "3/3" in registre.fiche("a1").progression


def test_main_agent_keeps_no_callback():
    assert _progression_sous_agent({}) is None
    assert _progression_sous_agent(None) is None
    assert _progression_sous_agent({"_tui_agents": RegistreAgents()}) is None
