# [desc] Flask endpoint that opens a session's or micro-task's declared delivered file with the OS default app. [/desc]
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from flask import current_app, jsonify, request

from ...services.erreurs import Refus
from ...services.sessions import store
from . import sessions_bp

#  Clé de config de l'app : un callable(path: str) -> None. Les tests y injectent un
#  enregistreur pour ne jamais lancer d'application réelle.
CLE_OUVREUR = "BOUZECODE_FILE_OPENER"


def ouvrir_avec_l_os(path: str) -> None:
    """Ouvre `path` avec l'application associée : os.startfile (Windows), open (macOS),
    xdg-open ailleurs. Non bloquant."""
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa: S606 — chemin vérifié contre une livraison déclarée
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])  # noqa: S603,S607
    else:
        subprocess.Popen(["xdg-open", path])  # noqa: S603,S607


def _declares_session(session_id: str) -> list[dict]:
    from ...services.work.taches_vue import related_files_de_session
    ref = store.resolve(session_id)
    data = store.load_session_json(ref.path) if ref is not None else None
    return related_files_de_session(data) if isinstance(data, dict) else []


def _declares_micro(micro_id: str) -> list[dict]:
    from ...services.work import rendu_humain
    try:
        rendu = rendu_humain.dernier(micro_id)
    except Exception:  # micro inconnue : aucune livraison, donc rien de déclaré
        return []
    return list((rendu or {}).get("related_files") or [])


@sessions_bp.post("/api/fichiers/ouvrir")
def api_fichiers_ouvrir():
    """Body {path, session_id | micro_id}. 403 `fichier_non_declare` si le chemin n'est pas
    dans les related_files de la livraison (ou livraison inconnue) ; 404 `fichier_absent`
    si déclaré mais absent du disque ; 200 {ok: true} une fois l'ouvreur appelé."""
    from bouzecode.backend.agent.related_files import meme_chemin
    body = request.get_json(silent=True) or {}
    path = str(body.get("path") or "").strip()
    session_id = str(body.get("session_id") or "").strip()
    micro_id = str(body.get("micro_id") or "").strip()
    if not path or not (session_id or micro_id):
        raise Refus("parametres_manquants", "path et session_id ou micro_id requis", 400)
    declares = _declares_session(session_id) if session_id else _declares_micro(micro_id)
    if not any(meme_chemin(path, f.get("path", "")) for f in declares):
        raise Refus("fichier_non_declare",
                    "ce chemin n'est pas un fichier livré de cette livraison", 403, path=path)
    if not Path(path).exists():
        raise Refus("fichier_absent", f"fichier introuvable : {path}", 404, path=path)
    ouvreur = current_app.config.get(CLE_OUVREUR) or ouvrir_avec_l_os
    ouvreur(path)
    return jsonify({"ok": True})
