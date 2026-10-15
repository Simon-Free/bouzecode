"""Suivre une execution distante et en recuperer le resultat (rapport de tests, captures, branche agent).

`recuperer` rapatrie `<share>/<run_id>/resultat/` sous ~/.bouzecode/remote/resultats/<run_id>/,
reimporte en mode agent chaque `<slug>.resultat.bundle` en `agent/<ticket>` dans le depot local,
puis (par defaut) supprime le job Rundeck et le dossier du file share de cette execution.
"""
import json
from pathlib import Path

import requests

from bouzecode.remote import registre
from bouzecode.remote.paquet.import_resultat import importer_bundle_resultat
from bouzecode.remote.transport import settings
from bouzecode.remote.transport.fileshare_client import ClientFileShare, ErreurFileShare
from bouzecode.remote.transport.rundeck_client import ClientRundeck, ErreurRundeck

LIGNES_JOURNAL_SUIVI = 40


def _refus(code: str, message: str) -> dict:
    return {"ok": False, "code": code, "message": message}


def suivre(execution_id: str) -> dict:
    if registre.lire(execution_id) is None:
        return _refus("execution_inconnue", f"execution {execution_id} absente du registre local")
    rundeck = ClientRundeck(settings.charger_reglages())
    try:
        etat = rundeck.etat_execution(str(execution_id))
        journal = rundeck.journal_execution(str(execution_id))
    except (ErreurRundeck, requests.RequestException) as erreur:
        return _refus("acces_rundeck_manquant", f"{type(erreur).__name__}: {str(erreur)[:300]}")
    return {"ok": True, **etat, "journal_fin": "\n".join(journal.splitlines()[-LIGNES_JOURNAL_SUIVI:])}


def telecharger_arborescence(share: ClientFileShare, distant: str, local: Path) -> list[Path]:
    local.mkdir(parents=True, exist_ok=True)
    fichiers = []
    for entree in share.lister(distant):
        if entree["dossier"]:
            fichiers += telecharger_arborescence(share, f"{distant}/{entree['nom']}", local / entree["nom"])
        else:
            (local / entree["nom"]).write_bytes(share.lire(f"{distant}/{entree['nom']}"))
            fichiers.append(local / entree["nom"])
    return fichiers


def importer_branches(fiche: dict, bilan: dict, dossier: Path) -> dict:
    branches = {}
    projets = {p["slug"]: p for p in fiche["projets"]}
    for slug, info in (bilan.get("projets") or {}).items():
        if info.get("bundle") and slug in fiche["depots"]:
            # Meme nom de branche des deux cotes : `agent/<ticket>` (cf. lancement.branche_agent).
            # `base` et `depot` servent au worktree local de retour (integrate suit le chemin local).
            branche = projets[slug]["branche_travail"]
            if not branche.startswith("agent/"):  # fiche d'avant le 2026-10-06 (bz/<run_id>)
                branche = f"agent/{fiche['ticket_id']}"
            branches[slug] = {**importer_bundle_resultat(Path(fiche["depots"][slug]), dossier / info["bundle"],
                                                         projets[slug]["branche_travail"], branche),
                              "base": projets[slug].get("branche") or "", "depot": fiche["depots"][slug]}
    return branches


def nettoyer(fiche: dict, rundeck: ClientRundeck, share: ClientFileShare) -> None:
    rundeck.supprimer_job(fiche["job_id"])
    share.supprimer_arborescence(fiche["share"])


def recuperer(execution_id: str, nettoyer_distant: bool = True) -> dict:
    fiche = registre.lire(execution_id)
    if fiche is None:
        return _refus("execution_inconnue", f"execution {execution_id} absente du registre local")
    reglages = settings.charger_reglages()
    rundeck, share = ClientRundeck(reglages), ClientFileShare(reglages)
    try:
        etat = rundeck.etat_execution(str(execution_id))
        if not etat["termine"]:
            return _refus("en_cours", f"execution {execution_id} encore {etat['statut']}")
        dossier = registre.racine_locale() / "resultats" / fiche["run_id"]
        dossier.mkdir(parents=True, exist_ok=True)
        (dossier / "journal_rundeck.log").write_text(rundeck.journal_execution(str(execution_id)), encoding="utf-8")
        fichiers = telecharger_arborescence(share, f"{fiche['share']}/resultat", dossier)
    except (ErreurRundeck, ErreurFileShare, requests.RequestException) as erreur:
        return _refus("acces_rundeck_manquant", f"{type(erreur).__name__}: {str(erreur)[:300]}")
    resultat_json = dossier / "resultat.json"
    bilan = json.loads(resultat_json.read_text(encoding="utf-8")) if resultat_json.exists() else {}
    branches = importer_branches(fiche, bilan, dossier) if fiche["mode"] == "agent" else {}
    if nettoyer_distant:
        nettoyer(fiche, rundeck, share)
    return {
        "ok": True, "execution_id": str(execution_id), "statut": etat["statut"], "url": etat["url"],
        "code": bilan.get("code", "resultat_absent"), "dossier_local": str(dossier),
        "junit": str(dossier / "junit.xml") if (dossier / "junit.xml").exists() else None,
        "captures": [str(f) for f in fichiers if "captures" in f.parts],
        "branches": branches, "nettoye": nettoyer_distant,
        # Raison de fin de l'agent (fiche de cloture du CLI, cf. vm_runner.lire_cloture) : vide
        # en mode tests ou si l'agent n'a rien ecrit.
        "close_reason": str(bilan.get("close_reason") or ""),
        "close_detail": str(bilan.get("close_detail") or ""),
        "final_answer": bool(bilan.get("final_answer")),
    }
