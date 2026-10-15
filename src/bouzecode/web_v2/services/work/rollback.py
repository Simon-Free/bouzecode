# [desc] Creates an idempotent human-requested rollback task whose brief carries the merge commit to revert. [/desc]
"""Un humain qui veut annuler un passage intégré ne lance pas `git revert` depuis le web : la
base peut être sale ou déjà avancée, un revert peut entrer en conflit. Il DEMANDE le rollback :
une tâche du Bureau, dans le chantier et le dépôt du passage, dont le brief porte le commit de
merge à annuler. Un agent l'exécute et arbitre les conflits, comme tout autre travail."""
from __future__ import annotations

from . import micros, suites_cloture, tickets

LIBELLE = "Annuler l'intégration du passage {ticket_id}"


def _brief(slug: str, ticket_id: str, ticket: dict, merge_commit: str, motif: str) -> str:
    titre = str(ticket.get("title") or ticket.get("titre") or "")
    lignes = [
        f"Rollback demandé par un humain du passage {ticket_id}"
        + (f" (« {titre} »)" if titre else "") + f", dépôt `{slug}`.",
        "",
        f"Commit de merge à annuler : `{merge_commit}`.",
        f"Commande : `git revert -m 1 {merge_commit}` sur la branche de base si c'est un commit de "
        "merge (deux parents), puis tests verts.",
        "Conflit : arbitre-le et dis quel côté tu as gardé ; ne réécris jamais l'historique.",
    ]
    base_avant = str((ticket.get("integration") or {}).get("base_avant") or "")
    if base_avant:
        lignes.insert(4, f"Intégration en avance rapide (un seul parent) : "
                         f"`git revert --no-edit {base_avant}..{merge_commit}`.")
    if motif:
        lignes += ["", f"Motif : {motif}"]
    return "\n".join(lignes)


def demander(micro_id: str, ticket_id: str, motif: str = "") -> dict:
    """Crée (ou rend, si déjà demandée) la tâche de rollback du passage intégré `ticket_id`."""
    from .taches_actions import Refus, _micro_ou_refus, passages
    micro = _micro_ou_refus(micro_id)
    passage = next((p for p in passages(micro) if p["ticket_id"] == ticket_id), None)
    if passage is None:
        raise Refus("passage_inconnu", f"le passage {ticket_id} n'appartient pas à cette tâche", 404)
    slug = str(passage.get("slug") or micro.get("projet_slug") or "")
    ticket = tickets.get_ticket(slug, ticket_id) if slug else None
    merge_commit = str(((ticket or {}).get("integration") or {}).get("merge_commit") or "")
    if not merge_commit:
        raise Refus("pas_integre", "Ce passage n'a pas été intégré : rien à annuler.", 409)
    libelle = LIBELLE.format(ticket_id=ticket_id)
    deja = suites_cloture.index().get(ticket_id, {}).get(suites_cloture.cle(libelle))
    existante = micros.get_micro(deja["micro_id"]) if deja else None
    if existante is not None:
        return {"ok": True, "micro": existante, "deja": True}
    motif = " ".join(str(motif or "").split())
    nouvelle = micros.create_micro(
        titre=libelle, corps=_brief(slug, ticket_id, ticket, merge_commit, motif),
        macro_id=micro.get("macro_id", ""), projet_slug=slug, origine="humain")
    suites_cloture.lier(ticket_id, libelle, nouvelle["id"], "rollback")
    return {"ok": True, "micro": nouvelle, "deja": False, "merge_commit": merge_commit}
