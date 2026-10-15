# [desc] Profondeur des sous-agents (process, terminal, web) bornee par `config.max_agent_depth`, et isolation demandee par le parent pour son enfant. [/desc]
"""Recursion des sous-agents : un agent peut lancer des sous-agents, qui en lancent d'autres,
jusqu'a `config["max_agent_depth"]` (defaut 4). Au-dela, l'outil `Agent` REFUSE avec un
message clair au lieu de laisser une recursion sans fin.

La profondeur d'un agent = celle de son PROCESS (variable `BOUZECODE_AGENT_DEPTH`, posee par
le parent au spawn : runner web, fenetre de terminal) + celle de sa boucle en process
(`config["_depth"]`, posee par `agent.loop` pour un sous-agent du `SubAgentManager`). Une
racine vaut 0 ; son enfant 1 ; etc.
"""
from __future__ import annotations

import os

ENV_PROFONDEUR = "BOUZECODE_AGENT_DEPTH"
PROFONDEUR_MAX_DEFAUT = 4

#: Isolations acceptees par l'outil `Agent` -> valeur attendue par le serveur.
ISOLATIONS = {"shared": "shared", "worktree": "worktree", "worktree_venv": "worktree+venv",
              "worktree+venv": "worktree+venv"}


def _entier(valeur) -> int:
    texte = str(valeur or "").strip()
    return int(texte) if texte.isdigit() else 0


def profondeur_courante(config: dict) -> int:
    return _entier(os.environ.get(ENV_PROFONDEUR)) + _entier(config.get("_depth", 0))


def profondeur_max(config: dict) -> int:
    return _entier(config.get("max_agent_depth")) or PROFONDEUR_MAX_DEFAUT


def refus_profondeur(config: dict) -> str | None:
    """Message d'erreur d'outil si un enfant depasserait la profondeur maximale, sinon None."""
    courante, maximum = profondeur_courante(config), profondeur_max(config)
    if courante + 1 <= maximum:
        return None
    return (f"Error: sous-agent REFUSE, aucun enfant n'a ete cree — profondeur maximale "
            f"atteinte : tu es a la profondeur {courante}, un enfant serait a {courante + 1} "
            f"(max_agent_depth = {maximum}). Fais ce morceau toi-meme, ou rends-le a ton "
            "parent dans ton rapport (Signaler s'il doit le savoir avant).")


def env_enfant(config: dict) -> dict[str, str]:
    """Variables a poser dans l'environnement d'un enfant lance dans un AUTRE process."""
    return {ENV_PROFONDEUR: str(profondeur_courante(config) + 1)}


def isolation_demandee(params: dict) -> tuple[str, str | None]:
    """(valeur serveur, erreur). Defaut `shared` : l'enfant peut encore demander son
    worktree lui-meme (outil Environment)."""
    brute = str(params.get("isolation") or "shared").strip().lower()
    if brute not in ISOLATIONS:
        return "", (f"Error: isolation inconnue {brute!r} — attendu shared, worktree ou "
                    "worktree_venv. Aucun enfant n'a ete cree.")
    return ISOLATIONS[brute], None
