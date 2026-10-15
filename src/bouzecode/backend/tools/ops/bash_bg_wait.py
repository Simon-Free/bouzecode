# [desc] BashOutput wait: block until new output, process exit, or a capped delay. [/desc]
"""Mesuré le 2026-10-05 (session 29b001ff) : un script de 3 min lancé en fond, relu par
BashOutput à chaque tour — 25 appels LLM sur 47 n'ont servi qu'à lire « (no new output) ».
`wait_s` fait patienter l'appel lui-même au lieu de le faire patienter par des tours.

Attente par sondage court (time.sleep, 0,5 s) : coupée par KeyboardInterrupt comme la
`communicate(timeout=…)` de Bash, et en plus par la demande d'interruption web
(`config["_cancel_peek"]`, lue sans la consommer, comme aux frontières d'outils de `dag`)."""
import time
from typing import Callable, Optional

MAX_WAIT_S = 600
_POLL_S = 0.5


def borne_attente(wait_s, until_exit: bool) -> int:
    """`wait_s` ramené dans [0, MAX_WAIT_S] ; `until_exit` sans délai = le plafond."""
    wait_s = min(max(int(wait_s or 0), 0), MAX_WAIT_S)
    return MAX_WAIT_S if until_exit and wait_s == 0 else wait_s


def _has_unread_output(entry: dict) -> bool:
    with entry["lock"]:
        return len(entry["buf"]) > entry["offset"]


def wait_for_activity(entry: dict, wait_s: int, until_exit: bool,
                      cancelled: Optional[Callable[[], bool]] = None) -> Optional[str]:
    """Bloque jusqu'à une sortie nouvelle (ignorée si `until_exit`), la fin du process,
    une interruption, ou l'expiration de `wait_s` (déjà borné). Rend une note pour la ligne
    de statut quand l'attente s'est arrêtée sans événement, sinon None."""
    start = time.monotonic()
    deadline = start + wait_s
    while True:
        if entry["proc"].poll() is not None:
            return None
        if not until_exit and _has_unread_output(entry):
            return None
        if cancelled is not None and cancelled():
            return f"attente interrompue après {time.monotonic() - start:.0f} s"
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return f"attendu {wait_s} s, toujours en cours" if wait_s > 0 else None
        time.sleep(min(_POLL_S, remaining))
