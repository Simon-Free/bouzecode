# [desc] Arguments de `bouzecode tickets …` et `bouzecode projets …` (argparse, un seul niveau de sous-commande par objet), avec l'aide complète de chaque commande. [/desc]
from __future__ import annotations

import argparse

EPILOGUE = """\
Sans serveur web, la CLI agit en process (mêmes services que l'API) ; si le serveur de
référence tourne, les écritures passent par son API et `suivre` ne fait que lire (son
watchdog suit). Codes de sortie : 0 succès / livré, 1 refus ou erreur (code affiché),
2 usage ; `suivre` : 3 refus du modèle, 4 fin sans livraison, 5 arrêté ou planté,
6 question en attente, 7 délai écoulé, 130 Ctrl+C (l'agent continue)."""


def _commande(sous, nom: str, aide: str, ticket: bool = True) -> argparse.ArgumentParser:
    parseur = sous.add_parser(nom, help=aide, description=aide)
    parseur.add_argument("--json", action="store_true", help="sortie JSON (scripts)")
    if ticket:
        parseur.add_argument("slug", help="projet du ticket")
        parseur.add_argument("ticket_id", help="identifiant du ticket")
    return parseur


def _options_de_creation(parseur: argparse.ArgumentParser) -> None:
    parseur.add_argument("--projet", dest="slug", required=True, help="projet (slug enregistré)")
    parseur.add_argument("--titre", required=True, help="titre court (≤ 200 car.)")
    consigne = parseur.add_mutually_exclusive_group(required=True)
    consigne.add_argument("--prompt", help="la consigne de l'agent")
    consigne.add_argument("--prompt-fichier", help="consigne lue dans ce fichier UTF-8")
    parseur.add_argument("--profil", default="", help="profil d'agent (défaut : celui du projet)")
    parseur.add_argument("--modele", default="", help="modèle (défaut : celui de la config)")
    parseur.add_argument("--isolation", default="", choices=("", "shared", "worktree",
                                                              "worktree_venv"),
                         help="défaut : worktree dans un dépôt git")
    parseur.add_argument("--brouillon", action="store_true", help="crée sans lancer")
    parseur.add_argument("--cible", default="", choices=("", "local", "rundeck"),
                         help="où tourne l'agent (défaut : local)")
    parseur.add_argument("--mode", default="", choices=("", "agent", "tests"),
                         help="cible rundeck : agent (défaut) ou tests seulement")
    parseur.add_argument("--commande-tests", "--commande", dest="commande_tests", default="",
                         help="mode tests : arguments de pytest, ex. \"tests/web -x\" ; mode "
                              "agent : commande jouée sur la VM à la place de l'agent bouzecode")
    parseur.add_argument("--navigateur", action=argparse.BooleanOptionalAction, default=None,
                         help="mode tests : installer Chromium (défaut : oui)")
    parseur.add_argument("--fichier", action="append", default=[], metavar="[SLUG:]CHEMIN",
                         help="fichier NON SUIVI à transmettre (répétable ; SLUG = projet "
                              "secondaire, sinon le projet principal)")
    parseur.add_argument("--projets-sup", nargs="+", default=[], metavar="SLUG",
                         help="projets secondaires de la tâche")


def _tickets(racine) -> None:
    tickets = racine.add_parser("tickets", help="tickets et agents, sans le serveur web",
                                description="Tickets et agents, sans le serveur web.",
                                epilog=EPILOGUE, formatter_class=argparse.RawDescriptionHelpFormatter)
    sous = tickets.add_subparsers(dest="action", required=True, metavar="COMMANDE")
    lister = _commande(sous, "lister", "tickets d'un projet (ou de tous)", ticket=False)
    lister.add_argument("--projet", dest="slug", default="", help="slug (défaut : tous)")
    lister.add_argument("--etat", default="", help="état(s), séparés par des virgules")
    lister.add_argument("--archives", action="store_true", help="inclure les archivés")
    _commande(sous, "voir", "fiche d'un ticket : état, runs, livraison, journal")
    _options_de_creation(_commande(sous, "creer", "crée (et lance) un ticket", ticket=False))
    lancer = _commande(sous, "lancer", "nouveau run sur un ticket (relance)")
    lancer.add_argument("--profil", default="")
    lancer.add_argument("--modele", default="")
    lancer.add_argument("--suffixe", default="", help="texte ajouté au prompt du ticket")
    message = _commande(sous, "message", "message à l'agent du ticket")
    message.add_argument("texte")
    message.add_argument("--maintenant", action="store_true",
                         help="coupe le tour en cours (défaut : mis en file)")
    _commande(sous, "stop", "arrête l'agent (ou le lancement) du ticket")
    _commande(sous, "integrer", "fusionne la branche du ticket dans sa base (attend l'issue)")
    clore = _commande(sous, "clore", "clôt le ticket (accepté par défaut)")
    clore.add_argument("--abandon", action="store_true", help="clôt en « abandonné »")
    clore.add_argument("--raison", default="")
    _commande(sous, "rouvrir", "rouvre un ticket clos")
    suivre = _commande(sous, "suivre", "attend la fin du ticket en affichant son journal")
    suivre.add_argument("--intervalle", type=float, default=5.0, help="secondes entre deux pas")
    suivre.add_argument("--delai", type=float, default=None, help="abandonne le suivi après N s")


def _projets(racine) -> None:
    projets = racine.add_parser("projets", help="projets enregistrés (lecture seule)",
                                description="Projets enregistrés (lecture seule).")
    sous = projets.add_subparsers(dest="action", required=True, metavar="COMMANDE")
    _commande(sous, "lister", "projets : chemin, branche, dernier commit", ticket=False)
    fichiers = _commande(sous, "fichiers", "état git et fichiers NON SUIVIS à transmettre",
                         ticket=False)
    fichiers.add_argument("slug")
    fichiers.add_argument("--indices", nargs="*", default=[],
                          help="mots de la tâche : marque les fichiers pertinents")


def construire() -> argparse.ArgumentParser:
    racine = argparse.ArgumentParser(prog="bouzecode", description="Commandes sans serveur web.")
    sous = racine.add_subparsers(dest="objet", required=True, metavar="OBJET")
    _tickets(sous)
    _projets(sous)
    return racine
