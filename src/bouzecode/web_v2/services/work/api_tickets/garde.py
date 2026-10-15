# [desc] LA garde d'environnement (API joignable + venv des agents) avant tout spawn : un seul point, utilisé par les routes de lancement, l'agent libre et le Bureau. [/desc]
"""Avant tout lancement d'agent, deux sondes : l'API du fournisseur répond (`api_sanity`) et le
Python des agents a ses modules (`python_env_sanity`). Ce contrôle était recopié à quatre
endroits (constat §8) ; il n'existe plus qu'ici."""
from __future__ import annotations


def exiger() -> None:
    """Lève `Refus` (503 `env_indisponible`) si l'environnement interdit un spawn."""
    from .... import api_sanity, python_env_sanity
    refus = api_sanity.require_api_sanity() or python_env_sanity.require_python_env()
    if refus is not None:
        raise refus
