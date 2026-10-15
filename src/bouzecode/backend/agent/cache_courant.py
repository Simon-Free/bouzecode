# [desc] Taille du prefixe actuellement en cache chez le fournisseur (cache lu + cache ecrit du DERNIER appel LLM), lue sur l'entree `llm_call` du compaction_log, et son expiration. [/desc]
"""« Cache now » : ce que le prochain appel est cense relire.

Pas un cumul : l'usage du DERNIER appel LLM compte par `loop._account_llm_call`, qui le
journalise deja (avec son horodatage) en entree `llm_call` du `compaction_log`. Cache lu +
cache ecrit = le prefixe relu plus ce qui vient d'y etre depose.

Expiration : le fil de conversation porte un `cache_control` ephemere SANS ttl
(`providers/conversion.py`), donc 5 min chez Anthropic. Seuls les blocs system et la note
passent en 1 h (`dispatch._resolve_cache_control`, API officielle ou BOUZECODE_CACHE_TTL_1H=1) ;
le fil, qui fait l'essentiel du prefixe, expire a 5 min : c'est ce delai qui fait foi.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

TTL_CACHE_FIL_S = 300.0


@dataclass(frozen=True)
class CacheCourant:
    tokens: int
    horodatage: float

    def expire(self, maintenant: float) -> bool:
        return maintenant - self.horodatage > TTL_CACHE_FIL_S


def cache_courant(state) -> Optional[CacheCourant]:
    """None si l'agent n'a fait aucun appel, ou si son dernier appel n'a rien mis en cache."""
    for entree in reversed(getattr(state, "compaction_log", None) or []):
        if entree.get("event") != "llm_call":
            continue
        tokens = int(entree.get("api_cache_read") or 0) + int(entree.get("api_cache_create") or 0)
        if not tokens:
            return None
        return CacheCourant(tokens, float(entree.get("timestamp") or 0.0))
    return None
