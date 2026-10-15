# [desc] Canal agent→serveur : où l'agent s'est déplacé en vol (env.json dans le dossier IPC). [/desc]
"""Un agent gouverné est un PROCESS SÉPARÉ : son `cwd` est fixé au `Popen` par
`runner.create_agent`, et `agent.cwd` (le champ persisté que toute reprise relit) vit côté
SERVEUR. Quand l'agent se provisionne lui-même un worktree — outil `Environment` — il fait un
`os.chdir()` dans SON process : le serveur, lui, continue de croire à l'ancien chemin, et le
premier `/continue` respawne au mauvais endroit (ou sur un dossier détruit → NotADirectoryError,
que l'UI étiquette à tort « interrompez l'agent d'abord »).

Le canal existe déjà et on n'en invente pas un second : le dossier IPC de l'agent, exposé au
process fils par `config["_web_agent_dir"]` / `BOUZECODE_WEB_IPC_DIR`, où `backend/tools/plan_mode`
dépose déjà `plan.md` que le serveur relit. On y dépose `env.json`.

Écrit par l'AGENT (`write`), relu par le SERVEUR (`read`) sur le chemin de recalage
(`services/work/provisioning.rehome_agent_cwd`). L'échec d'écriture n'est jamais fatal : un
signal perdu dégrade la reprise, il ne doit pas faire échouer l'action que l'agent vient de
réussir."""
from __future__ import annotations

import json
import os
from pathlib import Path

FILENAME = "env.json"

#: Les seuls champs que le serveur sait adopter. Le jeu est FERMÉ à dessein : un champ
#: inconnu serait écrit, jamais lu, et la faute de frappe ne se verrait nulle part.
FIELDS = ("cwd", "worktree_root", "base_venv")


def path(ipc_dir: str | os.PathLike) -> Path:
    """Chemin du fichier de signal dans un dossier IPC donné."""
    return Path(ipc_dir) / FILENAME


def read(ipc_dir: str | os.PathLike | None) -> dict[str, str]:
    """Ce que l'agent a signalé, ou `{}` s'il n'a rien signalé / si c'est illisible.

    Jamais d'exception : cette fonction est appelée sur le chemin de REPRISE d'un agent. Un
    JSON tronqué (crash pendant l'écriture) doit dégrader vers « je ne sais rien » — le
    serveur retombe alors sur son comportement d'avant ce module."""
    if not ipc_dir:
        return {}
    try:
        data = json.loads(path(ipc_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: str(v) for k, v in data.items() if k in FIELDS and v}


def write(ipc_dir: str | os.PathLike | None, **fields: str) -> bool:
    """Signale un ou plusieurs champs au serveur. Renvoie True si le fichier a été écrit.

    FUSIONNE avec ce qui est déjà là : l'action `venv` ne signale que `base_venv`, après que
    l'action `worktree` a signalé `cwd`/`worktree_root` — une écriture qui remplacerait le
    fichier ferait oublier au serveur le déplacement, c'est-à-dire exactement le bug que ce
    module existe pour empêcher.

    `ipc_dir` vide = agent hors serveur web (CLI) : no-op, pas une erreur.
    Champ hors `FIELDS` = bug de programmation → `ValueError` tout de suite."""
    inconnus = sorted(set(fields) - set(FIELDS))
    if inconnus:
        raise ValueError(f"champ(s) de signal inconnu(s) : {', '.join(inconnus)} "
                         f"(connus : {', '.join(FIELDS)})")
    if not ipc_dir:
        return False
    data = read(ipc_dir)
    data.update({k: str(v) for k, v in fields.items() if v})
    target = path(ipc_dir)
    tmp = target.with_name(f"{FILENAME}.tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, target)  # atomique : le serveur ne lit jamais un fichier à moitié écrit
    except OSError:
        return False
    return True


def clear(ipc_dir: str | os.PathLike | None) -> None:
    """Oublie le signal (le serveur l'a adopté). Best-effort, jamais d'exception."""
    if not ipc_dir:
        return
    try:
        path(ipc_dir).unlink()
    except OSError:
        pass
