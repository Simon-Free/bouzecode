# [desc] Capture au boot le SHA git/version bouzecode et calcule le drift pour GET /api/version. [/desc]
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

_BASE = Path(__file__).resolve().parent
SOURCE_ROOT: str = str(_BASE.parent)  # src/bouzecode — le code réellement importé

# Mémoire process : figée UNE fois au boot par capture_boot_state().
BOOT_SHA: str = ""
BOOT_VERSION: str = ""
REPO_ROOT: str = ""
BOOT_SOURCE_FINGERPRINT: str = ""

# Seuls les fichiers que le PROCESS a figés en mémoire comptent : les modules
# importés (.py) et les templates (Jinja les met en cache après le premier rendu).
# Volontairement PAS .css/.js : ceux-là sont servis depuis le disque à chaque requête
# en no-cache, donc un édit y est déjà visible — les compter lèverait un faux drift.
_SOURCE_SUFFIXES = (".py", ".html")
# Ignorés : bytecode dérivé, vendor/ (assets tiers immuables) et node_modules/.
# node_modules pesait à lui seul 825 des 877 répertoires parcourus pour UN fichier .html
# non chargé par le process : le sauter fait tomber le scan de 66 ms à 3,5 ms.
_SKIP_DIRS = ("__pycache__", "vendor", ".git", "node_modules")


def _no_window() -> dict:
    """Sous Windows, un serveur sans console (pythonw, service) ouvrait une fenêtre furtive
    à chaque `git`, soit toutes les 10 s au rythme du poll de /api/version."""
    if sys.platform == "win32":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


def _git_head(repo_path: str) -> str:
    """SHA de HEAD dans repo_path, chaîne vide si introuvable.

    git d'abord ; s'il échoue (git.exe hors du PATH d'un serveur lancé par raccourci ou
    service Windows, timeout), HEAD est lu dans les fichiers de .git — sans ce repli,
    current_head_sha restait vide et le bandeau ne se levait jamais sur un HEAD qui avance.
    Fail-safe : ne lève jamais, pour ne JAMAIS casser le boot."""
    if not repo_path:
        return ""
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            **_no_window(),
        )
    except (OSError, subprocess.SubprocessError):
        result = None
    if result is not None and result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    from ..backend.core.code_version import read_head_sha
    return read_head_sha(repo_path)


def _git_toplevel(start: str) -> str:
    """Racine du repo git contenant `start`, ou `start` en fallback.

    Fail-safe : tout échec (git hors PATH, timeout, returncode != 0) renvoie
    `start` sans lever, pour ne JAMAIS casser le boot."""
    from ..backend.core.code_version import _find_repo_root
    try:
        result = subprocess.run(
            ["git", "-C", start, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            **_no_window(),
        )
    except (OSError, subprocess.SubprocessError):
        return _find_repo_root(Path(start)) or start
    if result.returncode != 0:
        return _find_repo_root(Path(start)) or start
    return result.stdout.strip() or start


def _package_version() -> str:
    # "bouzecode": legacy distribution name (venv not yet reinstalled after rename).
    from bouzecode.backend.core.version_paquet import version_paquet
    return version_paquet("bouzecode", "bouzecode") or "unknown"


def source_fingerprint(source_root: str) -> str:
    """Empreinte du code source PRÉSENT SUR LE DISQUE : « <nb fichiers>:<mtime max> ».

    Le SHA de HEAD ne suffit pas : le 27/07, un serveur booté le 22/07 tournait du code
    périmé alors que HEAD n'avait pas bougé d'un commit — toute la dérive était dans le
    working tree (fichiers édités/supprimés, non commités), donc `drift` restait faux et
    aucun bandeau ne prévenait. Cette empreinte voit ce que le SHA ne voit pas.

    Fail-safe : renvoie "" si la racine est inconnue/illisible (jamais de bandeau faux)."""
    if not source_root or not os.path.isdir(source_root):
        return ""
    count = 0
    newest = 0
    # os.scandir plutôt qu'os.walk + os.stat : sous Windows le mtime vient déjà du
    # parcours de répertoire, ce qui évite un syscall par fichier. Mesuré sur le paquet :
    # 280 ms -> 70 ms, du même ordre que le `git rev-parse` que l'endpoint fait déjà.
    stack = [source_root]
    try:
        while stack:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name not in _SKIP_DIRS:
                            stack.append(entry.path)
                    elif entry.name.endswith(_SOURCE_SUFFIXES):
                        count += 1
                        newest = max(newest, entry.stat().st_mtime_ns)
    except OSError:
        # Arborescence qui bouge sous nos pieds (merge en cours) : pas d'empreinte
        # plutôt qu'un 500 sur GET /api/version. Le prochain appel retentera.
        return ""
    return f"{count}:{newest}"


def capture_boot_state() -> None:
    """Fige SHA + version + racine repo + empreinte du source au démarrage. Idempotent :
    ne recapture pas si déjà figé (protège contre un double create_app en test)."""
    global BOOT_SHA, BOOT_VERSION, REPO_ROOT, BOOT_SOURCE_FINGERPRINT
    if BOOT_SHA:
        return
    REPO_ROOT = _git_toplevel(str(_BASE))
    BOOT_SHA = _git_head(REPO_ROOT)
    BOOT_VERSION = _package_version()
    BOOT_SOURCE_FINGERPRINT = source_fingerprint(SOURCE_ROOT)


def version_state(
    boot_sha: str,
    boot_version: str,
    repo_path: str,
    boot_fingerprint: str = "",
    source_root: str = "",
) -> dict:
    """État de version consommé par GET /api/version, RECALCULÉ à chaque appel.

    Deux dérives, réunies dans `drift` pour le bandeau : `sha_drift` (HEAD a avancé
    depuis le boot) et `source_drift` (les fichiers sur le disque ne sont plus ceux
    chargés au boot — merge, édition non commitée, checkout). La seconde attrape le cas
    où HEAD n'a pas bougé mais le code, si."""
    current = _git_head(repo_path)
    sha_drift = bool(current) and bool(boot_sha) and current != boot_sha
    current_fingerprint = source_fingerprint(source_root) if boot_fingerprint else ""
    source_drift = bool(current_fingerprint) and current_fingerprint != boot_fingerprint
    return {
        "boot_sha": boot_sha,
        "current_head_sha": current,
        "sha_drift": sha_drift,
        "source_drift": source_drift,
        "drift": sha_drift or source_drift,
        "boot_version": boot_version,
    }


# Un état de version coûte un `git rev-parse` (~42 ms, spawn de process) + un scan du source
# (~3,5 ms) : trop cher pour un endpoint que TOUTE page poll en tâche de fond, à côté de
# /api/projects qui répond en 5 ms. Cache TTL court + single-flight, même motif que
# services/work/projects.py : une rafale de polls (plusieurs onglets, chargement de page) ne
# paie qu'un seul calcul. Cache mono-emplacement : en production la clé est toujours la même.
_state_cache: tuple | None = None  # (clé, état, échéance)
_state_lock = threading.Lock()
_state_compute_lock = threading.RLock()
# 10 s : la dérive n'alimente qu'un bandeau d'avertissement et le front ne poll que toutes les
# 40 s, donc au pire on prévient ~10 s plus tard qu'avant — sans enjeu — alors qu'une rafale de
# polls concurrents devient gratuite.
STATE_TTL_S = 10.0


def current_head_sha() -> str:
    """HEAD courant du dépôt (état mis en cache ci-dessous) : sert à signaler un agent qui
    tourne encore sur un commit antérieur."""
    return cached_version_state(BOOT_SHA, BOOT_VERSION, REPO_ROOT, BOOT_SOURCE_FINGERPRINT,
                                SOURCE_ROOT).get("current_head_sha", "")


def code_staleness(boot_commit: str) -> dict:
    """``code_boot_sha`` / ``code_head_sha`` / ``code_stale`` pour la fiche d'un agent.
    Pas de sha de démarrage (session antérieure au champ) ou HEAD illisible : jamais signalé."""
    head = current_head_sha() if boot_commit else ""
    stale = bool(boot_commit and head
                 and not head.startswith(boot_commit) and not boot_commit.startswith(head))
    return {"code_boot_sha": boot_commit or "", "code_head_sha": head, "code_stale": stale}


def cached_version_state(
    boot_sha: str,
    boot_version: str,
    repo_path: str,
    boot_fingerprint: str = "",
    source_root: str = "",
    *,
    now=time.monotonic,
    ttl: float = STATE_TTL_S,
    compute=version_state,
) -> dict:
    """`version_state` mémorisé pendant `ttl` secondes. `now`/`compute`/`ttl` sont injectables
    (les tests pilotent l'horloge et comptent les recalculs sans toucher au vrai temps)."""
    global _state_cache
    key = (boot_sha, boot_version, repo_path, boot_fingerprint, source_root)
    with _state_lock:
        if _state_cache and _state_cache[0] == key and now() < _state_cache[2]:
            return _state_cache[1]
    with _state_compute_lock:  # single-flight : un seul thread relit git + le disque
        with _state_lock:
            if _state_cache and _state_cache[0] == key and now() < _state_cache[2]:
                return _state_cache[1]
        state = compute(boot_sha, boot_version, repo_path, boot_fingerprint, source_root)
        with _state_lock:
            _state_cache = (key, state, now() + ttl)
        return state
