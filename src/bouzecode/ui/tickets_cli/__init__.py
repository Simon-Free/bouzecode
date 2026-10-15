# [desc] `bouzecode tickets …` / `bouzecode projets …` : piloter tickets et agents depuis le terminal, sans serveur web (ou à travers lui s'il tourne). Point d'entrée `main(argv)` appelé par ui/cli.py. [/desc]
"""Les équivalents en ligne de commande de l'API tickets (cf. README.md du dossier).

`ui/cli.py` route ici dès que le 1er argument est `tickets` ou `projets` : le reste de la ligne
n'est jamais pris pour un prompt."""
from __future__ import annotations

import sys
from pathlib import Path

from . import gestes, parseur, rendu, suivi
from .serveur import ErreurGeste

OBJETS = ("tickets", "projets")
EXIT_OK, EXIT_REFUS = 0, 1


def est_sous_commande(argv: list[str]) -> bool:
    return bool(argv) and argv[0] in OBJETS


def _lister(args) -> tuple[dict, str]:
    from bouzecode.web_v2.services.work import projects
    from bouzecode.web_v2.services.work.api_tickets import lectures
    slugs = [args.slug] if args.slug else [p["slug"] for p in projects.list_projects()]
    if args.slug and projects.find(args.slug) is None:
        raise ErreurGeste("projet_inconnu", f"projet inconnu : {args.slug}", 404)
    lignes = []
    for slug in slugs:
        page = gestes.en_process(lectures.lister, slug, args.etat, "all" if args.archives else "0",
                                 limit=500)
        lignes += [(slug, t) for t in page["tickets"]]
    return ({"tickets": [{"project_slug": s, **t} for s, t in lignes]}, rendu.liste(lignes))


def _voir(args) -> tuple[dict, str]:
    from bouzecode.web_v2.services.work import ticket_fsm
    from bouzecode.web_v2.services.work.api_tickets import lectures
    fiche = lectures.fiche(gestes.ticket(args.slug, args.ticket_id))
    evenements = ticket_fsm.events(args.slug, args.ticket_id, 0)
    return {**fiche, "events": evenements}, rendu.fiche(fiche, evenements)


def _suivre(args) -> tuple[dict, str, int]:
    ecrire = (lambda e: None) if args.json else (lambda e: print(rendu.evenement(e), flush=True))
    try:
        issue = suivi.suivre(args.slug, args.ticket_id, ecrire, args.intervalle, args.delai)
    except KeyboardInterrupt:
        return {"code": suivi.EXIT_INTERROMPU}, "Suivi interrompu : l'agent continue.", \
            suivi.EXIT_INTERROMPU
    from bouzecode.web_v2.services.work.etat_ticket import vue
    t = {**issue["ticket"], **vue(issue["ticket"])}
    corps = {"code": issue["code"], "state": t.get("state"), "state_reason": t.get("state_reason")}
    return corps, f"Fin du suivi : {rendu._etat(t)} (code {issue['code']})", issue["code"]


def _projets(args) -> tuple[dict, str]:
    from bouzecode.web_v2.services.work import projets_etat
    if args.action == "lister":
        tous = projets_etat.lister()
        return {"projets": tous}, rendu.projets(tous)
    resultat = projets_etat.fichiers(args.slug, args.indices)
    if not resultat.get("ok"):
        raise ErreurGeste(resultat.get("erreur") or "refus", rendu.fichiers(resultat), 404, resultat)
    return resultat, rendu.fichiers(resultat)


def _executer(args) -> tuple[dict, str, int]:
    if args.objet == "projets":
        return (*_projets(args), EXIT_OK)
    if args.action == "lister":
        return (*_lister(args), EXIT_OK)
    if args.action == "voir":
        return (*_voir(args), EXIT_OK)
    if args.action == "suivre":
        return _suivre(args)
    resultat = gestes.executer(args)
    return resultat, rendu.geste(args.action, getattr(args, "slug", ""), resultat), EXIT_OK


def main(argv: list[str]) -> int:
    args = parseur.construire().parse_args(argv)
    if getattr(args, "prompt_fichier", None):
        args.prompt = Path(args.prompt_fichier).read_text(encoding="utf-8")
    try:
        corps, texte, code = _executer(args)
    except ErreurGeste as refus:
        print(rendu.en_json(refus.corps()) if args.json else rendu.erreur(refus.corps()),
              file=sys.stdout if args.json else sys.stderr)
        return EXIT_REFUS
    print(rendu.en_json(corps) if args.json else texte)
    return code
