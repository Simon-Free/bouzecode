# [desc] Chemin TUI de l'outil Agent : lance le sous-agent en process, rend la main (background) ou l'attend en laissant l'utilisateur naviguer dans la barre, puis rend son rapport. [/desc]
"""`Agent` dans le TUI interactif.

Attendre = boucler sur `config["_attente_lot"]` (pose par le REPL sur la config du PRINCIPAL
seulement) : sur le fil du REPL, il ouvre la saisie avec la barre des agents pendant
l'attente ; ailleurs (un sous-agent qui attend ses propres enfants) il dort un instant.
"""
from __future__ import annotations

from .execution import lancer
from .fiche import PRINCIPAL, FicheAgent
from .registre import RegistreAgents


def agent_tui(params: dict, config: dict) -> str:
    from ..enfants import noter_enfant_local
    from ..appel_agent import _attend_l_enfant
    registre: RegistreAgents = config["_tui_agents"]
    params = dict(params)  # la note d'isolation enrichit le prompt : l'appel d'origine reste intact
    try:
        _verifier_le_type(params)
        atelier = preparer_atelier(params, config)
        fiche = lancer(registre, params, config, atelier)
    except ValueError as refus:
        return str(refus)
    racine = atelier.variables.get("BOUZECODE_WORKTREE_ROOT", "")
    if racine:  # ListAgentTasks et les gardes (ne pas detruire son worktree) le voient
        from ...tools.environment import _branch_of
        fiche.tache.worktree_path, fiche.tache.worktree_branch = racine, _branch_of(racine)
    noter_enfant_local(config, fiche.id)
    if not _attend_l_enfant(params):
        config["_bg_agent_launched"] = True
        return (f"Task ID: {fiche.id}\nName: {fiche.description}\nType: {fiche.type_agent}\n"
                "Status: running (en process, visible dans la barre du TUI)\n"
                "Lancé EN FOND — la main t'est rendue. Récupère son rapport avec "
                f"CheckAgentResult(task_id='{fiche.id}', wait=true) avant de clore.")
    if attendre([fiche], registre, config, "Agent") and fiche.actif:
        config["_bg_agent_launched"] = True
        return (f"Task ID: {fiche.id}\nName: {fiche.description}\n"
                "Attente INTERROMPUE : un message t'est arrivé (il suit ce résultat). "
                f"L'enfant {fiche.id} continue EN FOND ; récupère son rapport avec "
                f"CheckAgentResult(task_id='{fiche.id}', wait=true) avant de clore. "
                "Ne le redispatche pas.")
    return rapport(fiche)


def rapport(fiche: FicheAgent) -> str:
    if fiche.actif:
        return (f"[Agent: {fiche.description} ({fiche.type_agent})]\n\nError: attente "
                "abandonnée (tu as été interrompu) — l'enfant tourne encore, rien n'est livré.")
    return f"[Agent: {fiche.description} ({fiche.type_agent})]\n\n{fiche.resultat}"


def attendre(fiches: list[FicheAgent], registre: RegistreAgents, config: dict, outil: str) -> bool:
    """Jusqu'a ce que ces agents ne travaillent plus (fini, erreur, interrompu) — ou que
    l'agent qui attend soit lui-meme interrompu, ou qu'un message lui arrive (l'utilisateur
    reprend la discussion : les enfants continuent en fond). Rend True si c'est le courrier
    qui l'a reveille."""
    mon_id = config.get("_tui_moi") or PRINCIPAL

    def courrier() -> bool:
        return registre.a_du_courrier(mon_id)

    def fini() -> bool:
        return all(not f.actif for f in fiches) or courrier()

    hote = config.get("_attente_lot")
    moi = registre.fiche(config.get("_tui_moi") or "")
    while not fini():
        if moi is not None and moi.tache is not None and moi.tache._cancel_flag:
            return False
        if hote is not None:
            hote(fini, [outil])
        else:
            registre.attendre_changement(0.5)
    return any(f.actif for f in fiches) and courrier()


def _verifier_le_type(params: dict) -> None:
    """Type inconnu : refuse AVANT de provisionner quoi que ce soit."""
    nom = params.get("subagent_type", "") or ""
    if not nom:
        return
    from ...profiles.discovery import resolve_agent_profile
    if resolve_agent_profile(nom) is None:
        raise ValueError(f"Error: unknown subagent_type '{nom}'. "
                         "Use ListAgentTypes to see available types.")


def preparer_atelier(params: dict, config: dict):
    """Le dossier de travail de l'enfant, decide par le PARENT (`isolation`) : `shared` = celui du
    parent ; `worktree` = un worktree neuf (meme provisionnement que l'outil Environment) ;
    `worktree_venv` = idem + venv dedie. Echec = refus explicite, jamais un repli silencieux sur
    le dossier courant."""
    from ...core.dossier_agent import RACINE_WORKTREE, Atelier, actif, courant, dans
    from ..profondeur import isolation_demandee
    parent = actif()
    atelier = Atelier(dossier=courant(), variables=dict(parent.variables) if parent else {})
    isolation = isolation_demandee(params)[0] or "shared"
    if isolation == "shared":
        return atelier
    from ...tools import environment as outil_environment
    import uuid
    depot = outil_environment._repo_root(atelier.dossier)
    if not depot:
        raise ValueError(_refus_isolation(isolation, f"{atelier.dossier} n'est pas un dépôt git"))
    chemin, motif = outil_environment._provisionner_isole(depot, f"tui-{uuid.uuid4().hex[:8]}")
    if not chemin:
        raise ValueError(_refus_isolation(isolation, f"worktree NON obtenu : {motif}"))
    atelier.dossier = chemin
    atelier.variables[RACINE_WORKTREE] = chemin
    if isolation == "worktree+venv":
        with dans(atelier):
            rapport = outil_environment._venv(config)
        if not rapport.startswith("Venv dédié prêt"):
            raise ValueError(_refus_isolation(isolation, f"venv NON obtenu dans {chemin} : {rapport}"))
    params["prompt"] = (f"{params['prompt']}\n\n[Note de l'outil] Tu travailles dans TON worktree "
                        f"isolé {chemin} (branche {outil_environment._branch_of(chemin)}) : tes "
                        "Bash, Read/Write/Edit et chemins relatifs y pointent. Commite avant de "
                        "livrer ; ton parent intègre ta branche.")
    return atelier


def _refus_isolation(isolation: str, cause: str) -> str:
    return (f"Error: sous-agent REFUSÉ, aucun enfant n'a été créé — isolation '{isolation}' "
            f"impossible : {cause}. Corrige la cause, ou relance avec isolation='shared' si "
            "l'enfant n'écrit pas en parallèle d'un autre.")


# ── MessageAgent / Fleet sur la flotte en process du TUI ─────────────────────

def _trouver(registre: RegistreAgents, ident: str):
    ident = (ident or "").strip()
    return registre.fiche(ident) or next(
        (f for f in registre.sous_agents() if ident and ident == f.description), None)


def message_tui(params: dict, config: dict) -> str:
    """Meme chemin que la vue clavier : reponse a sa question, file de messages, ou reprise.
    `question=N` : reponse a SA question n°N (remontee par questions.py), refusee si deja prise."""
    from .questions import nom, repondre_a
    registre: RegistreAgents = config["_tui_agents"]
    fiche = _trouver(registre, params.get("ticket_id", ""))
    if fiche is None:
        return (f"Message NON transmis : aucun sous-agent '{params.get('ticket_id')}' "
                "(ids et noms : Fleet(action='list')).")
    if params.get("arreter"):
        arretes = registre.interrompre(fiche.id)
        return (f"Arrêt demandé à « {fiche.description} » ({len(arretes)} agent(s) avec ses "
                "descendants) : il s'arrête à sa prochaine étape, SANS livrer — ce qu'il n'a pas "
                "rendu par FinalAnswer ne compte pas. Message non transmis.")
    if params.get("interrompre") and fiche.actif:
        registre.interrompre(fiche.id)
        for _ in range(240):  # 2 min au plus : le tour en cours finit son outil
            if not fiche.actif:
                break
            registre.attendre_changement(0.5)
    moi = nom(registre, config.get("_tui_moi") or PRINCIPAL)
    if str(params.get("question") or "").strip().isdigit():
        verdict = repondre_a(registre, fiche, int(params["question"]), params["text"], moi)
        return f"Message pour « {fiche.description} » : {verdict}."
    return f"Message pour « {fiche.description} » : {registre.envoyer(fiche.id, params['text'], moi)}."


def flotte_tui(params: dict, config: dict) -> str:
    """`list` : les sous-agents en process (arbre, etat, conso, duree) ; `kill` : interrompt."""
    from .fiche import LIBELLES
    registre: RegistreAgents = config["_tui_agents"]
    action = (params.get("action") or "").strip().lower()
    if action == "kill":
        fiche = _trouver(registre, params.get("agent_id", ""))
        if fiche is None:
            return f"Fleet kill: agent introuvable ({params.get('agent_id')}). Utilise action='list'."
        arretes = registre.interrompre(fiche.id)
        return f"Agent {fiche.id} interrompu ({len(arretes)} agent(s) avec ses descendants)."
    if action != "list":
        return "Fleet: 'action' doit valoir 'list' ou 'kill'."
    fiches = registre.arbre()[1:]
    if not fiches:
        return "Aucun sous-agent dans ce TUI."
    lignes = [f"{len(fiches)} sous-agent(s) en process :"]
    for f in fiches:
        t, cout = f.tokens(), f.cout()
        conso = (f"in {t['entree'] + t['cache_lu']} out {t['sortie']}"
                 + (f" {cout:.2f} $" if cout is not None else ""))
        lignes.append(f"{'  ' * (f.profondeur - 1)}- {f.id} | {f.icone} "
                      f"{LIBELLES.get(f.etat, f.etat)} | {f.type_agent} | {f.description} | "
                      f"parent={f.parent_id or 'main'} | {conso} | {int(f.duree())} s")
    return "\n".join(lignes)
