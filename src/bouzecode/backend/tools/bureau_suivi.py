# [desc] `Flotte(attendre_s=N)` : l'assistant attend (borne a 600 s) qu'une de ses taches change d'etat ou qu'un signalement arrive, et recoit le delta. [/desc]
"""Suivre sans boucler : l'assistant du TERMINAL n'est jamais reveille par le serveur (il
n'est pas un agent web), et l'assistant web peut vouloir attendre un resultat court. Une
seule attente bornee, qui rend la main des que quelque chose bouge, remplace les `Flotte()`
repetes.

L'instantane lit en process : les tickets dont il est le PARENT (`enfants.enfants_de`) et
les signalements ouverts de sa lignee. `dormir` / `horloge` sont injectables (tests).
"""
from __future__ import annotations

import time

ATTENTE_MAX = 600
INTERVALLE = 5.0


def instantane(moi: str) -> dict:
    from bouzecode.web_v2.services.work import enfants, signalements
    taches = {f["ticket_id"]: {"titre": f["titre"], "etat": f["etat"], "libelle": f["libelle"],
                               "agent_id": f["agent_id"], "issue": f["issue"]}
              for f in enfants.enfants_de(moi)}
    return {"taches": taches, "signalements": {s["id"]: s for s in signalements.de_la_lignee(moi)}}


def delta(avant: dict, apres: dict) -> dict:
    changements = [{"ticket_id": ident, **fiche,
                    "etat_avant": (avant["taches"].get(ident) or {}).get("etat", "nouveau")}
                   for ident, fiche in apres["taches"].items()
                   if (avant["taches"].get(ident) or {}).get("etat") != fiche["etat"]]
    nouveaux = [{k: s[k] for k in ("id", "gravite", "titre", "detail", "agent_id",
                                   "profondeur", "ticket_id")}
                for ident, s in apres["signalements"].items() if ident not in avant["signalements"]]
    return {"changements": changements, "nouveaux_signalements": nouveaux}


def attendre(moi: str, attendre_s: int, intervalle: float = INTERVALLE,
             dormir=time.sleep, horloge=time.monotonic) -> dict:
    """Attend au plus `attendre_s` (borne a ATTENTE_MAX) un changement, et le rend."""
    if not moi:
        return {"ok": False, "erreur": "sans_identite", "message": (
            "Attendre ne marche que pour un assistant identifie (agent web, ou terminal lance "
            "avec `bouzecode --assistant` / `/assistant`).")}
    borne = min(max(int(attendre_s or 0), 0), ATTENTE_MAX)
    debut, depart = instantane(moi), horloge()
    while True:
        ecoule = horloge() - depart
        courant = instantane(moi)
        trouve = delta(debut, courant)
        if trouve["changements"] or trouve["nouveaux_signalements"] or ecoule >= borne:
            return {"ok": True, "attendu_s": round(ecoule, 1), "borne_s": borne,
                    "expire": not (trouve["changements"] or trouve["nouveaux_signalements"]),
                    **trouve, "en_cours": [t for t in courant["taches"].values()
                                           if t["etat"] in ("lancement", "en_cours")]}
        dormir(min(intervalle, max(borne - ecoule, 0.01)))
