# [desc] Blueprint `sessions_api` : sessions et conversations (liste, rangement, blocs du fil, analyse des tours, vues lisibles, file de messages d'un agent). Un module par domaine, tous LECTURE PURE sauf le rangement. [/desc]
"""`/blocks` est l'unique endpoint de polling du fil (nouveaux blocs + statut + méta) ;
`?plain=1` y renvoie du texte structuré (consommation par un LLM) au lieu du HTML.

Toute erreur sort à la forme unique `{"error": {"code", "message", "details"?}}` (spec §9)."""
from __future__ import annotations

from flask import Blueprint

#  Ré-exporté : des tests remplacent `sessions.store.resolve`.
from ...services.sessions import store  # noqa: F401

sessions_bp = Blueprint("sessions_api", __name__)

#  Les modules enregistrent leurs routes sur `sessions_bp` à l'import.
from . import analyse, blocs, conversations, fichiers, liste, vues  # noqa: E402,F401
