# [desc] Sous-agents du TUI executes dans le meme process : registre partage, fil d'execution, chemin TUI de l'outil Agent. [/desc]
from .fiche import PRINCIPAL, FicheAgent
from .outil import agent_tui
from .registre import RegistreAgents

__all__ = ["PRINCIPAL", "FicheAgent", "RegistreAgents", "agent_tui"]
