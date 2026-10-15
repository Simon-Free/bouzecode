# [desc] Le venv d'un dossier = celui du projet Python où l'agent travaille (pyproject le plus proche, worktree ramené à son checkout principal) ; désigner ce venv-là et lui seul dans l'env d'une commande. [/desc]
"""Quel venv les commandes d'un agent utilisent-elles ? Celui du projet où il TRAVAILLE.

LE CONSTAT (2026-10-12). Hors worktree, un agent qui faisait LoadProjectConfig(demo_application,
cd=true) changeait bien de dossier, mais ses `python` / `pytest` résolvaient encore vers le venv
hérité — celui de bouzecode (bouzecode, 3.12) — et jamais vers demo_application\\.venv. Seul un
worktree d'agent recevait le venv de son projet (`venv_meme_projet`, même jour). La question de
l'utilisateur : « s'il travaille dans demo_application, LoadProjectConfig devrait renvoyer le
venv de demo_application non ? » — oui.

LA RÈGLE, la même quel que soit le chemin qui a mené l'agent là (spawn en worktree,
LoadProjectConfig(cd=true), Environment(action='worktree'), simple cwd) :

  1. projet = dossier du pyproject.toml le plus proche en REMONTANT depuis le dossier courant,
     sans dépasser la racine du checkout git (dossier qui porte `.git`) ;
  2. venv = `<projet>/.venv` dans CE checkout s'il est utilisable (venv du projet, ou venv dédié
     d'un worktree créé par Environment(action='venv')) ; sinon, pour un worktree, le venv du
     même projet dans son checkout principal ; sinon le `.venv` à la racine du dépôt ;
  3. pas de pyproject → aucun venv : on n'en désigne pas un d'un autre projet.
"""
from __future__ import annotations

import functools
import os
from pathlib import Path

from . import venv_meme_projet


def _racine_checkout(dossier: Path) -> Path | None:
    """Le dossier qui porte `.git` (dossier ou fichier de worktree) au-dessus de `dossier`."""
    for candidat in (dossier, *dossier.parents):
        if (candidat / ".git").exists():
            return candidat
    return None


@functools.lru_cache(maxsize=256)
def _candidats(dossier: str) -> tuple[str, ...]:
    """Les `.venv` possibles du projet de `dossier`, par ordre de préférence (structure seule,
    mise en cache : l'existence des venvs, elle, est revérifiée à chaque appel)."""
    ici = Path(os.path.abspath(dossier))
    checkout = _racine_checkout(ici)
    projet = next((c for c in (ici, *ici.parents)
                   if (c / "pyproject.toml").is_file()
                   and (checkout is None or venv_meme_projet._sous(str(c), str(checkout)))), None)
    if projet is None:
        return ()
    candidats = [projet / ".venv"]
    if checkout is not None:
        relatif = os.path.relpath(projet, checkout)
        principal = venv_meme_projet.depot_principal(str(checkout))
        if principal and os.path.normcase(principal) != os.path.normcase(str(checkout)):
            candidats.append(Path(os.path.normpath(os.path.join(principal, relatif, ".venv"))))
            candidats.append(Path(principal) / ".venv")
        else:
            candidats.append(checkout / ".venv")
    return tuple(dict.fromkeys(str(c) for c in candidats))


def venv_du_projet(dossier: str) -> str:
    """Le venv du projet Python où se trouve `dossier`, "" si aucun (ou hors projet)."""
    from ....web_v2.runtime import venv_env
    return next((c for c in _candidats(dossier) if venv_env.is_usable(c)), "")


def _venvs_designes(env: dict[str, str]) -> list[str]:
    """Les venvs que `env` désigne déjà : VIRTUAL_ENV / UV_PROJECT_ENVIRONMENT absolus, plus le
    venv de bouzecode (son `Scripts` peut être en tête du PATH sans aucune variable)."""
    designes = [v for cle, v in env.items()
                if cle.upper() in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT") and v and os.path.isabs(v)]
    return designes + [venv_meme_projet.venv_de_bouzecode()]


def designer(env: dict[str, str], venv: str) -> dict[str, str]:
    """`env` où `venv` — et lui seul — est désigné : tout autre venv hérité est retiré (variables
    et PATH), puis `venv` est posé par `venv_env.base_venv_env` (PATH préfixé, et
    UV_PROJECT_ENVIRONMENT seulement sous la garde `is_compatible`). `venv` = "" : aucun.
    Idempotent : le venv choisi est retiré avant d'être reposé, le PATH n'empile rien."""
    from ....web_v2.runtime import venv_env
    out = venv_env.retirer_venvs(env, _venvs_designes(env) + [venv])
    if venv:
        out.update(venv_env.base_venv_env(venv, out))
    return out


def ligne_de_briefing(projet: str) -> str:
    """Ce que LoadProjectConfig dit du venv que les commandes utiliseront dans `projet`."""
    venv = venv_du_projet(projet)
    if venv:
        return f"Venv : {venv} — tes commandes (python, pytest, uv) l'utilisent dans ce projet."
    if not _candidats(projet):
        return "Venv : aucun — pas de pyproject.toml ici, ce n'est pas un projet Python."
    return ("Venv : aucun venv trouvé — Environment(action='venv') pour en créer un dans un "
            "worktree.")
