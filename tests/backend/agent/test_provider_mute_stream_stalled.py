"""Un provider qui se TAIT en vol doit arreter l'agent avec une cause LISIBLE.

Cas reel reproduit (agent d116c9422334, 26/08, 1,06 USD pour rien) : le stream du
provider cesse d'emettre au milieu d'un tour, sans erreur ni fin de flux. Le
consommateur `_interruptible_iter` bouclait alors sans deadline : le tour ne revenait
JAMAIS, donc aucun garde-fou post-stream (empty_completion & co) ne pouvait s'appliquer,
et la session mourait avec `close_reason=''` — une mort silencieuse que seul un humain
pouvait constater, en relancant a la main.

Le mutisme est injecte AU NIVEAU DU PROVIDER : on remplace `loop_turn.stream`, la
fonction meme que le backend Anthropic fournit (c'est le point d'injection utilise par
le harness e2e), pas une source factice posee au-dessus de la boucle.

Ce test est autonome plutot que bati sur `e2e_harness.bouzecode()` : quand le tour leve,
`bouzecode()` laisse remonter l'exception et ne rend donc jamais son `ConversationResult`
— or c'est precisement `state.close_reason` qu'il faut inspecter ici. On reutilise en
revanche SES symboles (load_config/AgentState/run) et SES patches.
"""
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import e2e_harness as h  # noqa: E402
import fake_llm  # noqa: E402
from fake_llm import MockLLM  # noqa: E402

# Tour 1 : productif. La Methodology satisfait l'enforcement, et le Bash produit un
# batch de tool_results — c'est ce batch qui doit SURVIVRE au stall (pas de rasage).
PRODUCTIVE_TURN = (
    "Je commence.\n"
    '<tool_use name="Methodology" id="m1"><param name="content">plan initial</param></tool_use>\n'
    '<tool_use name="Bash" id="b1"><param name="command">echo hello</param></tool_use>'
)


class MuteAfterFirstTurn(MockLLM):
    """Provider normal au 1er tour, puis MUET : il ouvre le stream et n'emet plus rien.

    Aucune exception, aucune fin de generateur : exactement le comportement qui gelait
    le consommateur. `release` libere le generateur en fin de test pour ne pas laisser
    un thread suspendu derriere nous.
    """

    def __init__(self, release: threading.Event):
        super().__init__([PRODUCTIVE_TURN])
        self.release = release
        self.main_calls = 0

    def stream(self, model, system, messages, tool_schemas, config):
        if (config or {}).get("_depth", 0) > 0:
            yield from super().stream(model, system, messages, tool_schemas, config)
            return
        self.main_calls += 1
        if self.main_calls == 1:
            yield from super().stream(model, system, messages, tool_schemas, config)
            return
        # Le stream s'ouvre... et se tait. Pour toujours.
        yield fake_llm.StreamStarted()
        self.release.wait(120)


def _run_muted_agent(stall_s: str, replay_delays: str = "", provider=None):
    """Fait tourner l'agent contre le provider muet. Rend (state, exception, alive).

    `replay_delays` alimente BOUZECODE_STALL_REPLAY_DELAYS_S : vide = aucun rejeu du tour
    (comportement nu du filet), sinon la liste des pauses avant chaque rejeu."""
    import bouzecode.backend.agent.loop_turn as lt

    release = threading.Event()
    if provider is None:
        provider = MuteAfterFirstTurn(release)
    else:
        provider.release = release

    # Pas h.load_config() : il cree CONFIG_DIR, fige a l'import sur le HOME du worker
    # (config.py L8/L93), ce que la garde d'etancheite du HOME refuse.
    import copy
    from bouzecode.backend.core.config import DEFAULTS
    config = copy.deepcopy(DEFAULTS)
    config["permission_mode"] = "accept-all"
    config["verbose"] = False
    config["task_classification"] = False
    config["close_validation"] = False
    import tempfile
    config["_cwd"] = tempfile.mkdtemp(prefix="bouzecode_stall_")

    def _fake_exec(level, results, durations, config):
        for tc in level:
            results[tc["id"]] = f"[{tc['name']} executed]"
            durations[tc["id"]] = 0.001

    saved = {
        "stream": lt.stream,
        "get_tool_schemas": lt.get_tool_schemas,
        "is_web_ipc_active": lt.is_web_ipc_active,
        "_execute_level": lt._execute_level,
        "_check_permission": lt._check_permission,
    }
    prev_env = os.environ.get("BOUZECODE_STREAM_STALL_TIMEOUT_S")
    prev_replay = os.environ.get("BOUZECODE_STALL_REPLAY_DELAYS_S")
    os.environ["BOUZECODE_STALL_REPLAY_DELAYS_S"] = replay_delays

    lt.stream = provider.stream
    lt.get_tool_schemas = lambda *_a, **_k: []
    lt.is_web_ipc_active = lambda: False
    lt._execute_level = _fake_exec
    lt._check_permission = lambda tc, c: True
    os.environ["BOUZECODE_STREAM_STALL_TIMEOUT_S"] = stall_s

    state = h.AgentState()
    box: dict = {}

    def _drain():
        try:
            for _ev in h.run("fais le travail", state, config, "You are a helpful assistant."):
                pass
        except BaseException as exc:  # noqa: BLE001 — on veut le type exact
            box["exc"] = exc

    worker = threading.Thread(target=_drain, daemon=True)
    worker.start()
    # Large devant le stall de 2 s : si le thread vit encore, c'est un GEL, pas de la lenteur.
    worker.join(timeout=30)
    alive = worker.is_alive()

    release.set()
    for name, val in saved.items():
        setattr(lt, name, val)
    if prev_env is None:
        os.environ.pop("BOUZECODE_STREAM_STALL_TIMEOUT_S", None)
    else:
        os.environ["BOUZECODE_STREAM_STALL_TIMEOUT_S"] = prev_env
    if prev_replay is None:
        os.environ.pop("BOUZECODE_STALL_REPLAY_DELAYS_S", None)
    else:
        os.environ["BOUZECODE_STALL_REPLAY_DELAYS_S"] = prev_replay

    return state, box.get("exc"), alive, provider


def test_mute_provider_stops_the_agent_instead_of_hanging_forever():
    from bouzecode.backend.agent.loop_turn import StreamStalled

    state, exc, alive, provider = _run_muted_agent("2")

    assert not alive, (
        "l'agent tourne TOUJOURS 30 s apres que le provider s'est tu : "
        "c'est le gel infini du consommateur de stream"
    )
    assert isinstance(exc, StreamStalled), (
        f"le mutisme du provider doit remonter comme StreamStalled, recu: {exc!r}"
    )
    # Le tour 1 a bien eu lieu : ce n'est pas un echec au premier appel.
    assert provider.main_calls == 2, provider.main_calls


def test_mute_provider_records_an_explicit_cause_of_death():
    """Une session tuee par un provider muet ne doit plus mourir avec close_reason=''."""
    state, exc, alive, _provider = _run_muted_agent("2")

    assert not alive
    assert state.close_reason == "stream_stalled", (
        f"cause de mort non enregistree (symptome de la session reelle): "
        f"close_reason={state.close_reason!r}"
    )
    detail = state.close_detail or ""
    assert detail.strip(), "close_detail vide : le journal ne dit pas POURQUOI ca s'est arrete"
    assert "stall" in detail.lower(), detail


def test_stall_does_not_wipe_the_context():
    """Un hoquet de stream ne doit JAMAIS raser le contexte deja construit."""
    state, _exc, alive, _provider = _run_muted_agent("2")

    assert not alive
    payload = state.last_api_payload or []
    assert len(payload) >= 2, f"contexte rase: {len(payload)} message(s) dans le dernier payload"

    def _has_tool_result(msg):
        if msg.get("role") == "tool":
            return True
        content = msg.get("content")
        if isinstance(content, list):
            return any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content
            )
        return False

    assert any(_has_tool_result(m) for m in payload), (
        "les tool_results du tour productif ont disparu du dernier payload : "
        "le contexte a ete rase au lieu d'etre conserve"
    )


def test_stall_is_a_declared_close_reason():
    """Tout close_reason produit par la boucle doit exister dans la table web_v2."""
    from bouzecode.web_v2.close_reasons import CLOSURES

    assert "stream_stalled" in CLOSURES
    closure = CLOSURES["stream_stalled"]
    # Mort en vol : rien n'est livre, le ticket n'avance pas, et ce n'est PAS la boucle
    # qui a choisi de couper -> un tel run doit pouvoir etre relance.
    assert closure.proves_delivery is False
    assert closure.controlled is False
