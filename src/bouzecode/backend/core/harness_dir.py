# [desc] Dossier de travail du harnais dans le dossier de l'agent (.nano_claude/…), exclu de git localement. [/desc]
"""Les plans et exports du harnais s'écrivent dans `<dossier de l'agent>/.nano_claude/<sous-dossier>`.

Le dossier de l'agent est `dossier_agent.courant()` : le worktree d'un sous-agent en process
(son atelier), le cwd du process sinon. `Path.cwd()` envoyait les plans d'un sous-agent isolé
dans le checkout principal (constaté : `demo_application/.nano_claude/plans/default.md`).

Ce ne sont jamais des fichiers du produit : une récolte automatique (`git add -A`) les
committait pourtant dans le dépôt de l'utilisateur (constaté : `.nano_claude/plans/<id>.md`
suivi dans main). On les exclut donc via `.git/info/exclude` du dépôt (local, jamais
committé) au moment où le harnais crée le dossier — sans toucher au `.gitignore` du projet.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

RACINE = ".nano_claude"
_MOTIF = f"{RACINE}/"


def dossier_harnais(sous_dossier: str, cwd: Path | None = None) -> Path:
    """Crée et renvoie `<base>/.nano_claude/<sous_dossier>`, exclu de git si base est un dépôt.
    `base` : `cwd` s'il est donné, sinon le dossier de l'agent qui s'exécute."""
    from .dossier_agent import courant
    base = Path(cwd) if cwd else Path(courant())
    dossier = base / RACINE / sous_dossier
    dossier.mkdir(parents=True, exist_ok=True)
    exclure_de_git(base)
    return dossier


def exclure_de_git(base: Path) -> bool:
    """Ajoute `.nano_claude/` à l'exclusion LOCALE du dépôt git de `base` (idempotent).

    Renvoie True si le motif est présent après l'appel ; False hors dépôt ou sans git."""
    exclude = _fichier_exclude(base)
    if exclude is None:
        return False
    existant = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if _MOTIF in existant.splitlines():
        return True
    exclude.parent.mkdir(parents=True, exist_ok=True)
    separateur = "" if not existant or existant.endswith("\n") else "\n"
    exclude.write_text(f"{existant}{separateur}{_MOTIF}\n", encoding="utf-8")
    return True


def _fichier_exclude(base: Path) -> Path | None:
    try:
        res = subprocess.run(["git", "-C", str(base), "rev-parse", "--git-path", "info/exclude"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    chemin = res.stdout.strip()
    if res.returncode != 0 or not chemin:
        return None
    return base / chemin  # relatif à base, ou absolu (Path garde l'absolu)
