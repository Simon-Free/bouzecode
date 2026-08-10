# [desc] Détecte qu'un ticket dispatché recouvre le périmètre d'un ticket frère déjà ouvert. [/desc]
"""Un livrable, un ticket. Deux frères au périmètre identique = du travail jeté.

Cas réel observé : un manager a dispatché trois écrivains sur la même « mesure
directe ». Ils ont
produit trois implémentations concurrentes du même service (`view_service.py`,
`views_service.py`, `view_tracker.py`). Rien côté serveur ne l'a vu. Ce module le voit —
sans rien demander au LLM, en comparant les périmètres des prompts.
"""
from __future__ import annotations

from typing import Any

from . import signature

OVERLAP_FLAG_KEY = "scope_overlap"
# Calibré sur six prompts réels d'un même manager : les rédactions d'un MÊME livrable
# passent au-dessus, les deux moitiés distinctes de la demande restent en dessous.
OVERLAP_THRESHOLD = 0.40
# En dessous, le prompt ne DÉCRIT aucun périmètre : il ne reste que du texte de service.
# Deux prompts sans contenu se ressemblent trivialement à 100 % — les comparer produirait
# des faux positifs à chaque dispatch. Sans preuve, le garde-fou s'abstient.
MIN_SIGNATURE = 8


def _est_concurrent(ticket: dict[str, Any]) -> bool:
    """Un frère ne « couvre » un livrable que s'il est encore vivant : un ticket archivé
    n'a rien livré, le redispatcher est légitime."""
    return not ticket.get("archived")


def overlapping_siblings(prompt: str, siblings: list[dict[str, Any]],
                         threshold: float = OVERLAP_THRESHOLD) -> list[dict[str, Any]]:
    """Les tickets frères dont le périmètre recouvre `prompt`, du plus proche au moins proche.

    Chaque entrée : `{id, title, score}`. Liste vide = aucun recouvrement détecté.
    """
    candidat = signature.scope_signature(prompt)
    if len(candidat) < MIN_SIGNATURE:
        return []
    trouves = []
    for frere in siblings:
        if not _est_concurrent(frere):
            continue
        frere_signature = signature.scope_signature(frere.get("prompt") or "")
        if len(frere_signature) < MIN_SIGNATURE:
            continue
        score = signature.similarity(candidat, frere_signature)
        if score >= threshold:
            trouves.append({"id": frere.get("id", ""), "title": frere.get("title", ""),
                            "score": round(score, 2)})
    return sorted(trouves, key=lambda t: t["score"], reverse=True)


def overlap_comment(matches: list[dict[str, Any]]) -> str:
    """Le commentaire posé sur le ticket ET rendu au manager. Il NOMME les frères : sans
    l'identifiant, le manager ne peut ni relire ni abandonner le doublon."""
    lignes = [f"  - {m['id']} ({int(m['score'] * 100)} % de périmètre commun) — {m['title'][:70]}"
              for m in matches]
    pluriel = "s" if len(matches) > 1 else ""
    return (f"⚠️ PÉRIMÈTRE EN DOUBLON : ce ticket recouvre {len(matches)} ticket{pluriel} "
            f"frère{pluriel} déjà ouvert{pluriel} sous le même parent :\n"
            + "\n".join(lignes)
            + "\nUN SEUL ticket d'implémentation par livrable. Si c'est bien le même livrable, "
              "abandonne l'un des deux ; sinon, redispatche avec un périmètre explicitement "
              "disjoint (fichiers/tables/routes différents).")


def overlap_warning(matches: list[dict[str, Any]]) -> str:
    """Version courte, destinée au `tool_result` du manager."""
    ids = ", ".join(m["id"] for m in matches)
    return (f"PÉRIMÈTRE EN DOUBLON — ce ticket recouvre le périmètre de : {ids}. "
            f"UN SEUL ticket d'implémentation par livrable : abandonne le doublon ou "
            f"redispatche avec un périmètre disjoint.")
