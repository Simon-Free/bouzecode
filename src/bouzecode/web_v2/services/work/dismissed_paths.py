# [desc] Journal des dossiers que l'utilisateur a explicitement désignés comme n'étant PAS des projets. [/desc]
"""Le versant « non » du registre de projets.

`projects.json` répond « ce dossier est un projet ». Ce journal-ci répond
« ce dossier n'en est pas un, et l'utilisateur l'a dit » — ce qui permet de ne
plus jamais reposer la question. Un dossier absent des deux listes est
simplement *inconnu* : la question n'a jamais été posée.

Fichier séparé de `projects.json` à dessein : celui-ci est un tableau lu tel
quel par l'interface pour construire la liste de lancement ; y glisser des
non-projets les y ferait apparaître.

La comparaison est faite sur le chemin **exact** (normalisé), jamais sur un
préfixe : écarter `demo/` ne dit rien de `demo/un_nouveau_projet/`.
"""
from __future__ import annotations
from bouzecode.paths import data_dir as bouzecode_data_dir

import json
import os
from pathlib import Path

from bouzecode.web_v2.services.horodatage import maintenant_iso

DISMISSED_PATH = bouzecode_data_dir() / "web_v2" / "dismissed_paths.json"


def _key(path: str | Path) -> str:
    """Forme comparable d'un chemin : absolu, résolu, casse normalisée.

    `normcase` est ce qui rend la comparaison correcte sous Windows, où
    `C:\\Users\\x` et `c:/users/x` désignent le même dossier.
    """
    return os.path.normcase(str(Path(path).expanduser().resolve()))


def list_dismissed() -> list[dict]:
    if not DISMISSED_PATH.is_file():
        return []
    entries = json.loads(DISMISSED_PATH.read_text(encoding="utf-8"))
    return entries if isinstance(entries, list) else []


def _save(entries: list[dict]) -> None:
    DISMISSED_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = DISMISSED_PATH.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(DISMISSED_PATH)


def is_dismissed(path: str | Path) -> bool:
    """True si l'utilisateur a déjà dit que ce dossier n'est pas un projet."""
    target = _key(path)
    return any(_key(entry["path"]) == target for entry in list_dismissed())


def find_dismissal(path: str | Path) -> dict | None:
    """L'entrée du journal pour ce chemin, ou None. Sert à dire *quand* et *pourquoi*."""
    target = _key(path)
    return next((e for e in list_dismissed() if _key(e["path"]) == target), None)


def dismiss(path: str | Path, reason: str = "", by: str = "user") -> dict:
    """Enregistre « ce dossier n'est pas un projet ». Idempotent."""
    resolved = Path(path).expanduser().resolve()
    existing = find_dismissal(resolved)
    if existing is not None:
        return existing
    entry = {
        "path": str(resolved),
        "dismissed_at": maintenant_iso(),
        "by": by,
        "reason": reason.strip()[:200],
    }
    _save(list_dismissed() + [entry])
    return entry


def undismiss(path: str | Path) -> bool:
    """Remet le dossier à l'état *inconnu*. True s'il était écarté."""
    target = _key(path)
    entries = list_dismissed()
    remaining = [e for e in entries if _key(e["path"]) != target]
    if len(remaining) == len(entries):
        return False
    _save(remaining)
    return True
