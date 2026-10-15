# [desc] Refus du modèle (`content_refusal`, filtre de contenu du fournisseur) : signalement visible de l'humain et du parent, pour un run local comme pour une exécution Rundeck. [/desc]
"""Un refus n'est ni une livraison ni un plantage : la boucle a coupé proprement parce que le
filtre de contenu a bloqué le tour malgré les relances du backend (blocage aléatoire : une
relance suffit souvent, sinon un autre modèle). Le ticket
finit `idle_no_delivery` (code `content_refusal`, cf. `close_reasons.issue_de_fin`) et ce
signalement dit quoi faire — dans « À traiter » et dans le digest du parent au réveil."""
from __future__ import annotations

from . import signalements

REFUS_MODELE = "content_refusal"
TITRE = "Le modèle a refusé la consigne"
ACTION = "Le modèle a refusé la consigne : reformule-la ou relance (au besoin sur un autre modèle)."


def parents_de(ticket: dict) -> list[str]:
    """Le parent à prévenir — jamais l'identité technique d'un dispatcher."""
    parent = str(ticket.get("parent") or "")
    return [parent] if parent and not parent.startswith("dispatcher:") else []


def signaler(slug: str, ticket: dict, agent_id: str, detail: str = "") -> dict:
    return signalements.creer(
        "alerte", f"{TITRE} : {ticket.get('title') or ticket['id']}",
        detail=detail or "Filtre de contenu du fournisseur : le run s'est arrêté sans rien livrer.",
        action_attendue=ACTION, agent_id=agent_id, parents=parents_de(ticket),
        ticket_slug=slug, ticket_id=ticket["id"])
