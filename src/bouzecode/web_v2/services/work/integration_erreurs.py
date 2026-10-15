# [desc] Échec d'intégration → (code machine, statut HTTP, message, détails) : les MÊMES codes pour la route ticket et la route Bureau (spec ticketing §5.4, constat C6). [/desc]
"""Un échec d'`integration.integrate_ticket` porte un `code` machine ; ce module le traduit en
réponse HTTP honnête (spec ticketing B6). La route `/api/projects/…/tickets/…/integrate` et la route du
Bureau `/api/micros/…/passages/…/integrer` relaient ainsi les mêmes codes, au lieu que la
seconde classe tout échec inconnu en « rien à intégrer » (constat C6).

    rien_a_integrer   409   pas de worktree, ou déjà intégré
    agent_actif       409   l'agent de travail tourne encore
    conflit_en_cours  409   merge inachevé / marqueurs dans le worktree
    conflit           409   conflit de fusion, renvoyé tel quel : personne n'est relancé
    merge_echoue      502   git a refusé (erreur git, arbre principal sale…) : re-tentable
"""
from __future__ import annotations

STATUTS = {"rien_a_integrer": 409, "agent_actif": 409, "conflit_en_cours": 409,
           "conflit": 409, "merge_echoue": 502}

_MESSAGES = {
    "conflit": "Conflit de fusion : relance l'agent du ticket pour le résoudre, puis réintègre.",
    "merge_echoue": "Intégration impossible : git a refusé la fusion.",
}

_DETAILS = ("state", "files", "retryable", "remede")


def traduire(resultat: dict) -> tuple[str, int, str, dict]:
    """(code, statut HTTP, message, détails) d'un résultat d'intégration en ÉCHEC."""
    code = resultat.get("code") or "merge_echoue"
    message = str(resultat.get("error") or _MESSAGES.get(code) or "intégration impossible")
    if code == "merge_echoue" and resultat.get("error"):
        message = f"{_MESSAGES['merge_echoue']} {resultat['error']}"
    details = {cle: resultat[cle] for cle in _DETAILS if cle in resultat}
    return code, STATUTS.get(code, 502), message, details
