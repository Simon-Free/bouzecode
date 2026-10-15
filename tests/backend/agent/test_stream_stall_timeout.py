"""Un provider MUET ne doit pas geler l'agent pour toujours.

Session reelle f10013b4 (agent d116c9422334, ticket b8443349, 26/08 16:31->16:58) : le
`compaction_log` ne porte que 6 `llm_call` pour 9 tours affiches, la session s'arrete avec
`close_reason=''` (aucun chemin de cloture atteint) et l'humain la relance 3 fois a la main,
repayant 34309 puis 10811 tokens de cache_creation. Le garde `empty_completion` (a963a407)
ne pouvait pas s'y declencher : il est POST-stream, et le tour ne revenait jamais du stream.

Le point de passage OBLIGE de tous les backends est `_interruptible_iter` : il consomme la
queue alimentee par le thread qui itere le generateur du provider. Sa boucle
`q.get(timeout=0.2) / except Empty: continue` n'a AUCUNE deadline d'inactivite globale : si
le generateur ne yield plus rien, elle tourne indefiniment et seul un `cancel_check` humain
en sort.

Ce test exerce ce chemin la, sans mock_patch : un vrai generateur qui yield un evenement
puis se tait.
"""
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bouzecode.backend.agent.loop_turn import _interruptible_iter  # noqa: E402


def _consume_in_thread(gen, timeout_s: float = 10.0):
    """Consomme `gen` via _interruptible_iter dans un thread et rend (alive, exc, items).

    Le thread est necessaire : AVANT correctif la boucle est infinie, et la consommer dans
    le thread principal bloquerait toute la suite de tests jusqu'au timeout global.
    """
    out: dict = {"exc": "not-set", "items": []}

    def _run():
        try:
            for item in _interruptible_iter(gen):
                out["items"].append(item)
        except BaseException as exc:  # noqa: BLE001 - on veut la classer dans le test
            out["exc"] = exc
        else:
            out["exc"] = None

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    th.join(timeout=timeout_s)
    return th.is_alive(), out["exc"], out["items"]


def test_silent_provider_raises_stream_stalled_instead_of_hanging(monkeypatch):
    """Provider muet apres un premier evenement -> exception bornee, pas de gel."""
    monkeypatch.setenv("BOUZECODE_STREAM_STALL_TIMEOUT_S", "1")

    release = threading.Event()

    def muet():
        yield "premier-evenement"
        # Le provider se tait : exactement ce que montre la session f10013b4.
        release.wait(60)

    try:
        alive, exc, items = _consume_in_thread(muet(), timeout_s=10.0)
    finally:
        release.set()

    assert not alive, (
        "_interruptible_iter tourne TOUJOURS 10 s apres le dernier evenement du provider : "
        "aucune deadline d'inactivite, l'agent est gele jusqu'a intervention humaine"
    )
    assert items == ["premier-evenement"]
    assert exc is not None, "le stream muet s'est termine sans erreur : rien ne sera signale"
    assert type(exc).__name__ == "StreamStalled", (
        f"exception inattendue: {type(exc).__name__}: {exc}"
    )
    msg = str(exc)
    assert msg.isascii(), f"message non ASCII (illisible dans les journaux Windows): {msg!r}"
    assert "1" in msg, f"le message doit citer le delai depasse, recu: {msg!r}"


def test_stall_timeout_default_is_above_provider_level_deadlines():
    """Le filet de securite ne doit pas court-circuiter les gardes du provider.

    `anthropic_helpers` a deja 180 s sur le premier evenement et 60 s inter-chunk
    (fc04e0c8). Le filet du consommateur doit se declencher APRES eux, sinon il coupe des
    retries legitimes au lieu de rattraper leurs trous.
    """
    from bouzecode.backend.agent import loop_turn

    assert loop_turn.STREAM_STALL_TIMEOUT_S >= 240, loop_turn.STREAM_STALL_TIMEOUT_S


def test_healthy_stream_is_never_interrupted(monkeypatch):
    """Un stream lent mais VIVANT (evenements espaces) passe sans exception."""
    monkeypatch.setenv("BOUZECODE_STREAM_STALL_TIMEOUT_S", "2")

    def lent():
        for i in range(5):
            threading.Event().wait(0.4)  # 0.4 s entre evenements, bien sous les 2 s
            yield f"chunk-{i}"

    alive, exc, items = _consume_in_thread(lent(), timeout_s=15.0)

    assert not alive
    assert exc is None, f"un stream vivant a ete interrompu: {type(exc).__name__}: {exc}"
    assert items == [f"chunk-{i}" for i in range(5)]


def test_env_override_is_read_at_call_time(monkeypatch):
    """La valeur est lue a l'appel (pas figee a l'import) : testable et reglable a chaud."""
    monkeypatch.setenv("BOUZECODE_STREAM_STALL_TIMEOUT_S", "1")
    from bouzecode.backend.agent import loop_turn

    assert loop_turn._stall_timeout_s() == 1.0
    monkeypatch.delenv("BOUZECODE_STREAM_STALL_TIMEOUT_S", raising=False)
    assert loop_turn._stall_timeout_s() == loop_turn.STREAM_STALL_TIMEOUT_S
    assert os.environ.get("BOUZECODE_STREAM_STALL_TIMEOUT_S") is None
