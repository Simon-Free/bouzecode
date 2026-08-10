# [desc] Faire pointer un agent vers le venv du dépôt de BASE, pour qu'un worktree sans venv n'en fabrique pas un. [/desc]
"""Les variables d'environnement qui donnent à un agent le venv du dépôt de base.

LE PROBLÈME MESURÉ (2026-07-30). L'isolation `worktree` promet « un worktree git dédié, SANS
venv » — et le serveur tient cette promesse : `provisioning._provision_worktree` ne provisionne
un venv que pour `worktree+venv`. Sauf que l'agent se retrouve alors dans un dossier SANS aucun
environnement Python, et au premier `uv run` / `uv sync` / `pytest`, **uv en crée un sur place** :
`~/.bouzecode/worktrees/<repo>/<ticket>/.venv`, ~1 Go pour une application Python de taille
moyenne. Constat sur un parc réel : 11 des 21 tickets `worktree` portaient un venv que
PERSONNE n'avait demandé.

Le remède ne change rien au contrat d'isolation (cf. `services/work/isolation.py`, exposé aux
managers par le paramètre `isolation` de l'outil `Agent`) : il le HONORE, en donnant à l'agent
le venv qui existe déjà, celui du dépôt de base.

    VIRTUAL_ENV            → `python`, `pytest`, `pip` résolvent vers ce venv
    PATH (préfixé)         → ses exécutables gagnent, comme après un `activate`
    UV_PROJECT_ENVIRONMENT → uv VISE ce venv au lieu de créer `./.venv` (la cause exacte)

⚠️ CONSÉQUENCE ASSUMÉE : un agent qui lance `uv sync` modifie alors le venv du dépôt de base,
partagé avec le serveur et les autres agents. C'est le comportement DEMANDÉ (« utiliser celui
du projet de base »), et c'est déjà ce que fait n'importe quel agent en isolation `shared`. Un
agent dont on sait qu'il va toucher aux dépendances doit être lancé en `worktree+venv` — c'est
précisément ce que dit le schéma de l'outil `Agent` au manager.
"""
from __future__ import annotations

import os
from pathlib import Path


def venv_bin_dir(venv: str | os.PathLike) -> Path:
    """Dossier des exécutables du venv : `Scripts` sous Windows, `bin` ailleurs."""
    return Path(venv) / ("Scripts" if os.name == "nt" else "bin")


def is_usable(venv: str) -> bool:
    """Ce venv est-il utilisable ? Un dossier ne suffit pas : `pyvenv.cfg` est le marqueur qui
    fait qu'un interpréteur s'y reconnaît (sans lui, `python.exe` refuse de démarrer — vécu le
    2026-07-30). On exige donc le marqueur ET le dossier d'exécutables."""
    if not venv:
        return False
    root = Path(venv)
    return (root / "pyvenv.cfg").is_file() and venv_bin_dir(root).is_dir()


def base_venv_env(base_venv: str, environ: dict | None = None) -> dict[str, str]:
    """Variables à injecter au spawn pour qu'un agent utilise `base_venv`. {} si inutilisable.

    Pur : `environ` injectable (défaut `os.environ`) — le PATH est PRÉFIXÉ, jamais remplacé,
    sinon l'agent perdrait git, uv et tout le reste de son outillage."""
    if not is_usable(base_venv):
        return {}
    environ = os.environ if environ is None else environ
    bin_dir = str(venv_bin_dir(base_venv))
    previous_path = environ.get("PATH", "")
    return {
        "VIRTUAL_ENV": str(Path(base_venv)),
        "UV_PROJECT_ENVIRONMENT": str(Path(base_venv)),
        "PATH": os.pathsep.join([bin_dir, previous_path]) if previous_path else bin_dir,
    }
