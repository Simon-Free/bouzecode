# [desc] Barre des sous-agents du TUI (facon Claude Code) : installation dans le REPL interactif et texte d'aide /help. [/desc]
from __future__ import annotations

import sys

from bouzecode.backend.multi_agent.en_process import PRINCIPAL, RegistreAgents

AIDE = """Sous-agents (TUI interactif) :
  L'outil Agent lance ses sous-agents dans CE process ; ils s'affichent sous la saisie :
    ● main
    ◯ ▶ general-purpose  description   in 20.3k · fresh 12.3k · c-read 8.0k · out 1.2k · 0.04 $  1m 3s
  Une ligne trop large défile vers la gauche jusqu'à tout montrer, puis revient au début.
  Icônes : ▶ en cours · ? attend ta réponse · ✓ fini · ✗ erreur · ■ interrompu · ⚑ alerte
  ↓ (saisie vide)  aller dans la liste      ↑/↓  choisir un agent
  Entrée           ouvrir sa conversation ; ce que tu tapes ensuite lui est envoyé
                   (réponse à sa question, message lu à sa prochaine étape, ou reprise)
  Échap            revenir à main           x (liste) / Ctrl+X (vue)  interrompre l'agent
  Une question d'un sous-agent part aussi à son parent : il y répond ou te la pose (main au
  repos est réveillé pour la traiter) ; tu peux répondre avant lui depuis la vue de l'enfant.
  La barre reste visible pendant que main travaille (sous le spinner et le texte en cours) ;
  la navigation au clavier, elle, n'est possible que quand l'invite est ouverte : au repos,
  ou pendant que main attend ses sous-agents — un texte tapé alors dans
  la vue main lui parvient à sa prochaine étape.
  isolation=worktree|worktree_venv (choisie par le parent) : l'enfant travaille dans SON
  worktree (et venv), sans déplacer les autres ; impossible = refus explicite.
  Ancien mode, une fenêtre de terminal par sous-agent : /config subagents_window=true
  (effet au prochain lancement d'Agent)"""


def installer(state, config: dict):
    """Arme les sous-agents en process si le REPL est interactif ; rend l'ecran, ou None
    (agent web, entree non interactive). `subagents_window` est relu a chaque appel d'Agent."""
    if config.get("_web_agent_dir") or not sys.stdin.isatty():
        return None
    from .ecran import EcranAgents
    registre = RegistreAgents()
    registre.declarer_principal(state, config.get("model", ""))
    ecran = EcranAgents(registre, config)
    config["_tui_agents"] = registre
    config["_attente_lot"] = ecran.attente
    #  Un message tape dans la vue `main` pendant qu'elle travaille : lu a sa prochaine etape.
    config["_inbox_pop"] = lambda: registre.relever(PRINCIPAL)
    #  Ses sous-agents forment une flotte : Fleet et MessageAgent sont proposés au modèle.
    from bouzecode.backend.core.tool_registry import activer_flotte_locale
    activer_flotte_locale(True)
    #  Ce qu'un sous-agent ecrit sur stdout/stderr part dans SON journal, pas sous les yeux de
    #  main. Pose ICI, avant tout spinner / rich.Live : eux s'empilent par-dessus et se retirent
    #  proprement (ils ne retirent leur couche que si elle est au sommet).
    from bouzecode.backend.core.sortie_agent import installer as router_les_sorties
    router_les_sorties()
    #  Pendant les tours de main (invite fermee) : la barre en pied du spinner / du texte.
    from . import rendu
    from .clavier import Navigation
    vue_main = Navigation()
    import shutil
    rendu.definir_pied(lambda: [t for _style, t in rendu.lignes(
        registre, vue_main, shutil.get_terminal_size((100, 24)).columns - 1)])
    return ecran
