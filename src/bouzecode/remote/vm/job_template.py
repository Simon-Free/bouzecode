"""Construit le YAML d'un job Rundeck a usage unique, nomme `BZ_<run_id>` (jamais un nom partage).

Les fichiers Python a executer sont embarques en base64 dans le script du job : aucune
substitution Rundeck ne touche le code. Le job n'a ni planification ni notification ; il est
supprime apres recuperation du resultat.
"""
import base64

import yaml

from bouzecode.remote.transport.settings import RUNDECK_FILTRE_NOEUDS, RUNDECK_GROUPE_JOBS, VM_PYTHON


def nom_job(run_id: str) -> str:
    return f"BZ_{run_id}"


def script_bash(fichiers: dict[str, str], entree: str, options: list[str], arguments: str = "") -> str:
    """Les RD_OPTION_* ne traversent pas le SSH vers le noeud (AcceptEnv) : mesure du 2026-10-05,
    la sonde les a recues vides. On les re-exporte donc par substitution `@option.X@`."""
    exports = "".join(f"export RD_OPTION_{nom.upper()}='@option.{nom}@'\n" for nom in options)
    ecritures = "".join(
        f"echo '{base64.b64encode(code.encode('utf-8')).decode('ascii')}' | base64 -d > \"$BZ_SCRIPTS/{nom}\"\n"
        for nom, code in fichiers.items())
    return (
        "#!/bin/bash\n"
        "set -e\n"
        "source ~/.profile 2>/dev/null || true\n"
        f"{exports}"
        "BZ_SCRIPTS=$(mktemp -d /tmp/bz_XXXXXXXX)\n"
        f"{ecritures}"
        f"set +e\n{VM_PYTHON} \"$BZ_SCRIPTS/{entree}\" {arguments}\nCODE=$?\n"
        "rm -rf \"$BZ_SCRIPTS\"\n"
        "exit $CODE\n"
    )


def _option(nom: str, secrete: bool) -> dict:
    option = {"name": nom, "label": nom}
    if secrete:
        # valueExposed : seule facon d'utiliser la valeur dans un script ; Rundeck la masque
        # dans les journaux et ne la conserve pas dans l'historique d'execution. Pas de `hidden` :
        # Rundeck refuse une option cachee sans valeur par defaut (import du 2026-10-06).
        option.update({"secure": True, "valueExposed": True})
    return option


def yaml_job(run_id: str, fichiers: dict[str, str], entree: str, options: list[str], description: str,
             arguments: str = "", options_secretes: tuple[str, ...] = (),
             filtre_noeuds: str = RUNDECK_FILTRE_NOEUDS, delai_max: str = "2h") -> str:
    """`options` : noms des options (valeurs passees au lancement, jamais stockees dans le job)."""
    tous = list(options) + list(options_secretes)
    job = {
        "name": nom_job(run_id),
        "group": RUNDECK_GROUPE_JOBS,
        "description": description,
        "executionEnabled": True,
        "scheduleEnabled": False,
        "loglevel": "INFO",
        "timeout": delai_max,
        "nodeFilterEditable": False,
        "nodesSelectedByDefault": True,
        "nodefilters": {
            "dispatch": {"excludePrecedence": True, "keepgoing": False, "rankOrder": "ascending",
                         "successOnEmptyNodeFilter": False, "threadcount": "1"},
            "filter": filtre_noeuds,
        },
        "options": [_option(nom, nom in options_secretes) for nom in tous],
        "sequence": {
            "keepgoing": False,
            "strategy": "node-first",
            "commands": [{"description": description, "script": script_bash(fichiers, entree, tous, arguments)}],
        },
    }
    return yaml.safe_dump([job], sort_keys=False, allow_unicode=True)
