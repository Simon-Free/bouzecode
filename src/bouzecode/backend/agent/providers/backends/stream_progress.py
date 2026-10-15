# [desc] Progress watchdog for SSE streams: aborts an attempt that keeps the socket alive without producing anything. [/desc]
"""Chien de garde de PROGRÈS sur un flux SSE (route chat/completions).

Le délai de lecture de requests ne mesure que le silence entre deux octets : des keep-alive
(lignes vides, commentaires `:`) ou des chunks sans delta le réarment indéfiniment. Mesuré le
2026-10-05 (agent 9f14d1810dd5, tour 35, claude-opus-5-5 via gateway_preprod) : flux ouvert 296 s
sans un token, puis un chunk `503 BedrockException` — 322 s pour un tour de 5 à 14 s, et le
cache de préfixe (TTL 5 min) expiré au moment de la relance.

Le chien de garde, lui, ne se réarme que sur un progrès UTILE : delta de contenu, de
reasoning, de refus, de tool_call, ou usage. Sans progrès pendant le délai, il lève
StreamNoProgress, que la boucle de lecture traite comme une erreur en plein flux (relance,
StreamRestart). Délais : 60 s avant le premier progrès (ingestion du prompt ; nos prompts
dépassent rarement 100 k tokens), puis 15 s entre deux progrès : une fois le flux lancé,
thinking, texte et tool_call arrivent en continu, un silence de 15 s est un vrai blocage
qu'il vaut mieux relancer tôt (décision du 2026-10-12, au lieu de 120/90 s). Ils restent
sous le filet consommateur de loop_turn (300 s).

Réglage, dans l'ordre de priorité (style de registry.py : la variable d'environnement tranche) :
BOUZECODE_STREAM_FIRST_PROGRESS_TIMEOUT_S / BOUZECODE_STREAM_PROGRESS_TIMEOUT_S, puis les clés
de config `stream_first_progress_timeout_s` / `stream_progress_timeout_s`, puis les défauts.
Une valeur non numérique ou <= 0 est ignorée."""
from __future__ import annotations
import os
import time

from .openrouter_retry import UpstreamStreamError

FIRST_PROGRESS_TIMEOUT_S = 60.0
PROGRESS_TIMEOUT_S = 15.0
FIRST_PROGRESS_ENV = "BOUZECODE_STREAM_FIRST_PROGRESS_TIMEOUT_S"
PROGRESS_ENV = "BOUZECODE_STREAM_PROGRESS_TIMEOUT_S"

_PROGRESS_DELTA_KEYS = ("content", "reasoning", "refusal", "tool_calls")


class StreamNoProgress(UpstreamStreamError):
    """Flux vivant (keep-alive, chunks vides) mais sans aucun progrès pendant le délai."""


def _positive_seconds(raw) -> float | None:
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def _resolve_seconds(env_name: str, config_key: str, config: dict, default: float) -> float:
    for candidate in (os.environ.get(env_name), config.get(config_key)):
        seconds = _positive_seconds(candidate)
        if seconds is not None:
            return seconds
    return default


def progress_timeouts(config: dict) -> tuple[float, float]:
    """``(avant le premier progrès, entre deux progrès)`` en secondes."""
    return (
        _resolve_seconds(FIRST_PROGRESS_ENV, "stream_first_progress_timeout_s", config,
                         FIRST_PROGRESS_TIMEOUT_S),
        _resolve_seconds(PROGRESS_ENV, "stream_progress_timeout_s", config, PROGRESS_TIMEOUT_S),
    )


def chunk_makes_progress(chunk: dict) -> bool:
    """Le chunk apporte-t-il quelque chose au tour (et pas seulement un signe de vie) ?"""
    if chunk.get("usage"):
        return True
    choices = chunk.get("choices") or []
    delta = (choices[0].get("delta") or {}) if choices else {}
    return any(delta.get(key) for key in _PROGRESS_DELTA_KEYS)


class ProgressWatchdog:
    """Échéance réarmée par `progress()`, contrôlée par `check()` à chaque ligne lue."""

    def __init__(self, first_timeout_s: float, idle_timeout_s: float, clock=time.monotonic):
        self.first_timeout_s = first_timeout_s
        self.idle_timeout_s = idle_timeout_s
        self._clock = clock
        self._last_progress_at = clock()
        self._got_progress = False

    def progress(self) -> None:
        self._got_progress = True
        self._last_progress_at = self._clock()

    def check(self) -> None:
        limit = self.idle_timeout_s if self._got_progress else self.first_timeout_s
        silent_for = self._clock() - self._last_progress_at
        if silent_for > limit:
            phase = "between two progress events" if self._got_progress else "before the first token"
            raise StreamNoProgress(f"no stream progress for {silent_for:.0f}s {phase} "
                                   f"(limit {limit:.0f}s)")
