# [desc] Parametres d'EXECUTION d'un lancement de tache par l'assistant (projets, cible local|rundeck, fichiers non suivis) et message clair quand le serveur web est arrete. [/desc]
"""Ce que `Taches(lancer|relancer)` et `LancerAgent` ajoutent au corps de
`POST /api/micros/<id>/lancer` : le champ `execution` (contrat :
docs/specs/assistant_execution.md). Garde `bureau_tools` sous controle de taille.
Le schema ne NOMME aucun autre outil : il est partage par l'assistant et le manager, qui n'a
pas `Projets` (cf. test_prompt_registry_conformity).
"""
from __future__ import annotations

#: Commande a donner a l'humain quand le serveur n'ecoute pas (un TUI hors web).
COMMANDE_SERVEUR = r"powershell -File bouzecode\bouzeui.ps1"

PARAMS_EXECUTION = {
    "projets": {"type": "array", "items": {"type": "string"}, "description": (
        "Slugs des depots concernes (depots enregistres). Le 1er est le depot principal ; "
        "plusieurs = tache multi-depots (l'agent recoit leurs chemins).")},
    "cible": {"type": "string", "enum": ["local", "rundeck"], "description": (
        "Ou l'agent tourne. 'local' (defaut) : sur ce poste. 'rundeck' : VM Linux Rundeck rec "
        "(voir mode_distant ; refus `cible_indisponible` ou `lancement_impossible` : dis-le).")},
    "fichiers_non_suivis": {"type": "object", "description": (
        "{slug: [chemins relatifs]} : fichiers HORS git a transmettre (l'agent part de "
        "l'etat commite). Pris parmi les fichiers non suivis proposes ; jamais un secret "
        "(.env, cle) sans accord explicite de l'humain."),
        "additionalProperties": {"type": "array", "items": {"type": "string"}}},
    "mode_distant": {"type": "string", "enum": ["agent", "tests"], "description": (
        "Avec cible='rundeck' : 'agent' (defaut) = un agent bouzecode tourne sur la VM ; "
        "'tests' = la VM joue SEULEMENT les tests du depot principal (Linux, Playwright compris) "
        "et rend JUnit + captures + fin de sortie. Tu es reveille a la fin dans les deux cas.")},
    "commande_tests": {"type": "string", "description": (
        "mode_distant='tests' : arguments de pytest (chemins, -m, -k), ex. "
        "'tests/web -m playwright -x'. Obligatoire en mode tests.")},
    "navigateur": {"type": "boolean", "description": (
        "mode_distant='tests' : installer Chromium headless avant les tests (defaut vrai). "
        "Faux pour une suite sans navigateur (plus rapide).")},
}
#: Parametres d'execution que les outils relaient tels quels a `execution_depuis`.
NOMS_EXECUTION = tuple(PARAMS_EXECUTION)


def execution_depuis(projets=None, cible: str = "", fichiers_non_suivis=None,
                     mode_distant: str = "", commande_tests: str = "", navigateur=None) -> dict:
    """`{"execution": {...}}` a fusionner dans le corps du lancement, ou `{}` (lancement
    ordinaire : aucun champ fourni)."""
    if not (projets or str(cible or "").strip() or fichiers_non_suivis or mode_distant
            or commande_tests):
        return {}
    execution = {"cible": str(cible or "local").strip() or "local",
                 "projets": [str(p) for p in projets or []],
                 "fichiers_non_suivis": dict(fichiers_non_suivis or {})}
    if str(mode_distant or "").strip() or str(commande_tests or "").strip():
        execution.update(mode=str(mode_distant or "agent").strip(),
                         commande=str(commande_tests or "").strip())
        if navigateur is not None:
            execution["navigateur"] = bool(navigateur)
    return {"execution": execution}


def expliquer_injoignable(reponse: dict) -> dict:
    """Serveur web arrete : on dit a l'assistant QUOI dire a l'humain (le lancer)."""
    if reponse.get("erreur") == "serveur" and "INJOIGNABLE" in str(reponse.get("message")):
        reponse["consigne"] = (
            "Le serveur web bouzecode (bouzeui) n'ecoute pas : RIEN n'a ete lance. Dis a "
            f"l'humain de le demarrer (`{COMMANDE_SERVEUR}`) puis de redemander ; la tache "
            "reste en brouillon, rien n'est perdu.")
    return expliquer_distant(reponse)


def expliquer_distant(reponse: dict) -> dict:
    """Lancement Rundeck accepte : l'execution, son lien, et les fichiers REFUSES (secrets,
    executables, trop gros...) que l'humain doit connaitre — ils ne sont PAS partis sur la VM."""
    distant = reponse.get("distant")
    if not isinstance(distant, dict) or not distant.get("ok", True):
        return reponse
    refuses = {slug: liste for slug, liste in (distant.get("fichiers_refuses") or {}).items() if liste}
    consigne = (f"Lance sur Rundeck : execution {distant.get('execution_id')} "
                f"({distant.get('url') or 'sans lien'}). Tu seras reveille a la fin (resultat, "
                "branche agent/<ticket> en mode agent, JUnit en mode tests) ou en cas d'echec.")
    if refuses:
        consigne += (" FICHIERS REFUSES, non transmis a la VM — dis-le a l'humain : "
                     + " ; ".join(f"{slug} : {liste}" for slug, liste in refuses.items()))
    reponse["consigne_distant"] = consigne
    return reponse
