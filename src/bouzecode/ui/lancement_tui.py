# [desc] Prompt donne au lancement (`--prompt-file` ou positionnel, sans `-p`) dans une vraie console : il devient le 1er message du TUI interactif (barre des sous-agents comprise). [/desc]
"""`bouzecode --prompt-file x.txt` dans un terminal ouvrait autrefois le chemin NON interactif :
pas de barre des sous-agents, donc une fenetre de terminal par sous-agent, puis sortie.
Ici on decide si ce prompt doit plutot etre soumis comme si l'utilisateur l'avait tape."""
from __future__ import annotations

import sys


def prompt_soumis_au_tui(config: dict, initial_prompt: str | None) -> bool:
    """Vrai si le prompt de lancement part dans le REPL interactif. Restent sur l'ancien
    chemin : `-p` (et donc Rundeck, sous-agents en terminal), agent web, entree non console,
    reprises automatiques (`--resume-auto`, `--resume-pending`)."""
    if not initial_prompt:
        return False
    if config.get("_non_interactif") or config.get("_web_agent_dir"):
        return False
    if config.get("_resume_auto") or config.get("_resume_pending"):
        return False
    #  Meme critere que l'installation de la barre (barre_agents.installer) : sans elle, pas
    #  de sous-agents en process, et l'interet de ce chemin disparait.
    return sys.stdin.isatty()


def annoncer_le_premier_message(invite: str, message: str) -> None:
    """Le prompt de lancement n'a pas ete tape : on l'affiche apres l'invite, comme s'il
    l'avait ete (premiere ligne seulement si le fichier est long)."""
    lignes = message.strip().splitlines() or [""]
    suite = f"  (+{len(lignes) - 1} lignes)" if len(lignes) > 1 else ""
    print(invite + lignes[0] + suite)
