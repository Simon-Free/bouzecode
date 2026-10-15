# [desc] Dumps full raw text and stream events of degenerate completions to a JSON diagnostics file, never fatal [/desc]
"""Ce que le modèle a VRAIMENT émis quand un tour part à la poubelle.

Trois incidents consécutifs (2026-09-28, claude-opus-5) se sont fermés sur
« empty completion ... run stopped » sans que personne ne puisse dire ce que le
modèle avait émis : le compteur disait `+9 out`, `+15 out`, `+9 out` — donc des
tokens FACTURÉS — mais ni texte ni appel d'outil n'arrivait jusqu'à la boucle
d'agent. Le warning stderr ne portait qu'un extrait tronqué à 400 caractères,
noyé dans le terminal et perdu au redémarrage suivant. Diagnostiquer revenait à
raisonner par élimination sur des SSE reconstruits de mémoire.

D'où ce module : à chaque complétion jugée dégénérée, UN fichier JSON par
incident sous ``~/.bouzecode/diagnostics/``, dont le chemin est rendu à
l'appelant pour être CITÉ dans le warning. On y met le texte brut INTÉGRAL (et
non l'extrait tronqué remonté sur l'AssistantTurn), ce qui a réellement été
streamé, et la trace des events du stream.

DEUX PARTIS PRIS, tous les deux par expérience :

- AUTOMATIQUE, pas d'opt-in par variable d'environnement. Un dump qu'il faut
  penser à activer n'est jamais actif au moment de l'incident — et un incident
  de ce genre n'est pas reproductible à la demande.
- JAMAIS FATAL. Le diagnostic est un bonus : disque plein, droits, chemin pris
  par un fichier — il renvoie ``None`` et se taît. Il documente une session, il
  ne la tue pas.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from ....core.config import CONFIG_DIR

# Attribut de MODULE, lu à l'intérieur de la fonction : les tests le
# monkeypatchent vers un tmp_path. Le capturer dans une valeur par défaut le
# rendrait impatchable.
DIAGNOSTICS_DIR = CONFIG_DIR / "diagnostics"

# Deux incidents peuvent tomber dans la MÊME seconde (le backend rejoue tout de
# suite). L'horodatage seul ferait s'écraser le second, c'est-à-dire perdre
# précisément la trace qu'on est venu chercher.
_compteur = 0

# Borne du texte conservé par event. Les events sont là pour montrer la FORME du
# stream (quels types, dans quel ordre) ; le contenu intégral, lui, vit dans
# raw_text.
_MAX_EVENT_TEXT = 200


def _serialisable(valeur):
    """Rend n'importe quel objet du SDK écrivable en JSON, sans jamais lever."""
    try:
        json.dumps(valeur)
        return valeur
    except Exception:
        return repr(valeur)[:_MAX_EVENT_TEXT]


def _version_du_code() -> dict:
    from bouzecode.backend.core.code_version import BOOT
    from bouzecode.backend.core.version_session import lire_branche, lire_version_bouzecode
    return {"bouzecode_version": lire_version_bouzecode(),
            "bouzecode_boot_commit": BOOT.boot_sha, "bouzecode_branche": lire_branche()}


def dump_degenerate_completion(*, reason: str, model: str, provider: str,
                               stop_reason, raw_text: str, streamed_text: str,
                               tool_calls, usage, events) -> Path | None:
    """Écrit le diagnostic d'un tour dégénéré, renvoie son chemin (ou None).

    `reason` dit POURQUOI le tour a été jugé dégénéré ("empty" = rien reçu du
    tout, "discarded" = du texte reçu mais entièrement écarté par le protocole)
    — c'est la distinction qui décide s'il faut rejouer ou nudger, donc la
    première chose qu'on veut lire dans le fichier.
    """
    global _compteur
    try:
        dossier = Path(DIAGNOSTICS_DIR)
        dossier.mkdir(parents=True, exist_ok=True)
        _compteur += 1
        nom = (f"completion-{reason}-{time.strftime('%Y%m%d-%H%M%S')}"
               f"-{os.getpid()}-{_compteur}.json")
        chemin = dossier / nom
        record = {
            "reason": reason,
            "timestamp": time.time(),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "model": model,
            "provider": provider,
            # Quel code a produit ce tour : un « malgré un pull » se tranche ici.
            **_version_du_code(),
            "stop_reason": stop_reason,
            # INTÉGRAL, volontairement : c'est la donnée que trois incidents
            # n'ont pas permis de voir.
            "raw_text": raw_text,
            "raw_text_len": len(raw_text or ""),
            "streamed_text": streamed_text,
            "streamed_text_len": len(streamed_text or ""),
            "tool_calls": _serialisable(tool_calls),
            "usage": _serialisable(usage),
            "events": [_serialisable(e) for e in (events or [])],
        }
        chemin.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return chemin
    except Exception:
        # Voir la docstring : un diagnostic ne tue pas la session qu'il documente.
        return None
