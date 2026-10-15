# [desc] Les commandes d'ÉCRITURE de `bouzecode tickets` (creer, lancer, message, stop, integrer, clore, rouvrir) : en process sans serveur, par l'API HTTP quand le serveur de référence vit. [/desc]
"""Chaque geste a deux formes, au même contrat : `_local_<geste>` appelle le service que la
route appelle (`web_v2/services/work/api_tickets/*`, `cloture_ticket`), `_http_<geste>` rend la
requête de la route. `executer` choisit selon la règle de `serveur.py`.

En process, un lancement est SYNCHRONE (`defer: false`) : un fil de fond mourrait avec la CLI.
Les agents lancés sont détachés de la console (`runner.DRAPEAUX_DE_SPAWN`)."""
from __future__ import annotations

import subprocess
import sys

from . import serveur
from .serveur import ErreurGeste, en_process


def _route(args, suite: str = "") -> str:
    return f"/api/projects/{args.slug}/tickets/{args.ticket_id}{suite}"


def ticket(slug: str, ticket_id: str, geste: bool = False) -> dict:
    from bouzecode.web_v2.services.work import tickets
    trouve = tickets.get_ticket(slug, ticket_id)
    if trouve is None:
        raise ErreurGeste("ticket_inconnu", f"ticket inconnu : {slug}/{ticket_id}", 404)
    if geste and trouve.get("archived"):
        raise ErreurGeste("archive", "ticket archivé : il n'accepte que les lectures", 409,
                          {"state": trouve.get("state")})
    return trouve


def preparer_les_lancements() -> None:
    """Ce que fait le boot du serveur avant un spawn : sonde de l'API (garde `env_indisponible`)
    et, sous Windows, des agents détachés de la console de la CLI."""
    from bouzecode.web_v2 import api_sanity
    from bouzecode.web_v2.runtime.runner import agent_commande
    api_sanity.capture_api_sanity()
    if sys.platform == "win32":
        agent_commande.DRAPEAUX_DE_SPAWN = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW


# ---------------------------------------------------------------- creer

def _execution(args) -> dict:
    from bouzecode.backend.tools.bureau_lancement import execution_depuis
    projets = [args.slug, *args.projets_sup]
    fichiers: dict[str, list[str]] = {}
    for brut in args.fichier:
        slug, separe, chemin = brut.partition(":")
        if not separe or slug not in projets:
            slug, chemin = args.slug, brut
        fichiers.setdefault(slug, []).append(chemin)
    #  Options Rundeck transmises telles quelles : hors cible=rundeck, le service les REFUSE
    #  (400 `options_distantes`) au lieu de les ignorer en silence.
    return execution_depuis(projets if (args.projets_sup or fichiers or args.cible) else None,
                            args.cible or "", fichiers, args.mode or "",
                            args.commande_tests or "", args.navigateur)


def corps_de_creation(args) -> dict:
    corps = {"title": args.titre, "prompt": args.prompt, "launch": not args.brouillon}
    for cle, valeur in (("profile", args.profil), ("model", args.modele),
                        ("isolation", args.isolation)):
        if valeur:
            corps[cle] = valeur
    return {**corps, **_execution(args)}


def _local_creer(args) -> dict:
    preparer_les_lancements()
    from bouzecode.web_v2.services.work.api_tickets import creation
    return en_process(creation.creer, args.slug, {**corps_de_creation(args), "defer": False})


def _http_creer(args) -> tuple:
    return "POST", f"/api/projects/{args.slug}/tickets", corps_de_creation(args)


# ---------------------------------------------------------------- gestes sur un ticket

def _corps_de_relance(args) -> dict:
    return {cle: valeur for cle, valeur in (("profile", args.profil), ("model", args.modele),
                                            ("prompt_suffix", args.suffixe)) if valeur}


def _local_lancer(args) -> dict:
    preparer_les_lancements()
    from bouzecode.web_v2.services.work.api_tickets import lancement
    ticket(args.slug, args.ticket_id, geste=True)
    return en_process(lancement.lancer, args.slug, args.ticket_id,
                      {**_corps_de_relance(args), "defer": False})


def _local_message(args) -> dict:
    preparer_les_lancements()
    from bouzecode.web_v2.services.work import tickets
    from bouzecode.web_v2.services.work.api_tickets import remise
    vise = ticket(args.slug, args.ticket_id, geste=True)
    mode = remise.INTERROMPRE if args.maintenant else remise.FILE
    try:
        return en_process(lambda: remise.remettre(remise.agent_du_ticket(vise), args.texte, mode,
                                                  du_ticket=(args.slug, vise)))
    except ErreurGeste as refus:  # jamais perdu : gardé au journal, NON envoyé (comme la route)
        tickets.add_comment(args.slug, vise, args.texte, False)
        refus.details["commentaire_conserve"] = True
        raise


def _local_stop(args) -> dict:
    from bouzecode.web_v2.services.work.api_tickets import controle
    return en_process(controle.arreter_ticket, args.slug, ticket(args.slug, args.ticket_id))


def _local_integrer(args) -> dict:
    from bouzecode.web_v2.services.work.api_tickets import integration_async
    vise = ticket(args.slug, args.ticket_id, geste=True)
    return en_process(integration_async.integrer, args.slug, vise, attendre=True)


def _local_clore(args) -> dict:
    from bouzecode.web_v2.services.work import cloture_ticket
    return en_process(cloture_ticket.clore, args.slug, ticket(args.slug, args.ticket_id),
                      _issue(args), args.raison or "")


def _local_rouvrir(args) -> dict:
    from bouzecode.web_v2.services.work import cloture_ticket
    return en_process(cloture_ticket.rouvrir, args.slug, ticket(args.slug, args.ticket_id))


def _issue(args) -> str:
    return "abandoned" if args.abandon else "accepted"


_HTTP = {
    "creer": _http_creer,
    "lancer": lambda a: ("POST", _route(a, "/runs"), _corps_de_relance(a)),
    "message": lambda a: ("POST", _route(a, "/messages"),
                          {"text": a.texte, "mode": "now" if a.maintenant else "queue"}),
    "stop": lambda a: ("POST", _route(a, "/stop"), {}),
    "integrer": lambda a: ("POST", _route(a, "/integrate"), {"wait": True}),
    "clore": lambda a: ("POST", _route(a, "/close"), {"outcome": _issue(a),
                                                      "reason": a.raison or ""}),
    "rouvrir": lambda a: ("POST", _route(a, "/reopen"), {}),
}
_LOCAL = {"creer": _local_creer, "lancer": _local_lancer, "message": _local_message,
          "stop": _local_stop, "integrer": _local_integrer, "clore": _local_clore,
          "rouvrir": _local_rouvrir}
GESTES = tuple(_LOCAL)


def executer(args) -> dict:
    """Le geste `args.action`, par le serveur s'il vit, sinon en process. Lève `ErreurGeste`."""
    if serveur.vivant():
        return {**serveur.appeler(*_HTTP[args.action](args)), "via": "serveur"}
    return {**_LOCAL[args.action](args), "via": "process"}
