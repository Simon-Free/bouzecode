# [desc] Les enfants de CET agent tels que le serveur les voit (tickets web + sous-agents en process), et les garde-fous qui en dépendent. [/desc]
"""Mes enfants, vus comme ils sont — pas comme mon process s'en souvient.

Un agent web délègue par l'outil `Agent`, qui crée un TICKET côté serveur : l'enfant est un
autre process, que le gestionnaire en mémoire (`SubAgentManager`) ne connaît pas. Toute
question sur mes enfants passe donc par le serveur (`/api/agents/<moi>/children`, lu frais),
complétée par les sous-agents en process du mode headless.

Trois consommateurs, une seule lecture :
  - ListAgentTasks / CheckAgentResult (voir) ;
  - Bash et Environment (ne pas détruire le worktree ou la branche d'un enfant vivant) ;
  - FinalAnswer (ne pas clore par-dessus un enfant qui travaille encore).

Échec de lecture (pas de serveur) : les outils de consultation le DISENT ; les garde-fous
laissent passer (ils ne savent pas, ils ne bloquent pas un agent hors serveur).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

_ENFANTS_URL = "http://127.0.0.1:5056/api/agents/{agent_id}/children"

#  Le relecteur de `close_review` est un sous-agent en process lancé ET attendu par la porte
#  de clôture elle-même : ce n'est pas un enfant que l'agent a délégué.
_NOMS_INTERNES = frozenset({"relecteur"})

_ACTIFS_LOCAUX = frozenset({"pending", "running"})


def mon_id(config: dict) -> str:
    """Mon id d'agent web (nom du dossier IPC), '' hors serveur."""
    ipc = config.get("_web_agent_dir") or os.environ.get("BOUZECODE_WEB_IPC_DIR") or ""
    return Path(ipc).stem if ipc else ""


def _fiche_locale(task) -> dict:
    actif = task.status in _ACTIFS_LOCAUX
    return {"ticket_id": task.id, "slug": "", "agent_id": task.id,
            "titre": task.name or task.prompt[:50], "etat": "en_cours" if actif else task.status,
            "libelle": "en cours" if actif else task.status, "actif": actif,
            "branche": task.worktree_branch or "", "worktree": task.worktree_path or "",
            "worktree_existe": bool(task.worktree_path) and os.path.isdir(task.worktree_path),
            "issue": "", "local": True}


def noter_enfant_local(config: dict, task_id: str) -> None:
    """Retient qu'un sous-agent en process est MON enfant. Le gestionnaire est un singleton de
    process : ses tâches mêlent mes enfants, ceux de mes enfants et, en test, d'autres
    conversations — un enfant ne doit pas voir ses frères comme les siens."""
    config.setdefault("_enfants_locaux", []).append(task_id)


def _locaux(config: dict) -> list[dict]:
    from .gestionnaire import get_agent_manager
    taches = get_agent_manager().tasks
    return [_fiche_locale(taches[i]) for i in config.get("_enfants_locaux") or ()
            if i in taches and taches[i].name not in _NOMS_INTERNES]


def _web(config: dict) -> list[dict]:
    moi = mon_id(config)
    if not moi:
        return []
    from .client_tickets import _get_json, _sur_le_serveur
    get = config.get("_web_get") or _get_json
    reponse = get(_sur_le_serveur(_ENFANTS_URL.format(agent_id=moi))) or {}
    return list(reponse.get("children") or [])


def lire(config: dict) -> tuple[list[dict], str]:
    """(fiches, erreur). `erreur` non vide = le serveur n'a pas pu répondre : la liste est
    alors INCOMPLÈTE, et le dire vaut mieux qu'un « aucun enfant » faux."""
    try:
        web = _web(config)
    except Exception as exc:  # noqa: BLE001 — réseau, 404, JSON : même conséquence
        return _locaux(config), f"{type(exc).__name__}: {exc}"
    return _locaux(config) + web, ""


def actifs(config: dict) -> list[dict]:
    """Enfants dont le travail peut encore changer. Lecture impossible → [] (on ne bloque pas
    sur ce qu'on ne sait pas)."""
    fiches, _erreur = lire(config)
    return [f for f in fiches if f.get("actif")]


def ligne(f: dict) -> str:
    """Une ligne lisible : qui, lancé quand et sous quel nom, état, branche, worktree, objectif.

    « lancé par toi » est TOUJOURS écrit : ces fiches sont, par construction, celles des tickets
    dont l'agent est le parent. Essai du 2026-09-25 : la racine a écrit à a139daa2 « Tu n'as
    pas été lancé par moi » — elle l'avait lancé au tour 68, rien de ce qu'elle relisait ne
    le disait."""
    ou = f.get("worktree") or "-"
    if f.get("worktree") and not f.get("worktree_existe"):
        ou += " (supprimé)"
    agent = f.get("agent_id") or "-"
    return (f"{f.get('ticket_id')} | {lance_par_toi(f)} | agent {agent} | "
            f"{f.get('libelle') or f.get('etat')} | branche {f.get('branche') or '-'} | "
            f"worktree {ou} | objectif : {f.get('objectif') or f.get('titre') or ''}")


def lance_par_toi(f: dict) -> str:
    lancement = f.get("lancement") or {}
    quand = f" au tour {lancement['tour']}" if lancement.get("tour") else ""
    nom = f" sous le nom « {lancement['nom']} »" if lancement.get("nom") else ""
    return f"lancé par toi{quand}{nom}"


#  États où l'enfant TRAVAILLE : l'attendre a un sens. Un enfant qui attend une réponse, lui,
#  n'avancera pas tant qu'on ne lui répond pas.
_TRAVAILLE = frozenset({"lancement", "en_cours"})


def travaille(f: dict) -> bool:
    return f.get("etat") in _TRAVAILLE or (bool(f.get("local")) and bool(f.get("actif")))


def comment_faire(f: dict) -> str:
    """Les gestes qui libèrent un enfant actif : l'attendre (ou lui répondre), ou l'arrêter."""
    tid = f.get("ticket_id")
    if f.get("local"):
        return (f"attends-le avec CheckAgentResult(task_id='{tid}', wait=true), ou arrête-le "
                f"avec CheckAgentResult(task_id='{tid}', arreter=true)")
    arreter = f"arrête-le avec Fleet(action='kill', agent_id='{f.get('agent_id')}')"
    if f.get("etat") == "attend_reponse":
        return (f"il attend une réponse : réponds-lui avec MessageAgent(ticket_id='{tid}', "
                f"text=…), ou {arreter}")
    return f"attends-le avec CheckAgentResult(task_id='{tid}', wait=true), ou {arreter}"


# ── Garde-fou : ne pas détruire l'atelier d'un enfant vivant ─────────────────

#  Les commandes qui suppriment un worktree ou une branche. Une commande qui ne détruit rien
#  ne coûte aucune requête au serveur.
_DESTRUCTION_RE = re.compile(
    r"\bgit\b[^\n;&|]*\b(?:worktree\s+remove|branch\s+(?:-[a-zA-Z]*[dD]\b|--delete\b))"
    r"|\brm\s+-[a-zA-Z]*r",
)


def detruit_peut_etre(commande: str) -> bool:
    return bool(_DESTRUCTION_RE.search(commande or ""))


def _vise(commande: str, f: dict) -> bool:
    """La commande nomme-t-elle le worktree ou la branche de cet enfant ?"""
    cibles = [f.get("worktree") or "", f.get("branche") or ""]
    return any(c and c in commande for c in cibles)


def refus_destruction(commande: str, config: dict) -> str:
    """Message de refus si `commande` supprime le worktree ou la branche d'un enfant actif."""
    if not detruit_peut_etre(commande):
        return ""
    vises = [f for f in actifs(config) if _vise(commande, f)]
    if not vises:
        return ""
    return _refus("supprimer son worktree ou sa branche détruirait son travail en cours", vises)


def refus_si_enfants_actifs(geste: str, config: dict) -> str:
    """Refus d'un geste (intégrer, ranger) tant qu'un enfant travaille encore."""
    vivants = actifs(config)
    return _refus(geste, vivants) if vivants else ""


def _refus(pourquoi: str, vivants: list[dict]) -> str:
    noms = "\n".join(f"- {ligne(f)} → {comment_faire(f)}" for f in vivants)
    return (f"Error: refusé — enfant(s) encore actif(s), {pourquoi} :\n{noms}\n"
            "Attends-le(s) ou arrête-le(s) d'abord, puis refais ce geste.")


# ── Attendre un enfant ───────────────────────────────────────────────────────

def attendre(f: dict, config: dict) -> str:
    """Bloque jusqu'à ce que l'enfant rende la main ; renvoie son compte rendu."""
    from . import attente_web, gestionnaire
    registre = config.get("_tui_agents")
    fiche_tui = registre.fiche(f["ticket_id"]) if registre is not None and f.get("local") else None
    if fiche_tui is not None:  # sous-agent du TUI : l'attente laisse naviguer dans la barre
        from .en_process.outil import attendre as attendre_tui
        if attendre_tui([fiche_tui], registre, config, "CheckAgentResult") and fiche_tui.actif:
            return ("attente INTERROMPUE : un message t'est arrivé (il suit ce résultat) ; "
                    "l'enfant continue.")
        return f"{fiche_tui.tache.status}\n{fiche_tui.resultat or '(pas de résultat)'}"
    if f.get("local"):
        task = gestionnaire.get_agent_manager().wait(f["ticket_id"],
                                                    timeout=attente_web._WAIT_TIMEOUT)
        if task is None:
            return "introuvable"
        if task.status in _ACTIFS_LOCAUX:
            return (f"toujours actif après {int(attente_web._WAIT_TIMEOUT)} s d'attente — il "
                    f"EXISTE et tourne : ne le relance pas ; "
                    f"{comment_faire(_fiche_locale(task))}.")
        return f"{task.status}\n{task.result or '(pas de résultat)'}"
    attente = config.get("_web_wait_verdict") or (lambda tid, _slug: attendre_web(tid, config))
    try:
        return attente(f["ticket_id"], f.get("slug") or "")
    except attente_web.AttenteInterrompue:
        return ("attente INTERROMPUE : un message t'est arrivé (il suit ce résultat) ; "
                "l'enfant continue.")
    except Exception as exc:  # noqa: BLE001 — serveur illisible : l'enfant existe toujours
        return (f"attente impossible ({type(exc).__name__}: {exc}) ; l'enfant EXISTE, "
                "relis-le avec CheckAgentResult avant de décider.")


def attendre_web(ticket_id: str, config: dict) -> str:
    """L'attente d'un enfant web, pour CheckAgentResult(wait=true) comme pour Agent en mode
    pause : relire mes enfants (frais) jusqu'à ce que celui-ci ne TRAVAILLE plus."""
    from . import attente_web
    if not mon_id(config):
        raise ValueError("agent hors serveur : impossible de relire ses enfants")
    return attendre_ticket(ticket_id, lambda: _lire_ou_lever(config),
                           reveil=attente_web._reveil(config))


def _lire_ou_lever(config: dict) -> list[dict]:
    fiches, erreur = lire(config)
    if erreur:
        raise RuntimeError(f"enfants du serveur illisibles : {erreur}")
    return fiches


def _fiche_de(ticket_id: str, fiches: list[dict]) -> dict:
    courant = next((x for x in fiches if x.get("ticket_id") == ticket_id), None)
    if courant is None:
        raise LookupError(f"{ticket_id} n'est pas parmi mes enfants")
    return courant


def attendre_ticket(ticket_id: str, lire_fiches, *, sleep=None, now=None,
                    timeout: float | None = None, reveil=None) -> str:
    """Sonde `lire_fiches()` jusqu'à ce que l'enfant ne TRAVAILLE plus : fini, arrêté, ou
    bloqué sur une question (à laquelle seul son parent ou l'utilisateur peut répondre).

    UNE règle (`travaille`, sur la fiche du serveur) pour l'attente comme pour les garde-fous :
    essai du 2026-09-25, l'attente disait l'enfant 40ea29e4 « fini, livré » pendant que les
    garde-fous le voyaient actif. `sleep` / `now` / `timeout` sont injectables (tests)."""
    import time
    from . import attente_web
    sleep, now = sleep or time.sleep, now or time.monotonic
    timeout = attente_web._WAIT_TIMEOUT if timeout is None else timeout
    fin = now() + timeout
    while now() < fin:
        courant = _fiche_de(ticket_id, lire_fiches())
        if not travaille(courant):
            return f"{ligne(courant)}\nIssue : {courant.get('issue') or '-'}"
        if attente_web._dormir(sleep, reveil):
            raise attente_web.AttenteInterrompue(ticket_id)
    return (f"{ticket_id} toujours actif après {int(timeout)} s d'attente — il EXISTE et "
            "tourne : ne le redispatche pas. Tu seras ré-invoqué avec son verdict quand il "
            "aura terminé.")


# ── Clôture : pas par-dessus un enfant qui travaille ─────────────────────────

#  Pour un manager, clore son tour EST la façon d'attendre : `wake.process_wakes` le réveille
#  avec le digest de ses enfants (il ne livre ni n'intègre rien lui-même). L'assistant du Bureau
#  aussi : les tâches qu'il lance lui sont rattachées (pour qu'il soit réveillé à leur fin ou à
#  leur question), et il doit pouvoir rendre la main à l'humain pendant qu'elles tournent.
_CLORE_C_EST_ATTENDRE = frozenset({"manager", "monitor", "bureau-assistant"})

#  Plafond absolu : un enfant bloqué sur une question que personne ne tranche ferait refuser
#  indéfiniment. Au-delà, la clôture passe, mais la réponse livrée NOMME les enfants actifs
#  (même principe que les parcours non prouvés : jamais une anomalie silencieuse).
MAX_REFUS_CLOTURE = 6


def _clore_c_est_attendre(config: dict) -> bool:
    profil = config.get("_task_classification_result") or config.get("_agent_type") or ""
    return str(profil).strip().lower() in _CLORE_C_EST_ATTENDRE


def cloture_en_attente(config: dict) -> bool:
    """Cette clôture est-elle une ATTENTE d'enfants encore actifs (manager, monitor) ? Seul un
    tel agent sera relancé par le compte rendu de ses enfants ; un autre clôt pour de bon.
    Lecture impossible : on suppose l'attente (mieux vaut un réveil de trop qu'un manager
    oublié)."""
    if not _clore_c_est_attendre(config):
        return False
    fiches, erreur = lire(config)
    return bool(erreur) or any(f.get("actif") for f in fiches)


def refus_de_cloture(config: dict) -> str:
    """Chaîne vide si l'agent peut clore ; sinon le refus. Dès la PREMIÈRE tentative, le
    harnais attend lui-même les enfants qui travaillent et rend leurs comptes rendus : l'agent
    les intègre et rappelle FinalAnswer — un tour de refus au lieu de trois.

    Session B4 (TUI, 2026-10-14) : trois enfants lancés en fond, puis FinalAnswer aussitôt
    (« je reprendrai à la fin de chacun d'eux ») — un agent normal n'est JAMAIS réveillé par
    ses enfants ; refusé deux fois avant que le harnais n'attende. Un enfant qui attend une
    réponse, lui, ne s'attend pas : le refus dit comment lui répondre ou l'arrêter."""
    if _clore_c_est_attendre(config):
        return ""
    vivants = actifs(config)
    if not vivants:
        return ""
    refus = int(config.get("_refus_enfants_actifs", 0)) + 1
    config["_refus_enfants_actifs"] = refus
    if refus > MAX_REFUS_CLOTURE:
        config["_enfants_actifs_a_la_cloture"] = [ligne(f) for f in vivants]
        return ""
    if not any(travaille(f) for f in vivants):
        noms = "\n".join(f"- {ligne(f)} → {comment_faire(f)}" for f in vivants)
        return ("CLÔTURE REFUSÉE — tu as des enfants encore actifs, qui attendent une réponse ; "
                f"clore maintenant livrerait sans leur travail :\n{noms}\n"
                "Réponds-leur (ou arrête-les), intègre ou écarte leur résultat, puis rappelle "
                "FinalAnswer.")
    comptes_rendus = "\n\n".join(f"### {f.get('ticket_id')} ({f.get('titre') or ''})\n"
                                 f"{attendre(f, config) if travaille(f) else comment_faire(f)}"
                                 for f in vivants)
    return (f"CLÔTURE DIFFÉRÉE — {len(vivants)} sous-agent(s) encore actif(s) : le harnais "
            f"les a attendus pour toi. Leurs comptes rendus :\n\n{comptes_rendus}"
            "\n\nIntègre ou écarte leur travail en connaissance de cause, puis rappelle "
            "FinalAnswer.")


def avouer_enfants_actifs(answer: str, config: dict) -> str:
    """Plafond de refus atteint : la clôture passe, mais l'utilisateur doit le LIRE."""
    restes = config.get("_enfants_actifs_a_la_cloture")
    if not restes:
        return answer
    return (answer + "\n\n⚠️ Clôture forcée alors que des sous-agents étaient encore actifs "
            "(leur travail peut arriver après cette réponse) :\n- " + "\n- ".join(restes))
