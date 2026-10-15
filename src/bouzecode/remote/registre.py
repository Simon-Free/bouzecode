"""Registre local des executions distantes : execution_id Rundeck -> run_id, job, mode, depots, ticket.

Un fichier JSON par execution sous ~/.bouzecode/remote/executions/ ; c'est ce qui permet a
`suivre()` et `recuperer()` de ne recevoir que l'execution_id.
"""
from bouzecode.paths import data_dir as bouzecode_data_dir
import json
from pathlib import Path

from bouzecode.backend.core.garde_vrai_home import refuser_le_vrai_home


def racine_locale() -> Path:
    """Relue à chaque appel (HOME du test) ; jamais le vrai profil sous pytest (fuite du 2026-10-06)."""
    return refuser_le_vrai_home(bouzecode_data_dir() / "remote")


def _chemin(execution_id: str) -> Path:
    return racine_locale() / "executions" / f"{execution_id}.json"


def enregistrer(execution_id: str, fiche: dict) -> None:
    chemin = _chemin(execution_id)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(fiche, indent=2, ensure_ascii=False), encoding="utf-8")


def lire(execution_id: str) -> dict | None:
    chemin = _chemin(str(execution_id))
    return json.loads(chemin.read_text(encoding="utf-8")) if chemin.is_file() else None
