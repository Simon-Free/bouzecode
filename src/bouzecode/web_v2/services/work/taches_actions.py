# [desc] Gestes sur une tâche du Bureau : lancer, relancer (itérations), arrêter, changer d'état, intégrer un passage. [/desc]
"""Les gestes d'une tâche (SPEC §4.6, §4.7), partagés par les routes HTTP et par les outils de
l'assistant — un seul endroit où les règles sont vérifiées :

* **aucun dépôt deviné** : dépôt demandé, sinon celui de la tâche, sinon le 1er du chantier,
  sinon refus `depot_requis` (le repli silencieux sur `demo` a disparu) ;
* **un échec de lancement ne ment pas** : la tâche reste brouillon et l'erreur remonte ;
* **jamais deux agents actifs sur la même tâche** ;
* **une itération n'oublie rien** : le prompt d'un nouveau passage contient le récap de chaque
  passage précédent et tous les retours humains.

Chaque refus lève `Refus(code, message, status, **extra)` ; la route le traduit en HTTP.
"""
from __future__ import annotations

import threading

from bouzecode.web_v2.services.horodatage import age_s, maintenant

from .. import erreurs
from . import lexique
from . import micros as micros_service


class Refus(erreurs.Refus):
    """Un refus d'un geste sur une tâche : 400 par défaut. Les routes le sérialisent."""

    def __init__(self, code: str, message: str, status: int = 400, **details):
        super().__init__(code, message, status, **details)


#  Le lancement n'est PAS rejouable : deux requêtes simultanées doivent produire un seul agent
#  (serveur mono-process, multi-thread).
VERROU_LANCEMENT = threading.Lock()


def _micro_ou_refus(micro_id: str) -> dict:
    micro = micros_service.get_micro(micro_id)
    if micro is None:
        raise Refus("tache_inconnue", f"tâche {micro_id} inconnue", 404)
    return micro


def _suggestions() -> list[dict]:
    from . import projects
    return [{"slug": p["slug"], "name": p["name"]} for p in projects.list_projects()]


def resoudre_depot(micro: dict, demande: str = "") -> str:
    """Le dépôt du lancement, jamais deviné. Lève `Refus` si aucun n'est connu ou valide."""
    from . import projects, taches_vue
    slug = (demande or "").strip() or taches_vue.projet_defaut(micro)
    if not slug:
        raise Refus("depot_requis",
                    "Choisis un dépôt pour cette tâche : aucun n'est indiqué sur la tâche ni sur "
                    "son chantier.", 400, suggestions=_suggestions())
    if projects.find(slug) is None:
        raise Refus("depot_inconnu",
                    f"Le dépôt « {slug} » n'est pas (ou plus) enregistré. Choisis un dépôt de "
                    f"la liste ou enregistre-le.", 400, suggestions=_suggestions())
    return slug


# -------------------------------------------------------------------------- passages


def passages(micro: dict) -> list[dict]:
    """Passages de la tâche, du plus récent au plus ancien (même calcul que le Bureau)."""
    from . import taches_vue
    ctx = taches_vue.contexte()
    liens = [l for l in (micro.get("tickets") or []) if l.get("ticket_id")]
    vues = [taches_vue.passage(ctx, str(l.get("slug") or ""), str(l["ticket_id"]),
                               str(l.get("at") or ""), n) for n, l in enumerate(liens, start=1)]
    vues.reverse()
    return vues


def agent_actif(micro: dict) -> dict | None:
    """Le passage dont l'agent occupe encore la tâche (tourne, prépare, attend), sinon None."""
    for vue in passages(micro):
        if vue["etat"] in lexique.ETATS_ACTIFS:
            return vue
    return None


# ---------------------------------------------------------------------------- préciser

#  L'agent du dernier passage reçoit la précision s'il occupe la tâche (tourne, attend une
#  réponse, attend ses sous-agents) ou s'il est au repos, conversation reprenable : il est alors
#  RÉVEILLÉ avec elle. Planté ou disparu : la précision reste au brief, rien n'est relancé.
_ETATS_JOIGNABLES = lexique.ETATS_ACTIFS | {"idle", "finished"}
_ETATS_ENFANT_JOIGNABLE = ("running", "starting", "idle", "awaiting_input",
                           "awaiting_plan_validation")


def _agent_destinataire(micro: dict) -> str:
    if (micro.get("etat") or "") in ("faite", "abandonnee"):
        return ""
    dernier = next(iter(passages(micro)), {})
    return str(dernier.get("agent_id") or "") if dernier.get("etat") in _ETATS_JOIGNABLES else ""


def _sous_agents_joignables(agent_id: str) -> list[str]:
    """Les descendants de `agent_id` qui peuvent encore lire un message (tous niveaux)."""
    from ...runtime.runner import agent_registre
    from ..sessions import store
    enfants: dict[str, list] = {}
    for agent in agent_registre.list_agents():
        enfants.setdefault(agent.parent, []).append(agent)
    trouves, a_voir = [], [agent_id]
    while a_voir:
        for enfant in enfants.get(a_voir.pop(), []):
            a_voir.append(enfant.agent_id)
            if store.agent_status(enfant).get("state") in _ETATS_ENFANT_JOIGNABLE:
                trouves.append(enfant.agent_id)
    return trouves


def _transmettre_precision(precision: dict, agent_id: str, texte: str, interrompre: bool,
                           origine: str) -> dict:
    """Trace la transmission AVANT de livrer : une livraison immédiate la marque lue."""
    from . import file_messages
    message_id = file_messages.nouvel_id()
    micros_service.enregistrer_transmission(precision["id"], agent_id, message_id,
                                            "interruption" if interrompre else "ajout")
    resultat = file_messages.transmettre(agent_id, texte, interrompre, origine,
                                         precision["id"], message_id)
    if resultat.get("reason") == "agent_missing":
        micros_service.marquer_transmission(message_id, "non_lue")
    return {"agent_id": agent_id, **resultat}


#  Fenêtre dans laquelle la même précision, renvoyée, est un DOUBLON et non un rappel voulu.
FENETRE_DOUBLON_S = 600


def _maintenant():
    return maintenant()


def _doublon_recent(micro: dict, texte: str) -> dict | None:
    """La dernière précision de la tâche si elle dit EXACTEMENT la même chose, il y a peu.

    Assistant du Bureau, 2026-09-24 : sa clôture refusée (FinalAnswer dans le lot de
    `Taches(preciser)`), il a renvoyé la précision — le brief la portait deux fois et l'agent
    l'a reçue deux fois. Un renvoi identique dans la fenêtre n'est ni ajouté ni retransmis."""
    derniere = next(iter(sorted(micro.get("precisions") or [],
                                key=lambda p: p.get("rang") or 0, reverse=True)), None)
    if derniere is None or " ".join(str(derniere.get("texte") or "").split()) != " ".join(texte.split()):
        return None
    age = age_s(derniere.get("created_at"), _maintenant())
    return derniere if age is not None and 0 <= age <= FENETRE_DOUBLON_S else None


def preciser(micro_id: str, texte: str, auteur: str = "humain", transmettre: bool = False,
             interrompre: bool = False, sous_agents: bool = False) -> dict:
    """Ajoute une précision au brief (section « Précisions ajoutées » : toute relance future la
    reçoit) et, si `transmettre`, la donne à l'agent qui travaille sur la tâche — en AJOUT (lue
    à sa prochaine frontière de tour) ou en INTERRUPTION (tour coupé, il repart avec). Avec
    `sous_agents`, ses sous-agents encore joignables la reçoivent aussi (en ajout)."""
    micro = _micro_ou_refus(micro_id)
    texte = str(texte or "").strip()
    if not texte:
        raise Refus("texte_requis", "Une précision vide n'apporte rien.")
    doublon = _doublon_recent(micro, texte)
    if doublon is not None:
        return {"ok": True, "doublon": True, "precision": doublon, "transmis": [],
                "micro": micro}
    precision = micros_service.add_precision(micro_id, texte, auteur=auteur or "humain",
                                             statut="validee")
    principal = _agent_destinataire(micro) if transmettre else ""
    origine = "assistant" if auteur == "assistant" else "bureau"
    transmis = []
    if principal:
        transmis.append(_transmettre_precision(precision, principal, texte, interrompre, origine))
        for enfant in _sous_agents_joignables(principal) if sous_agents else []:
            transmis.append(_transmettre_precision(precision, enfant, texte, False, origine))
    return {"ok": True, "precision": precision, "transmis": transmis,
            "micro": micros_service.get_micro(micro_id)}


# ------------------------------------------------------------------------------ prompt


def _puces(titre: str, textes: list[str]) -> str:
    return titre + "\n" + "\n".join(f"- {t}" for t in textes)


_INTEGRATION = {True: "intégrée", False: "NON intégrée", None: ""}


def _section_passage(vue: dict) -> list[str]:
    """Ce qu'un passage précédent a laissé : fait, reste, décisions, branche, fin, réponse."""
    entete = f"### Passage {vue['numero']} — {vue['libelle_etat'] or vue['etat']}"
    if vue.get("agent_id"):
        entete += f" (agent {vue['agent_id']})"
    recap = vue.get("recap") or {}
    lignes = [entete]
    for cle, titre in (("fait", "Fait :"), ("reste", "Restait à faire :"),
                       ("a_decider", "Points à décider :")):
        if recap.get(cle):
            lignes.append(_puces(titre, recap[cle]))
    if vue.get("branche"):
        lignes.append(f"Branche : {vue['branche']} {_INTEGRATION[vue.get('integre')]}".rstrip())
    if vue.get("raison_echec"):
        lignes.append(f"Fin du passage : {vue['raison_echec']}")
    if recap.get("resume"):
        lignes.append("Réponse finale de l'agent (extrait) :\n" + recap["resume"])
    return lignes


def _historique(vues: list[dict]) -> str:
    """Les passages précédents, du plus ancien au plus récent."""
    if not vues:
        return ""
    lignes = ["## Ce qui a déjà été fait sur cette tâche",
              "Des agents ont déjà travaillé sur cette tâche. Pars de leur travail, ne le "
              "refais pas, et tiens compte des retours de l'utilisateur plus bas."]
    for vue in vues:
        lignes.extend(_section_passage(vue))
    return "\n\n".join(lignes)


def _retours(micro: dict, retour_en_plus: str) -> list[str]:
    retours = [r["texte"] for r in micros_service.retours_de(micro["id"])]
    if retour_en_plus.strip():
        retours.append(retour_en_plus.strip())
    return retours


def prompt_assemble(micro: dict, retour_en_plus: str = "", liste_passages=None) -> dict:
    """Le prompt d'un NOUVEAU passage : brief + historique des passages + retours.

    `retour_en_plus` = le retour qu'on s'apprête à donner (aperçu avant envoi)."""
    vues = list(reversed(liste_passages if liste_passages is not None else passages(micro)))
    retours = _retours(micro, retour_en_plus)
    morceaux = [micros_service.prompt_de(micro), _historique(vues)]
    if retours:
        morceaux.append(_puces("## Retours de l'utilisateur (le plus récent en dernier)", retours))
    texte = "\n\n".join(m for m in morceaux if m)
    return {"prompt": texte, "passages_inclus": len(vues), "retours_inclus": len(retours),
            "caracteres": len(texte)}


# ------------------------------------------------------------------------------ lancer


def _relais(refus) -> Refus:
    """Un refus de l'API tickets, relayé avec son code TEL QUEL (spec §5.4, constat C6)."""
    return Refus(refus.code, refus.message, refus.status, **refus.details)


def _garde_environnement() -> None:
    """Refuse proprement quand l'env API ou Python rend tout spawn voué à l'échec."""
    from .api_tickets import garde
    from .api_tickets.refus import Refus as RefusApi
    try:
        garde.exiger()
    except RefusApi as refus:
        raise _relais(refus) from refus


def _refus_si_occupee(vues: list[dict], message: str) -> None:
    """Jamais deux agents actifs sur la même tâche."""
    actif = next((v for v in vues if v["etat"] in lexique.ETATS_ACTIFS), None)
    if actif is not None:
        raise Refus("deja_en_cours", message.format(numero=actif["numero"]), 409,
                    agent_id=actif.get("agent_id", ""))


def _refus_si_archivee(micro: dict) -> None:
    if (micro.get("etat") or "") in ("faite", "abandonnee"):
        raise Refus("archivee", "Cette tâche est archivée : rouvre-la avant de la relancer.", 409)


def _dispatcher(micro: dict, prompt: str, slug: str, profil: str, isolation: str,
                defer: bool, parent: str = "") -> dict:
    """Le passage est un CLIENT de la création de ticket (`POST /api/projects/{slug}/tickets`,
    même service) ; tout refus est relayé avec son code (la tâche reste brouillon).

    `parent` : l'agent qui lance (l'assistant du Bureau). Le ticket lui est rattaché pour
    qu'il soit réveillé quand l'agent finit ou pose une question ; le profil reste celui d'un
    lancement depuis l'écran (`managed: false`). Vide : lancement manuel."""
    from .api_tickets import creation
    from .api_tickets.refus import Refus as RefusApi
    demande = {"title": str(micro.get("titre") or "")[:200] or prompt.splitlines()[0][:80],
               "prompt": prompt, "profile": (profil or "").strip(), "isolation": isolation,
               "parent": parent, "managed": False, "micro_id": micro.get("id"), "defer": defer}
    try:
        return creation.creer(slug, demande)
    except RefusApi as refus:
        raise _relais(refus) from refus


def _reponse_de_lancement(micro_id: str, verdict: dict, slug: str) -> dict:
    ticket_id = str(verdict["ticket_id"])
    reponse = {"ok": True, "mode": "nouvel_agent", "ticket_id": ticket_id,
               "launch_key": f"launching/{ticket_id}", "projet_slug": slug,
               "isolation": verdict.get("isolation", ""),
               "isolation_message": verdict.get("isolation_message", ""),
               "micro": micros_service.get_micro(micro_id)}
    if verdict.get("key"):
        reponse["key"] = verdict["key"]
        reponse["agent_id"] = str(verdict["key"]).split("/", 1)[-1]
    if verdict.get("scope_warnings"):
        reponse["avertissements"] = verdict["scope_warnings"]
    return reponse


def lancer(micro_id: str, projet_slug: str = "", profil: str = "", isolation: str = "",
           retour: str = "", defer: bool = True, garde_env: bool = True,
           parent: str = "", execution: dict | None = None) -> dict:
    """Lance un NOUVEAU passage. Le prompt est l'assemblage complet (historique compris).

    `execution` ({cible, projets, fichiers_non_suivis}, cf. `taches_execution`) : memorisee
    sur la tache, posee sur le ticket, injectee dans le prompt ; `cible="rundeck"` confie le
    passage au lanceur distant au lieu de lancer un agent local."""
    from . import taches_execution
    micro = _micro_ou_refus(micro_id)
    if not (micro.get("titre") or "").strip():
        raise Refus("titre_requis", "Une tâche sans titre ne dit pas quoi faire.")
    if garde_env:
        _garde_environnement()
    with VERROU_LANCEMENT:
        micro = _micro_ou_refus(micro_id)
        _refus_si_archivee(micro)
        vues = passages(micro)
        _refus_si_occupee(vues, "Un agent travaille déjà sur cette tâche (passage {numero}) : "
                                "arrête-le ou attends qu'il ait fini.")
        slug = resoudre_depot(micro, projet_slug)
        retour_ligne = micros_service.add_retour(micro_id, retour, mode="nouvel_agent") \
            if retour.strip() else None
        execution = taches_execution.preparer(micro_id, execution, slug)
        prompt = prompt_assemble(micro, liste_passages=vues)["prompt"]             + taches_execution.section_prompt(execution)
        if execution and execution["cible"] == "rundeck":
            verdict = taches_execution.lancer_distant(micro, prompt, slug, execution, parent)
        else:
            verdict = _dispatcher(micro, prompt, slug, profil, isolation, defer, parent)
        ticket_id = str(verdict["ticket_id"])
        taches_execution.poser_sur_ticket(slug, ticket_id, execution)
        micros_service.lier_ticket(micro_id, slug=slug, ticket_id=ticket_id)
        if retour_ligne:
            micros_service.rattacher_retour(retour_ligne["id"], ticket_id)
        if (micro.get("etat") or "") != "lancee":
            micros_service.marquer_etat(micro_id, "lancee")
    reponse = _reponse_de_lancement(micro_id, verdict, slug)
    if execution:
        reponse["execution"] = execution
    if verdict.get("distant"):
        reponse["distant"] = verdict["distant"]
    return reponse


TEXTE_CONTINUER = "Continue là où tu t'es arrêté."


def _rattacher(slug: str, ticket: dict, parent: str) -> dict:
    """L'assistant qui relance un passage LANCÉ À LA MAIN en devient le parent : c'est lui qui
    attend la réponse, c'est donc lui que le réveil doit prévenir. Un passage déjà rattaché à
    un agent (manager, autre assistant) garde son parent : on ne lui vole pas son enfant.
    Le passage reste NON managé : une relance depuis l'écran garde son profil (NON_MANAGE)."""
    from . import dispatch as dispatch_service
    from . import tickets as tickets_service
    if not parent or dispatch_service.is_managed_parent(ticket.get("parent") or ""):
        return ticket
    tickets_service.poser(slug, ticket, parent=parent, **{dispatch_service.NON_MANAGE: True})
    return ticket


def _continuer(micro: dict, dernier: dict, retour: str, parent: str = "") -> dict:
    """Envoie le retour à l'agent du dernier passage, dans SA conversation."""
    from . import tickets as tickets_service
    from .api_tickets import remise
    from .api_tickets.refus import Refus as RefusApi
    ticket = tickets_service.get_ticket(dernier["slug"], dernier["ticket_id"])
    if ticket is None:
        raise Refus("non_joignable", "Le ticket du dernier passage a disparu.", 409)
    ticket = _rattacher(dernier["slug"], ticket, parent)
    try:
        remise.remettre(remise.agent_du_ticket(ticket), retour.strip() or TEXTE_CONTINUER,
                        du_ticket=(dernier["slug"], ticket))
    except RefusApi as refus:
        raise _relais(refus) from refus
    enregistre = micros_service.add_retour(micro["id"], retour, ticket_id=dernier["ticket_id"],
                                           mode="continuer") if retour.strip() else None
    if (micro.get("etat") or "") != "lancee":
        micros_service.marquer_etat(micro["id"], "lancee")
    return {"ok": True, "mode": "continuer", "joignable": True,
            "ticket_id": dernier["ticket_id"], "agent_id": dernier["agent_id"],
            "key": dernier["key"], "retour": enregistre,
            "micro": micros_service.get_micro(micro["id"])}


def _en_file_si_occupee(micro: dict, vues: list[dict], retour: str, mode: str) -> dict | None:
    """L'agent du dernier passage travaille encore et on lui envoie un retour (même agent) : le
    retour part EN FILE, livré à la fin de son tour — plus de 409 muet côté écran. None si ce
    cas ne s'applique pas (le refus « déjà en cours » garde alors la main)."""
    actif = next((v for v in vues if v["etat"] in lexique.ETATS_ACTIFS), None)
    if not (actif and actif.get("agent_id") and retour.strip() and (mode or "continuer") == "continuer"):
        return None
    from . import file_messages
    item = file_messages.mettre_en_file(actif["agent_id"], retour.strip())
    enregistre = micros_service.add_retour(micro["id"], retour, ticket_id=actif["ticket_id"],
                                           mode="continuer")
    return {"ok": True, "mode": "continuer", "queued": True, "queue_id": item.get("id", ""),
            "joignable": True, "ticket_id": actif["ticket_id"], "agent_id": actif["agent_id"],
            "key": actif.get("key", ""), "retour": enregistre,
            "micro": micros_service.get_micro(micro["id"])}


def relancer(micro_id: str, retour: str = "", mode: str = "", projet_slug: str = "",
             profil: str = "", isolation: str = "", defer: bool = True,
             parent: str = "", execution: dict | None = None) -> dict:
    """Nouvelle itération : le retour est enregistré, puis envoyé à l'agent du dernier passage
    (`continuer`, contexte et cache conservés) ou à un nouvel agent (`nouvel_agent`, contexte
    assemblé). Défaut : `continuer` si le dernier agent est joignable."""
    micro = _micro_ou_refus(micro_id)
    _refus_si_archivee(micro)
    vues = passages(micro)
    en_file = _en_file_si_occupee(micro, vues[:1], retour, mode)
    if en_file:
        return en_file
    _refus_si_occupee(vues[:1], "Un agent travaille encore sur cette tâche : envoie-lui ta "
                                "consigne depuis sa conversation, ou arrête-le d'abord.")
    joignable = bool(vues and vues[0]["joignable"])
    mode = (mode or "").strip() or ("continuer" if joignable else "nouvel_agent")
    if mode not in ("continuer", "nouvel_agent"):
        raise Refus("mode_inconnu", f"mode inconnu : {mode!r} (continuer ou nouvel_agent)")
    if mode == "nouvel_agent":
        reponse = lancer(micro_id, projet_slug=projet_slug, profil=profil, isolation=isolation,
                         retour=retour, defer=defer, parent=parent, execution=execution)
        return {**reponse, "joignable": joignable}
    if not joignable:
        raise Refus("non_joignable",
                    "L'agent du dernier passage ne peut plus recevoir de message : relance avec "
                    "un nouvel agent.", 409)
    return _continuer(micro, vues[0], retour, parent)


# ----------------------------------------------------------------------------- arrêter


def _tuer(agent_id: str) -> str:
    """Arrête un agent par LE geste de l'API (`POST /api/agents/{id}/stop`) : "" ou l'erreur."""
    from bouzecode.web_v2.runtime.runner import agent_fiche

    from .api_tickets import controle
    from .api_tickets.refus import Refus as RefusApi
    agent = agent_fiche.load_agent(agent_id)
    if agent is None:
        return ""
    try:
        controle.arreter_agent(agent)
    except RefusApi as refus:
        return refus.message
    return ""


def _arreter_passage(vue: dict) -> tuple[str, dict | None]:
    """Arrête un passage actif → (identifiant arrêté ou "", erreur ou None)."""
    from . import dispatch as dispatch_service
    from . import tickets as tickets_service
    if vue.get("agent_id"):
        erreur = _tuer(vue["agent_id"])
        if erreur:
            return "", {"agent_id": vue["agent_id"], "error": erreur}
        return vue["agent_id"], None
    #  Lancement encore en préparation : on l'acte comme échoué, rien ne démarrera. Si l'agent
    #  vient de démarrer entre-temps, c'est lui qu'on arrête.
    ticket = tickets_service.get_ticket(vue["slug"], vue["ticket_id"])
    if ticket is None:
        return "", None
    demarre = dispatch_service.arreter_la_preparation(vue["slug"], ticket)
    if demarre:
        return _arreter_passage({**vue, "agent_id": demarre})
    return vue["ticket_id"], None


def arreter(micro_id: str) -> dict:
    """Arrête les agents actifs de la tâche. La tâche passera « En échec » (arrêt volontaire)."""
    from . import taches_vue
    micro = _micro_ou_refus(micro_id)
    actifs = [v for v in passages(micro) if v["etat"] in lexique.ETATS_ACTIFS]
    if not actifs:
        raise Refus("rien_a_arreter", "Aucun agent ne travaille sur cette tâche.", 409)
    issues = [_arreter_passage(vue) for vue in actifs]
    arretes = [ident for ident, _ in issues if ident]
    erreurs = [erreur for _, erreur in issues if erreur]
    if erreurs and not arretes:
        raise Refus("arret_refuse", "Le système a refusé d'arrêter l'agent.", 502,
                    erreurs=erreurs)
    taches_vue.invalider()
    return {"ok": True, "arretes": arretes, "erreurs": erreurs,
            "micro": micros_service.get_micro(micro_id)}


# ------------------------------------------------------------------------------- états


def _verifier_transition(depart: str, etat: str) -> None:
    if etat not in micros_service.ETATS_MICRO:
        raise Refus("etat_inconnu", f"état inconnu : {etat!r}")
    permis = micros_service.TRANSITIONS.get(depart, ())
    if etat != depart and etat not in permis:
        raise Refus("transition_refusee",
                    f"Une tâche « {lexique.libelle_statut(depart) or depart} » ne peut pas "
                    f"passer « {lexique.libelle_statut(etat) or etat} ».", 409,
                    permises=list(permis))


def _liberer_agent(micro: dict, etat: str) -> list[str]:
    """Abandonner arrête d'abord l'agent actif ; rouvrir ou classer « faite » est refusé."""
    if not (micro.get("etat") == "lancee" or micro.get("tickets")):
        return []
    actif = agent_actif(micro)
    if actif is None:
        return []
    if etat == "abandonnee":
        return arreter(micro["id"])["arretes"]
    if etat in ("brouillon", "faite", "prete"):
        raise Refus("agent_actif",
                    "Un agent travaille encore sur cette tâche : arrête-le d'abord.", 409,
                    agent_id=actif.get("agent_id", ""))
    return []


_ETATS_CLASSES = ("faite", "abandonnee")


def _cascade(micro: dict, depart: str, etat: str, auteur: str) -> dict:
    """Classer archive les tickets et conversations de la tâche ; rouvrir les ramène et date
    la réouverture du classement motivé (fait ailleurs, doublon, caduque), sans l'effacer."""
    from . import archivage_tache, classement
    if etat in _ETATS_CLASSES and depart not in _ETATS_CLASSES:
        return {"archives": archivage_tache.archiver(micro)}
    if etat not in _ETATS_CLASSES and depart in _ETATS_CLASSES:
        classement.noter_reouverture(micro["id"], auteur)
        return {"restaures": archivage_tache.restaurer(micro)}
    return {}


def changer_etat(micro_id: str, etat: str, pourquoi: str = "", auteur: str = "humain") -> dict:
    """faite · abandonnee · brouillon (Rouvrir). Abandonner arrête d'abord l'agent actif ;
    rouvrir ou classer « faite » pendant qu'un agent tourne est refusé. Classer archive les
    tickets et conversations de la tâche (`archives`) ; rouvrir les restaure (`restaures`)."""
    micro = _micro_ou_refus(micro_id)
    depart = micro.get("etat") or ""
    _verifier_transition(depart, etat)
    arretes = _liberer_agent(micro, etat)
    try:
        vue = micros_service.marquer_etat(micro_id, etat, pourquoi=pourquoi)
    except micros_service.EtatRefuse as refus:
        raise Refus("transition_refusee", str(refus), 409)
    return {"micro": vue, **({"arretes": arretes} if arretes else {}),
            **_cascade(micro, depart, etat, auteur)}


# ---------------------------------------------------------------------------- intégrer


def _passage_a_integrer(micro: dict, ticket_id: str) -> tuple[str, dict]:
    """(slug, ticket) d'un passage de la tâche dont l'agent a fini."""
    from . import tickets as tickets_service
    lien = next((l for l in micro.get("tickets") or [] if l.get("ticket_id") == ticket_id), None)
    if lien is None:
        raise Refus("passage_inconnu", f"le passage {ticket_id} n'appartient pas à cette tâche",
                    404)
    vue = next((v for v in passages(micro) if v["ticket_id"] == ticket_id), None) or {}
    if vue.get("etat") in lexique.ETATS_ACTIFS:
        raise Refus("agent_actif", "L'agent de ce passage travaille encore.", 409)
    slug = vue.get("slug") or lien.get("slug") or ""
    ticket = tickets_service.get_ticket(slug, ticket_id)
    if ticket is None:
        raise Refus("passage_inconnu", "Le ticket de ce passage a disparu.", 404)
    return slug, ticket


def integrer(micro_id: str, ticket_id: str) -> dict:
    """Client de `POST …/tickets/{id}/integrate` (même service, mêmes codes) : l'intégration
    part EN FOND (`integrating`), l'écran suit l'état du passage."""
    from .api_tickets import integration_async
    from .api_tickets.refus import Refus as RefusApi
    slug, ticket = _passage_a_integrer(_micro_ou_refus(micro_id), ticket_id)
    try:
        resultat = integration_async.integrer(slug, ticket)
    except RefusApi as refus:
        raise _relais(refus) from refus
    return {"ok": True, "state": resultat.get("state"),
            "message": "Intégration lancée : le travail est en cours de fusion dans la branche de "
                       "base."}
