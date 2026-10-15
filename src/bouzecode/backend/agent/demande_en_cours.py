# [desc] Remet la demande utilisateur en cours en tête du fil d'un tour d'agent : « [MESSAGE USER EN COURS]: … ». [/desc]
"""La demande de l'utilisateur, en premier message du fil.

Le fil minimal (`build_minimal_payload`) ne garde que le dernier lot : passé le tour 1, la
demande n'existe plus que dans la note Methodology du system, et le fil commence par un
assistant « . » suivi de résultats d'outils. Mesuré le 2026-10-05 sur la préprod du gateway
(claude-opus-5-5, session 0a3ed5c5 tour 13) : 12/12 refus `content_filter` sans message user
en tête, 0/12 avec la demande remise en premier. L'API Anthropic exige d'ailleurs un premier
message `user`.

On AJOUTE : la demande reste aussi dans la note (bloc `## User @…`). Ce message suit la note,
qui change à chaque tour : il est donc relu en tokens frais à chaque tour. On le tronque à
`LONGUEUR_MAX_DEMANDE` caractères — le texte complet est dans la note, et la même mesure
(préprod, 2026-10-05) donne 0/12 refus avec la demande tronquée à 100 caractères.
"""
from __future__ import annotations

import re

PREFIXE = "[MESSAGE USER EN COURS]: "

# Au-delà, la demande remise en tête est coupée et suivie de « … ».
LONGUEUR_MAX_DEMANDE = 100

# Posé sur le message que l'utilisateur a réellement tapé (`loop.run`), pour le distinguer des
# relances du harnais, qui sont aussi des messages `user`.
DEMANDE_UTILISATEUR = "_demande_utilisateur"

# Repli pour une session antérieure au marquage : le dernier bloc `## User` de la note. Coupe
# au premier titre `## ` interne à la demande — même limite que `methodology._USER_BLOCK_RE`.
_BLOC_USER = re.compile(r"^## User(?:\s+@[^\n]*)?\n(.*?)(?=\n## |\Z)", re.DOTALL | re.MULTILINE)


def _texte(content) -> str:
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return content or ""


def _derniere_demande_de_la_note(state) -> str:
    from ..context_manager.state import METHODOLOGY_NOTE
    notes = getattr(getattr(state, "context_state", None), "notes", None) or {}
    blocs = _BLOC_USER.findall(notes.get(METHODOLOGY_NOTE, "") or "")
    return blocs[-1].strip() if blocs else ""


def demande_en_cours(state) -> str:
    """Le dernier message tapé par l'utilisateur ; à défaut, le dernier `## User` de la note."""
    for message in reversed(state.messages):
        if message.get("role") == "user" and message.get(DEMANDE_UTILISATEUR):
            return _texte(message.get("content")).strip()
    return _derniere_demande_de_la_note(state)


def demande_abregee(demande: str) -> str:
    """Les `LONGUEUR_MAX_DEMANDE` premiers caractères de la demande, suivis de « … » si coupée."""
    demande = demande.strip()
    if len(demande) <= LONGUEUR_MAX_DEMANDE:
        return demande
    return demande[:LONGUEUR_MAX_DEMANDE] + "…"


def mettre_la_demande_en_tete(fil: list[dict], demande: str) -> list[dict]:
    """Le fil, précédé de la demande — sauf s'il commence déjà par elle (tour 1)."""
    if not demande:
        return fil
    if fil and fil[0].get("role") == "user" and (
            fil[0].get(DEMANDE_UTILISATEUR) or _texte(fil[0].get("content")).strip() == demande):
        return fil
    return [{"role": "user", "content": PREFIXE + demande_abregee(demande)}, *fil]
