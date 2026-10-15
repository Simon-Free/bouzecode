"""Le qualificateur d'erreur API ne doit JAMAIS masquer l'exception d'origine.

Constate le 2026-08-24 : le handler `except BaseException` de loop.run commencait
par `import anthropic`. Quand ce module etait indisponible (venv casse, autre
provider), le ModuleNotFoundError du handler REMPLACAIT l'exception reelle et
envoyait le diagnostic sur une fausse piste.

Ici on rend `anthropic` volontairement inimportable (meta_path finder actif, pas
de mock) et on verifie que l'exception initiale du stream survit intacte.
"""

from __future__ import annotations

import sys

import pytest

from bouzecode.backend.agent.loop import run
from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.agent.stream_interceptor import set_stream_interceptor


class _BlockAnthropic:
    """Rend tout import de `anthropic` impossible, comme un venv incomplet."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "anthropic" or fullname.startswith("anthropic."):
            raise ModuleNotFoundError(f"No module named {fullname!r}", name=fullname)
        return None


def _boom_streamer(_raw):
    def _stub(model, system, messages, tool_schemas, config):
        raise RuntimeError("boom original")
        yield  # pragma: no cover -- makes this a generator
    return _stub


def test_original_exception_survives_when_anthropic_is_unavailable():
    blocker = _BlockAnthropic()
    saved_modules = {
        name: mod for name, mod in sys.modules.items()
        if name == "anthropic" or name.startswith("anthropic.")
    }
    for name in saved_modules:
        del sys.modules[name]
    sys.meta_path.insert(0, blocker)
    set_stream_interceptor(_boom_streamer)
    try:
        state = AgentState()
        config = {
            "model": "claude-sonnet-4",
            "task_classification": False,
            "enforce_methodology": False,
            "recover_memory": False,
        }
        with pytest.raises(RuntimeError, match="boom original"):
            list(run("hello", state, config, "SYSTEM", cancel_check=None))
    finally:
        set_stream_interceptor(None)
        sys.meta_path.remove(blocker)
        sys.modules.update(saved_modules)
