# [desc] Ce qu'est devenu chaque point « reste à faire » / « à décider » d'un passage : la tâche qui le porte (lien enregistré à la clôture ou par « Créer la tâche », repli par titre exact pour l'existant), avec son statut actuel. [/desc]
"""Le récap d'un passage dit ce que l'agent a laissé ; il doit aussi dire OÙ c'est parti.

Cas réel (2026-09-24) : la carte « Passage #1 » listait « Reste à faire : Améliorer la
difficulté estimée » et « À décider : Étendre le scraping… », alors que le pont de clôture avait
créé les deux tâches. Rien ne le disait : l'utilisateur a cru qu'aucune tâche n'existait.

Le lien est ENREGISTRÉ, pas deviné : `micro_suites (ticket_id, cle) → micro_id` est écrit par le
pont de clôture (`cloture_micros`) pour chaque point déclaré — tâche créée, ou tâche déjà ouverte
qui le portait — et par « Créer la tâche » sur la carte. Seules les clôtures antérieures à cette
table passent par un repli : une tâche du Bureau dont le titre est EXACTEMENT le libellé.
"""
from __future__ import annotations

from bouzecode.web_v2.services.horodatage import maintenant_iso

from . import micros

LISTES = ("reste", "a_decider")


def cle(libelle: object) -> str:
    """Le libellé déclaré, comparable (espaces et casse) : même clé que l'anti-doublon du pont."""
    return " ".join(str(libelle or "").split()).casefold()


def lier(ticket_id: str, libelle: str, micro_id: str, lien: str = "creee") -> None:
    """Le point `libelle` du passage `ticket_id` est porté par la tâche `micro_id`."""
    if not (ticket_id and cle(libelle) and micro_id):
        return
    with micros._tx() as conn:
        conn.execute("INSERT OR REPLACE INTO micro_suites (ticket_id, cle, micro_id, lien, at)"
                     " VALUES (?, ?, ?, ?, ?)",
                     (ticket_id, cle(libelle), micro_id, lien,
                      maintenant_iso()))


def index() -> dict[str, dict[str, dict]]:
    """`{ticket_id: {cle: {micro_id, lien}}}` en UNE requête, pour tout le Bureau."""
    with micros._tx() as conn:
        lignes = conn.execute("SELECT ticket_id, cle, micro_id, lien FROM micro_suites").fetchall()
    suites: dict[str, dict[str, dict]] = {}
    for ticket_id, cle_point, micro_id, lien in lignes:
        suites.setdefault(ticket_id, {})[cle_point] = {"micro_id": micro_id, "lien": lien}
    return suites


# ------------------------------------------------------------------ vue du Bureau


def _exact(titre: object) -> str:
    return " ".join(str(titre or "").split())


def _vue(tache: dict | None, lien: str) -> dict | None:
    if tache is None:
        return None
    return {"id": tache["id"], "titre": tache.get("titre", ""), "lien": lien,
            "statut_ui": tache.get("statut_ui", ""), "libelle_statut": tache.get("libelle_statut", "")}


def _par_titre(libelle: str, par_titre: dict[str, list[dict]], porteuse: dict) -> dict | None:
    """Repli des clôtures sans lien enregistré : titre exact, même chantier d'abord."""
    candidates = [t for t in par_titre.get(_exact(libelle), []) if t["id"] != porteuse["id"]]
    meme_chantier = [t for t in candidates if t.get("macro_id") == porteuse.get("macro_id")]
    choix = meme_chantier or candidates
    return max(choix, key=lambda t: str(t.get("created_at") or "")) if choix else None


def _suite(libelle: str, connues: dict, par_id: dict, par_titre: dict, porteuse: dict):
    enregistree = connues.get(cle(libelle))
    if enregistree:
        #  Un lien enregistré vers une tâche supprimée ne se rabat pas sur un homonyme.
        return _vue(par_id.get(enregistree["micro_id"]), enregistree["lien"])
    return _vue(_par_titre(libelle, par_titre, porteuse), "titre")


def relier(lignes: list[dict], suites: dict[str, dict[str, dict]]) -> None:
    """Ajoute à chaque récap de passage `suites = {reste: [...], a_decider: [...]}`, une entrée
    par point (même ordre) : la tâche qui le porte `{id, titre, statut_ui, libelle_statut,
    lien}`, ou None. Appelée APRÈS l'enrichissement de toutes les lignes (statuts connus)."""
    par_id = {t["id"]: t for t in lignes}
    par_titre: dict[str, list[dict]] = {}
    for tache in lignes:
        par_titre.setdefault(_exact(tache.get("titre")), []).append(tache)
    for tache in lignes:
        for passage in tache.get("passages") or []:
            recap = passage.get("recap")
            if recap:
                connues = suites.get(str(passage.get("ticket_id") or ""), {})
                recap["suites"] = {liste: _suites_de(recap.get(liste), connues, par_id, par_titre, tache)
                                   for liste in LISTES}


def _suites_de(points, connues: dict, par_id: dict, par_titre: dict, porteuse: dict) -> list:
    return [_suite(p, connues, par_id, par_titre, porteuse) for p in points or []]


# ------------------------------------------------------------------ « Créer la tâche »


def _corps_declare(passage: dict, libelle: str) -> str:
    """Le brief que l'agent avait écrit pour ce point dans sa réponse finale ("" sinon)."""
    from bouzecode.web_v2.runtime.runner import agent_fiche

    from . import taches_vue
    agent = agent_fiche.load_agent(passage["agent_id"]) if passage.get("agent_id") else None
    recap = taches_vue.recap_d_agent(agent) if agent is not None else {}
    return str((recap.get("corps") or {}).get(cle(libelle)) or "")


def creer(micro_id: str, ticket_id: str, libelle: str, decision: bool) -> dict:
    """Crée la tâche d'un point resté sans tâche, dans le chantier et le dépôt du passage, et
    l'enregistre comme sa suite. Idempotent : un point déjà porté rend sa tâche."""
    from .taches_actions import Refus, _micro_ou_refus, passages
    libelle = " ".join(str(libelle or "").split())
    if not libelle:
        raise Refus("libelle_requis", "Quel point du récap faut-il transformer en tâche ?")
    micro = _micro_ou_refus(micro_id)
    passage = next((p for p in passages(micro) if p["ticket_id"] == ticket_id), None)
    if passage is None:
        raise Refus("passage_inconnu", f"le passage {ticket_id} n'appartient pas à cette tâche", 404)
    deja = index().get(ticket_id, {}).get(cle(libelle))
    existante = micros.get_micro(deja["micro_id"]) if deja else None
    if existante is not None:
        return {"ok": True, "micro": existante, "deja": True}
    nouvelle = micros.create_micro(
        titre=libelle, corps=_corps_declare(passage, libelle), macro_id=micro.get("macro_id", ""),
        projet_slug=passage.get("slug") or micro.get("projet_slug", ""), origine="cloture_agent",
        decision=decision)
    lier(ticket_id, libelle, nouvelle["id"], "manuelle")
    return {"ok": True, "micro": nouvelle, "deja": False}
