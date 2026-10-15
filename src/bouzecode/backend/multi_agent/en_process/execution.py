# [desc] Lance un sous-agent du TUI dans un fil du MEME process (boucle agent.run), suit ses evenements dans le registre, route messages/questions/permissions, et conclut : seul FinalAnswer livre. [/desc]
"""Un sous-agent du TUI = un fil, une `AgentState` (sa conversation), une fiche du registre.

Le fil est un `threading.Thread` dedie, pas le pool du `SubAgentManager` : un parent qui
attend ses enfants occupe un fil, et un pool borne se bloquerait des la profondeur 2. La
tache est quand meme inscrite au gestionnaire (`mgr.tasks`), pour que ListAgentTasks,
CheckAgentResult et la garde de cloture de FinalAnswer la voient comme tout enfant en process.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import Future

from .fiche import ANNULE, EN_COURS, ERREUR, FINI, PRINCIPAL, FicheAgent
from .registre import RegistreAgents


def lancer(registre: RegistreAgents, params: dict, config: dict, atelier=None) -> FicheAgent:
    """Cree la fiche et demarre le fil ; leve ValueError (message d'outil) si refus.
    `atelier` : dossier et variables PROPRES a l'enfant (core.dossier_agent), jamais un chdir."""
    from ...core.tool_registry import inherit_private
    from ..gestionnaire import get_agent_manager

    subagent_type = params.get("subagent_type", "") or ""
    eff_config = inherit_private(config, {k: v for k, v in config.items() if not k.startswith("_")})
    if params.get("model"):
        eff_config["model"] = params["model"]
    systeme = config.get("_system_prompt", "You are a helpful assistant.")
    if subagent_type:
        from ...profiles.discovery import resolve_agent_profile
        profil = resolve_agent_profile(subagent_type)
        if profil is None:
            raise ValueError(f"Error: unknown subagent_type '{subagent_type}'. "
                             "Use ListAgentTypes to see available types.")
        systeme = get_agent_manager()._apply_profile(profil, eff_config, systeme)

    profondeur = int(config.get("_depth", 0) or 0) + 1
    tache = get_agent_manager().create_task(params["prompt"], depth=profondeur - 1,
                                            name=params.get("name", "") or "")
    tache.agent_type = subagent_type or "general-purpose"
    tache.model = eff_config.get("model", "")
    tache.status = "running"
    from ...agent.state import AgentState
    fiche = registre.ajouter(FicheAgent(
        id=tache.id, parent_id=config.get("_tui_moi") or PRINCIPAL, type_agent=tache.agent_type,
        description=_description(params), modele=tache.model, profondeur=profondeur,
        state=AgentState(), tache=tache))
    atelier = _atelier_avec_journal(atelier, fiche)
    #  Ce que l'enfant herite du TUI : le registre (recursion), son identite, sa boite aux
    #  lettres (relevee aux frontieres de lot par agent.loop), et la voie de ses questions.
    eff_config.update({
        "_tui_agents": registre, "_tui_moi": tache.id, "close_requires_final_answer": True,
        "_atelier": atelier,
        "_inbox_pop": lambda: registre.relever(tache.id),
        #  Sa question part a son PARENT (qui y repond ou la relaie) ET reste dans la barre.
        "_tui_question": lambda q, o=None, libre=True: registre.poser_question(
            tache.id, q, o, libre, au_parent=True),
    })
    fiche.reprendre = lambda message: _demarrer(registre, fiche, message, eff_config, systeme)
    _demarrer(registre, fiche, params["prompt"], eff_config, systeme)
    return fiche


def _atelier_avec_journal(atelier, fiche: FicheAgent):
    """Tout enfant porte un atelier (dossier du parent a defaut) et SA sortie : ce qu'il
    ecrit sur stdout/stderr va dans `~/.bouzecode/logs/sous-agent-<id>.log` (core/sortie_agent),
    jamais dans le terminal du principal."""
    from ...core import config as module_config
    from ...core.dossier_agent import Atelier, courant
    from ...core.sortie_agent import JournalAgent
    atelier = atelier if atelier is not None else Atelier(dossier=courant())
    atelier.sortie = JournalAgent(module_config.LOGS_DIR / f"sous-agent-{fiche.id}.log")
    fiche.journal = atelier.sortie
    #  Interrompre l'enfant (Ctrl+C / x / Ctrl+X dans la barre) tue aussi son Bash en cours :
    #  sans cela il restait fige dans le subprocess jusqu'a sa fin (tools/ops/shell_search).
    atelier.annule = lambda: fiche.tache is not None and bool(fiche.tache._cancel_flag)
    return atelier


def _description(params: dict) -> str:
    nom = str(params.get("name") or "").strip()
    if nom:
        return nom
    premiere = str(params.get("prompt") or "").strip().splitlines()
    return (premiere[0] if premiere else "")[:80]


def _demarrer(registre, fiche: FicheAgent, message: str, config: dict, systeme: str) -> None:
    tache = fiche.tache
    tache._cancel_flag = False
    tache.status = "running"
    tache._future = Future()
    registre.changer(fiche.id, etat=EN_COURS, fin=None, resultat="")
    threading.Thread(target=_executer, args=(registre, fiche, message, config, systeme),
                     name=f"sous-agent-{fiche.id}", daemon=True).start()


def _executer(registre, fiche: FicheAgent, message: str, config: dict, systeme: str) -> None:
    from ...core.dossier_agent import dans
    #  L'atelier vaut pour TOUT le fil, pas seulement pendant ses outils : la boucle charge
    #  ses skills (prompt systeme) et avertit hors de tout appel d'outil — sans lui, elle le
    #  faisait dans le dossier du principal et dans son terminal.
    with dans(config.get("_atelier")):
        _boucler(registre, fiche, message, config, systeme)


def _boucler(registre, fiche: FicheAgent, message: str, config: dict, systeme: str) -> None:
    from .. import task as module_tache
    from ...tools.interaction import DeferredChecks
    tache, state = fiche.tache, fiche.state
    differe = ""
    try:
        while message and not tache._cancel_flag:
            state.final_answer = ""  # une reprise ne relivre jamais la reponse d'avant
            for evenement in module_tache._agent_run(message, state, config, systeme,
                                                     depth=fiche.profondeur,
                                                     cancel_check=lambda: tache._cancel_flag):
                _observer(registre, fiche, evenement)
            #  Courrier arrive apres la derniere frontiere de lot : il relance un tour.
            message = "\n\n".join(registre.relever(fiche.id))
    except DeferredChecks as clos:
        state.final_answer = state.final_answer or clos.answer
        differe = "\n\n(vérifications différées NON exécutées en sous-agent TUI)"
    except Exception as exc:  # le parent doit lire l'echec, jamais un silence
        state.close_reason = state.close_reason or "exception"
        state.close_detail = f"{type(exc).__name__}: {exc}"
    _conclure(registre, fiche, differe)


def _observer(registre, fiche: FicheAgent, evenement) -> None:
    from ...agent.state import PermissionRequest, ToolEnd, ToolStart, TurnDone
    if isinstance(evenement, ToolStart):
        #  La progression du run precedent reste lisible dans l'onglet jusqu'au prochain outil.
        registre.changer(fiche.id, activite=evenement.name, progression="")
    elif isinstance(evenement, ToolEnd):
        registre.changer(fiche.id, activite="")
        if evenement.name == "Signaler" and not str(evenement.result).startswith("Error"):
            entrees = evenement.inputs or {}
            registre.signaler(fiche.id, entrees.get("gravite", "info"), entrees.get("titre", ""))
    elif isinstance(evenement, PermissionRequest):
        reponse = registre.poser_question(fiche.id, f"Autoriser : {evenement.description} ?",
                                          ["oui", "non"], False)
        evenement.granted = reponse.strip().lower() in ("oui", "o", "y", "yes", "1")
    elif isinstance(evenement, TurnDone):
        registre.changer(fiche.id)  # tokens a jour : la barre se redessine
        _sauver(fiche)


def _conclure(registre, fiche: FicheAgent, differe: str) -> None:
    """FinalAnswer est la SEULE fin qui livre ; toute autre fin est un echec explicite."""
    tache, state = fiche.tache, fiche.state
    if tache._cancel_flag:
        etat, statut = ANNULE, "cancelled"
        resultat = "Error: sous-agent interrompu par l'utilisateur — rien n'est livré."
    elif state.final_answer:
        etat, statut, resultat = FINI, "completed", state.final_answer + differe
    else:
        etat, statut = ERREUR, "failed"
        cause = state.close_detail or state.close_reason or "fin sans motif"
        resultat = (f"Error: le sous-agent s'est arrêté SANS FinalAnswer ({cause}) — rien "
                    "n'est livré. Ne considère pas ce travail comme fait.")
    tache.status, tache.result = statut, resultat
    tache.input_tokens = state.total_input_tokens
    tache.output_tokens = state.total_output_tokens
    tache.cache_read_tokens = state.total_cache_read_tokens
    tache.cache_creation_tokens = state.total_cache_creation_tokens
    _sauver(fiche)
    registre.changer(fiche.id, etat=etat, resultat=resultat, fin=time.time(), activite="")
    tache._future.set_result(tache)
    #  Message depose entre la derniere releve et ce changement d'etat : il relance l'agent.
    restants = registre.relever(fiche.id)
    if restants and etat != ANNULE:
        fiche.reprendre("\n\n".join(restants))


def _sauver(fiche: FicheAgent) -> None:
    """La session du sous-agent sur disque, a cote des autres (daily/<date>/session_*.json)."""
    from datetime import datetime
    from ...commands.session.session import _save_session_checkpoint
    from ...core import config as module_config
    if not fiche.state.messages:
        return
    if not fiche.chemin_session:
        jour = module_config.DAILY_DIR / datetime.now().strftime("%Y-%m-%d")
        fiche.chemin_session = str(jour / f"session_{datetime.now():%H%M%S}_{fiche.id}.json")
    _save_session_checkpoint(fiche.state, fiche.chemin_session, fiche.id, fiche.chemin_session,
                             model=fiche.modele)
