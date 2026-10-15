"""Un stream muet UNE fois ne doit plus tuer la session : la boucle rejoue le tour.

Cas reel (session 69fae8479e09 « dax-engine », 2026-10-12) : le gateway preprod n'a
renvoye aucun octet pendant 300 s sur un appel ; le filet de loop_turn a leve
StreamStalled et la session est morte alors qu'un nouvel appel aurait abouti. Un tour
coupe par StreamStalled n'a rien streame d'utile (loop_turn ne relaie l'exception que
dans ce cas) : le rejouer est sans risque.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import fake_llm  # noqa: E402
from fake_llm import MockLLM  # noqa: E402
from test_provider_mute_stream_stalled import PRODUCTIVE_TURN, _run_muted_agent  # noqa: E402


class MuteOnSecondCallOnly(MockLLM):
    """Tour 1 productif, appel 2 muet, puis le provider repond de nouveau."""

    def __init__(self):
        super().__init__([PRODUCTIVE_TURN, "Travail termine."])
        self.release = None
        self.main_calls = 0

    def stream(self, model, system, messages, tool_schemas, config):
        if (config or {}).get("_depth", 0) > 0:
            yield from super().stream(model, system, messages, tool_schemas, config)
            return
        self.main_calls += 1
        if self.main_calls == 2:
            yield fake_llm.StreamStarted()
            self.release.wait(120)
            return
        yield from super().stream(model, system, messages, tool_schemas, config)


def test_single_stall_is_replayed_and_the_session_survives():
    from bouzecode.backend.agent.loop_turn import StreamStalled

    provider = MuteOnSecondCallOnly()
    state, exc, alive, provider = _run_muted_agent("2", replay_delays="0", provider=provider)

    assert not alive
    assert not isinstance(exc, StreamStalled), (
        f"un seul silence du provider a tue la session au lieu d'etre rejoue: {exc!r}"
    )
    assert state.close_reason != "stream_stalled", state.close_reason
    assert provider.main_calls >= 3, provider.main_calls


def test_replays_are_bounded_then_the_stall_surfaces():
    """Provider definitivement muet : on rejoue N fois, puis StreamStalled remonte."""
    from bouzecode.backend.agent.loop_turn import StreamStalled

    state, exc, alive, provider = _run_muted_agent("1", replay_delays="0,0")

    assert not alive
    assert isinstance(exc, StreamStalled), repr(exc)
    assert state.close_reason == "stream_stalled"
    # 1 tour productif + 1 appel muet + 2 rejeux muets.
    assert provider.main_calls == 4, provider.main_calls
