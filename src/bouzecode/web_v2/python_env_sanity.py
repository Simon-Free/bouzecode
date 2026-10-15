# [desc] Verdict « l'environnement Python des agents est-il intact ? » — garde les spawns comme api_sanity garde l'API. [/desc]
"""Refuser un spawn quand le venv des agents a été vidé.

`api_sanity` empêche de lancer un agent qui ne pourrait pas parler au provider.
Il manquait la garde symétrique, et plus élémentaire : un agent qui ne peut pas
IMPORTER de quoi parler au provider.

CE QUI ARRIVE, ET POURQUOI ÇA SE REPRODUIT
------------------------------------------
`uv sync` ne met pas un venv à jour : quand il le juge invalide, il le SUPPRIME
et le reconstruit. La suppression de `Lib/site-packages` réussit toujours ; la
reconstruction échoue tant qu'un agent CLI tient `Scripts/bouzecode.exe`
(erreur 32, fichier verrouillé). Il reste un arbre de sources importable sans
aucune dépendance — et le serveur, lui, continue de tourner avec ses modules
déjà chargés en mémoire. **Seuls les NOUVEAUX spawns meurent.**

Mesuré le 2026-08-24 : quatre agents CLI lancés entre 07:56 et 08:49 tenaient
l'exe. Un `uv` lancé par un agent de travail a vidé `site-packages` à 10:19, et
tout ce qui a été dispatché ensuite est mort sur
`ModuleNotFoundError: No module named 'anthropic'`, levé au fond de
`backend/agent/loop.py:339`. Côté interface : cinq tickets « planté » d'affilée,
sans que rien ne dise que la cause était commune, ni qu'elle était réparable en
une commande. C'est ce diagnostic-là qu'on rend immédiat.

CE QU'ON VÉRIFIE
----------------
Le serveur tourne dans LE MÊME venv que les agents qu'il lance : ce qu'il ne peut
pas résoudre, un agent frais ne le pourra pas non plus. Un `find_spec` relit le
disque à chaque appel (il ne se contente pas de `sys.modules`), donc il voit la
disparition même si le module est déjà chargé ici. Pas de sous-process, pas de
sonde réseau : quelques millisecondes.
"""
from __future__ import annotations

import importlib.util

#: Dépendances sans lesquelles un agent meurt avant son premier tour. `anthropic`
#: est importé par `backend/agent/loop.py` au premier appel LLM ; les deux autres
#: portent le serveur et le transport. Volontairement court : cette liste est une
#: alarme, pas un vérificateur d'installation.
REQUIRED_MODULES = ("anthropic", "httpx", "flask")

SPAWN_REFUSED_MESSAGE = (
    "environnement Python des agents incomplet — un spawn mourrait au démarrage. "
    "Cause habituelle : un `uv sync` a vidé `.venv/Lib/site-packages` sans pouvoir "
    "le reconstruire (`bouzecode.exe` verrouillé par un agent CLI). "
    "Réparation SANS reconstruire : `uv export --format requirements-txt "
    "--no-emit-project --no-hashes -o reqs.txt` puis `uv pip install --python "
    ".venv/Scripts/python.exe -r reqs.txt`."
)


def missing_modules() -> list[str]:
    """Les dépendances requises que l'interpréteur courant ne sait plus résoudre."""
    absents = []
    for name in REQUIRED_MODULES:
        try:
            found = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            absents.append(name)
    return absents



def require_python_env():
    """Garde des spawns : le refus 503 `env_indisponible` (`services.erreurs.Refus`) si l'env
    est amputé, sinon None — même forme que `api_sanity.require_api_sanity`, pour s'enchaîner
    avec lui (`api_tickets/garde.exiger`)."""
    absents = missing_modules()
    if not absents:
        return None
    from .services.erreurs import Refus

    return Refus("env_indisponible", SPAWN_REFUSED_MESSAGE, 503, missing=absents,
                 env_missing=True)
