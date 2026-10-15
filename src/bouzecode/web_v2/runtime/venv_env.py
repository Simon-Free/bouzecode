# [desc] Faire pointer un agent vers le venv du dépôt de BASE, pour qu'un worktree sans venv n'en fabrique pas un. [/desc]
"""Les variables d'environnement qui donnent à un agent le venv du dépôt de base.

LE PROBLÈME MESURÉ (2026-07-30). L'isolation `worktree` promet « un worktree git dédié, SANS
venv » — et le serveur tient cette promesse : `provisioning._provision_worktree` ne provisionne
un venv que pour `worktree+venv`. Sauf que l'agent se retrouve alors dans un dossier SANS aucun
environnement Python, et au premier `uv run` / `uv sync` / `pytest`, **uv en crée un sur place** :
`~/.bouzecode/worktrees/<repo>/<ticket>/.venv`, ~1 Go pour demo_application. Constat sur le
parc réel : 11 des 21 tickets `worktree` portaient un venv que PERSONNE n'avait demandé.

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

import logging
import os
import re
from pathlib import Path

_log = logging.getLogger(__name__)


def venv_bin_dir(venv: str | os.PathLike) -> Path:
    """Dossier des exécutables du venv : `Scripts` sous Windows, `bin` ailleurs."""
    return Path(venv) / ("Scripts" if os.name == "nt" else "bin")


def pinned_python_spec() -> str:
    """La version PATCH à ÉPINGLER à la CRÉATION d'un venv (`uv venv --python <ici>`).

    `.python-version` du dépôt dit la SÉRIE (`3.12`) : uv résout alors le lien ROULANT
    `cpython-3.12-windows-…` et l'écrit dans `pyvenv.cfg`. Le prochain patch repointe ce
    lien, la version gravée devient fausse, et uv SUPPRIME le venv qu'il juge invalide —
    c'est le piège armé le 2026-08-20 qui a détruit trois fois le venv partagé le
    2026-08-24 (cf. `is_compatible`, qui ne protège que la LECTURE d'un venv existant).

    Épingler le patch fait pointer `home` vers un répertoire VERSIONNÉ
    (`cpython-3.12.13-…`), que rien ne repointe jamais. On prend la version de
    l'interpréteur COURANT : c'est celui qui fait déjà tourner le serveur et les agents,
    donc celui avec lequel le venv doit s'accorder."""
    import sys

    return "%d.%d.%d" % sys.version_info[:3]


def is_usable(venv: str) -> bool:
    """Ce venv est-il utilisable ? Un dossier ne suffit pas : `pyvenv.cfg` est le marqueur qui
    fait qu'un interpréteur s'y reconnaît (sans lui, `python.exe` refuse de démarrer — vécu le
    2026-07-30). On exige donc le marqueur ET le dossier d'exécutables."""
    if not venv:
        return False
    root = Path(venv)
    return (root / "pyvenv.cfg").is_file() and venv_bin_dir(root).is_dir()


def _recorded_version(venv: str) -> str:
    """La version gravée dans `pyvenv.cfg` (`version_info`), ou "" si illisible."""
    cfg = Path(venv) / "pyvenv.cfg"
    try:
        lignes = cfg.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for ligne in lignes:
        cle, _, valeur = ligne.partition("=")
        if cle.strip() == "version_info":
            return valeur.strip()
    return ""


def _interpreter_version(venv: str) -> str:
    """La version de l'interpréteur que `home` désigne AUJOURD'HUI, ou "" si indéterminable.

    Lue dans le NOM du répertoire résolu, jamais en lançant l'interpréteur : cette
    fonction est sur le chemin du spawn, et un sous-process par agent se paierait à
    chaque lancement. Les interpréteurs d'uv s'appellent
    `cpython-3.12.13-windows-x86_64-none`, et le lien roulant `cpython-3.12-windows-…`
    se résout vers le répertoire versionné. Un chemin sans version lisible
    (`C:\\Program Files\\Python313`) renvoie "" — et sera traité comme compatible,
    faute de quoi on refuserait des venvs parfaitement sains.
    """
    cfg_home = ""
    try:
        for ligne in (Path(venv) / "pyvenv.cfg").read_text(encoding="utf-8",
                                                           errors="replace").splitlines():
            cle, _, valeur = ligne.partition("=")
            if cle.strip() == "home":
                cfg_home = valeur.strip()
    except OSError:
        return ""
    if not cfg_home:
        return ""
    try:
        nom = Path(cfg_home).resolve().name
    except OSError:
        return ""
    m = re.search(r"cpython-(\d+\.\d+\.\d+)", nom)
    return m.group(1) if m else ""


def is_compatible(base_venv: str) -> bool:
    """uv accepterait-il ce venv, ou le jugerait-il invalide et le DÉTRUIRAIT-il ?

    uv ne met jamais un venv à jour : dès qu'il le juge invalide, il le SUPPRIME et le
    recrée. Le critère qu'il applique est écrit dans ses propres avertissements :
    « The interpreter in the project environment has a different version (3.12.13) than
    it was created with (3.12.12) ».

    Ce désaccord naît tout seul. `pyvenv.cfg` grave une version au jour de la création,
    et son `home` peut pointer le lien ROULANT d'uv (`cpython-3.12-windows-…`), que le
    prochain patch repointe. Le 2026-08-20 à 16:08 ce lien est passé de 3.12.12 à
    3.12.13 : le piège était armé quatre jours avant le premier dégât.

    Et le dégât ne se répare pas seul, il s'entretient. Le 2026-08-24 à 10:19:13 un agent
    lance `uv sync --frozen` dans son worktree, avec `UV_PROJECT_ENVIRONMENT` pointant —
    parce que c'est CE module qui l'a posé — sur le venv du dépôt principal. uv vide
    `Lib/site-packages`, puis échoue sur `Scripts/` (os error 32 : `bouzecode.exe`
    verrouillé par les agents CLI en cours) et abandonne SANS réécrire `pyvenv.cfg`. Le
    `uv sync` suivant relit la même version périmée et re-vide. Trois destructions ce
    jour-là, et tous les agents lancés après mouraient sur `ModuleNotFoundError`.

    D'où cette garde : un venv que uv jugerait invalide ne lui est plus DÉSIGNÉ. L'agent
    le garde pour exécuter (`VIRTUAL_ENV`, `PATH`), mais uv ne le vise plus, donc il ne
    peut plus le détruire.
    """
    grave, reelle = _recorded_version(base_venv), _interpreter_version(base_venv)
    if not grave or not reelle:
        return True  # indéterminable : on ne refuse pas un venv sur une supposition
    return grave.split(".final")[0] == reelle


def base_venv_env(base_venv: str, environ: dict | None = None) -> dict[str, str]:
    """Variables à injecter au spawn pour qu'un agent utilise `base_venv`. {} si inutilisable.

    Pur : `environ` injectable (défaut `os.environ`) — le PATH est PRÉFIXÉ, jamais remplacé,
    sinon l'agent perdrait git, uv et tout le reste de son outillage.

    `UV_PROJECT_ENVIRONMENT` n'est posé que si le venv est COMPATIBLE (cf. `is_compatible`) :
    le désigner à uv alors qu'il le juge invalide, c'est lui demander de le détruire."""
    if not is_usable(base_venv):
        return {}
    environ = os.environ if environ is None else environ
    bin_dir = str(venv_bin_dir(base_venv))
    previous_path = environ.get("PATH", "")
    env = {
        "VIRTUAL_ENV": str(Path(base_venv)),
        "PATH": os.pathsep.join([bin_dir, previous_path]) if previous_path else bin_dir,
    }
    if is_compatible(base_venv):
        env["UV_PROJECT_ENVIRONMENT"] = str(Path(base_venv))
    else:
        _log.warning(
            "venv %s incompatible (pyvenv.cfg=%s, interpreteur=%s) : UV_PROJECT_ENVIRONMENT "
            "n'est PAS pose, sinon le premier `uv sync` d'un agent le detruirait",
            base_venv, _recorded_version(base_venv), _interpreter_version(base_venv),
        )
    return env


_VARIABLES_DE_VENV = ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT")


def _meme_chemin(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def retirer_venvs(environ: dict, venvs) -> dict[str, str]:
    """Copie de `environ` où aucun de ces `venvs` n'est plus désigné : ni par VIRTUAL_ENV /
    UV_PROJECT_ENVIRONMENT, ni par son dossier d'exécutables dans le PATH (sinon `python` et
    `pip` y résoudraient encore). Clés comparées sans casse, comme Windows le fait."""
    venvs = [v for v in venvs if v]
    if not venvs:
        return dict(environ)
    bins = [str(venv_bin_dir(v)) for v in venvs]
    out = {}
    for cle, valeur in environ.items():
        if cle.upper() in _VARIABLES_DE_VENV and valeur and any(
                _meme_chemin(valeur, v) for v in venvs):
            continue
        if cle.upper() == "PATH":
            valeur = os.pathsep.join(p for p in valeur.split(os.pathsep)
                                     if not (p and any(_meme_chemin(p, b) for b in bins)))
        out[cle] = valeur
    return out


def env_sans_venv_designe(environ: dict | None = None) -> dict[str, str]:
    """Env pour CRÉER le venv dédié d'un worktree : aucun venv hérité n'y est désigné.

    Vécu le 2026-10-12 : `Environment(action='venv')` lançait `uv venv` / `uv sync` avec l'env
    du process bouzecode, qui pouvait porter VIRTUAL_ENV / UV_PROJECT_ENVIRONMENT vers le venv d'un
    AUTRE projet (celui de bouzecode). uv vise alors ce venv-là au lieu du `./.venv` du worktree :
    au mieux le sync échoue, au pire il détruit le venv partagé (os error 32 sur `Scripts`)."""
    environ = dict(os.environ if environ is None else environ)
    designes = [v for cle, v in environ.items() if cle.upper() in _VARIABLES_DE_VENV]
    out = retirer_venvs(environ, designes)
    return {k: v for k, v in out.items()
            if k.upper() not in _VARIABLES_DE_VENV + ("UV_NO_SYNC",)}
