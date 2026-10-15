# [desc] Loads and parses agent profile YAML files into AgentProfile dataclass instances. [/desc]
from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Dict

# `yaml` est importé à l'USAGE (16 ms au démarrage de chaque agent) : un agent sans profil
# déclaré ne lit jamais un seul fichier YAML.

from bouzecode.backend.profiles.models import AgentProfile


# YAML décodé, par chemin, avec la signature du fichier (mtime ns, taille, inode). Les
# typologies (`/api/typologies`, le catalogue, chaque lancement) relisaient tous les profils à
# chaque appel avec le décodeur YAML en pur Python : ~5 ms par fichier, 50 ms par requête pour
# 10 profils, plus sous Windows. Un fichier modifié change de signature et est relu.
_yaml_memo: Dict[str, tuple] = {}
_yaml_lock = threading.Lock()


def _signature(path: Path):
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size, st.st_ino)


def _lire_yaml(path: Path) -> dict:
    """Contenu YAML du fichier (copie profonde : l'appelant peut le modifier), décodé une fois
    par version du fichier, avec le décodeur C de libyaml quand il est disponible."""
    import yaml
    signature = _signature(path)
    cle = str(path)
    with _yaml_lock:
        connu = _yaml_memo.get(cle)
    if signature is not None and connu is not None and connu[0] == signature:
        return copy.deepcopy(connu[1])
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    data = yaml.load(path.read_text(encoding="utf-8"), Loader=loader) or {}  # noqa: S506 — SafeLoader
    if signature is not None:
        with _yaml_lock:
            _yaml_memo[cle] = (signature, copy.deepcopy(data))
    return data


def load_profile_from_path(path: Path) -> AgentProfile:
    """Parse a single YAML profile file into an AgentProfile."""
    data = _lire_yaml(path)
    return AgentProfile(
        name=str(data.get("name", path.stem)),
        description=str(data.get("description", "") or ""),
        skills=_as_str_list(data.get("skills", [])),
        tools=_as_str_list(data.get("tools", [])),
        hooks=_as_str_list(data.get("hooks", [])),
        requires_plugins=_as_plugin_list(data.get("requires_plugins", [])),
        model=str(data.get("model", "") or ""),
        system_prompt_extra=str(data.get("system_prompt_extra", "") or ""),
        kind=str(data.get("kind", "user") or "user"),
        plan_mode=bool(data.get("plan_mode", True)),
        require_recap=bool(data.get("require_recap", False)),
        require_taches=bool(data.get("require_taches", True)),
        inherit_default=bool(data.get("inherit_default", True)),
    )


def load_profiles_from_dir(directory: Path) -> Dict[str, AgentProfile]:
    """Load all *.yaml and *.yml profiles from a directory."""
    profiles: Dict[str, AgentProfile] = {}
    if not directory.is_dir():
        return profiles
    for ext in ("*.yaml", "*.yml"):
        for p in sorted(directory.glob(ext)):
            profile = load_profile_from_path(p)
            profiles[profile.name] = profile
    return profiles


def _as_str_list(value) -> list[str]:
    """Normalize a value to a list of strings."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return []


def _as_plugin_list(value) -> list:
    """Normalize requires_plugins: keep dict entries ({name, source}) as-is,
    coerce bare strings to plain names."""
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    if isinstance(value, list):
        return [v if isinstance(v, dict) else str(v) for v in value]
    return []
