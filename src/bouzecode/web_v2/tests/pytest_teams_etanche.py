# [desc] Plugin pytest : aucun test ne lance le vrai PowerShell Teams / Microsoft Graph ; toute tentative échoue bruyamment. [/desc]
"""Aucun test ne parle au vrai Teams.

Pourquoi : les tests redirigent HOME et USERPROFILE vers un dossier jetable. Un vrai script
Graph lancé depuis un test n'y trouve donc aucune session enregistrée, et `Connect-MgGraph`
ouvre une fenêtre de connexion Microsoft sur le poste de l'utilisateur — à chaque run.

Deux verrous, posés AU CHARGEMENT du plugin (`-p` dans `addopts`) :

1. Dans CE processus, un hook d'audit (`sys.addaudithook`) regarde chaque `subprocess.Popen` :
   si la ligne de commande désigne un script de `services/work/teams/ps/`, il lève
   `TeamsReelInterdit` AVANT la création du processus. La tentative est aussi NOTÉE : même si
   le code appelant avale l'exception (`except Exception`), le test échoue en nommant le
   script. Aucune fenêtre ne s'ouvre. Les tests passent un faux transport (runner injecté).
2. Pour les DESCENDANTS (agents, serveurs, CLI lancés par un test), la variable
   `BZ_TESTS_TEAMS_INTERDIT=1` est héritée ; `ps/graph_auth.ps1` la lit et refuse de se
   connecter, avant tout `Connect-MgGraph`.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

VAR_INTERDIT = "BZ_TESTS_TEAMS_INTERDIT"
DOSSIER_PS = Path(__file__).resolve().parents[1] / "services" / "work" / "teams" / "ps"
#  Lu sur le disque : un script ajouté demain est couvert sans toucher ce plugin.
SCRIPTS_TEAMS = frozenset(p.name.lower() for p in DOSSIER_PS.glob("*.ps1"))


#  Tentatives notées depuis le dernier rapport de test.
_tentatives: list[str] = []


class TeamsReelInterdit(RuntimeError):
    """Un test a tenté de lancer un vrai script Teams / Graph."""


def _morceaux(args) -> list[str]:
    if isinstance(args, (str, bytes, os.PathLike)):
        args = [args]
    return [os.fsdecode(os.fspath(a)) if isinstance(a, (bytes, os.PathLike)) else str(a)
            for a in (args or ())]


def script_teams_vise(executable, args) -> str | None:
    """Le nom du script Teams que cette ligne de commande lancerait, sinon None."""
    for morceau in _morceaux(args) + _morceaux([executable] if executable else []):
        for mot in morceau.replace("\\", "/").replace('"', " ").replace("'", " ").split():
            nom = mot.rsplit("/", 1)[-1].lower()
            if nom in SCRIPTS_TEAMS:
                return nom
    return None


def _audit(evenement: str, args) -> None:
    if evenement != "subprocess.Popen":
        return
    nom = script_teams_vise(args[0], args[1])
    if nom:
        _tentatives.append(nom)
        raise TeamsReelInterdit(
            f"un test a voulu lancer le vrai script Teams `{nom}` : il ouvrirait une connexion "
            "Microsoft sur le poste. Injecter un faux transport (paramètre `runner`) à la place.")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    rapport = (yield).get_result()
    if not _tentatives:
        return
    noms = sorted(set(_tentatives))
    del _tentatives[:]
    message = ("lancement du VRAI PowerShell Teams bloqué (" + ", ".join(noms) + ") : "
               "injecter un faux transport. Voir pytest_teams_etanche.py.")
    if rapport.failed:
        rapport.sections.append(("Teams réel", message))
    else:
        rapport.outcome = "failed"
        rapport.longrepr = message


os.environ[VAR_INTERDIT] = "1"
sys.addaudithook(_audit)
