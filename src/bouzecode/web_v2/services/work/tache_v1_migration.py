# [desc] Déplace les tâches du Bureau v1 vers les lignes (micro-tâches). One-shot, idempotent.
"""Arbitrage utilisateur du 2026-09-07 : « tu déplaces ».

Les sections « À faire » et « À décider » de l'écran lisaient la table `tasks` (v1) pendant que
« Brouillons » et la TO-DO lisaient les micro-tâches (v2). Trois listes pour le même objet, donc
trois vocabulaires et des doublons. Ici on DÉPLACE : chaque tâche v1 devient une ligne, et l'écran
n'a plus qu'une seule source.

Rien n'est détruit. La table `tasks` garde ses lignes et ses 297 « fait » : c'est de l'historique,
et le lien `micro_taches_v1` dit pour chaque tâche quelle ligne la porte désormais. C'est CE lien
qui rend la migration idempotente — pas une comparaison de titres (deux tâches peuvent porter le
même titre, et le corps d'une ligne est édité à la main dès le lendemain).

L'état d'arrivée est écrit en SQL direct plutôt que par la machine à états `TRANSITIONS`, qui
interdit `brouillon -> faite`. Cet interdit est juste POUR L'ÉCRAN (§8.5 : rien ne saute de
brouillon à faite sans être passé par un lancement) ; l'assouplir pour laisser passer un
chargement d'historique ouvrirait le trou à tous les appelants. Une migration n'est pas un geste
utilisateur : elle a le droit d'écrire l'état d'arrivée.
"""

from __future__ import annotations

from bouzecode.web_v2.services.horodatage import maintenant_iso

from . import micros as micros_service
from . import tasks as tasks_service

LIEN = """CREATE TABLE IF NOT EXISTS micro_taches_v1 (
  task_id  TEXT PRIMARY KEY,
  micro_id TEXT NOT NULL,
  at       TEXT NOT NULL DEFAULT ''
)"""

#  Ce que `outcome` peut dire d'un abandon. Tout le reste d'une tâche close est un travail FAIT :
#  le supposer abandonné effacerait la preuve que quelque chose a été livré.
ABANDONS = ("abandon", "abandonne", "abandonnee", "annule", "annulee", "rejete", "rejetee")


def _now() -> str:
    return maintenant_iso()


def _liens_connus(conn) -> dict[str, str]:
    """Les tâches déjà déplacées, lues DEPUIS la base : la mémoire de l'idempotence."""
    conn.execute(LIEN)
    rows = conn.execute("SELECT task_id, micro_id FROM micro_taches_v1").fetchall()
    return {str(row[0]): str(row[1]) for row in rows}


def etat_cible(tache: dict, a_des_tickets: bool) -> tuple[str, bool]:
    """Rend `(etat_micro, decision)` pour une tâche v1. Fonction PURE, testable sans base.

    La règle `decision` est celle que `board.py` appliquait déjà pour fabriquer la section
    « À décider » : une ligne à moi, sans dépôt et sans ticket, n'est pas du travail que
    quelqu'un peut prendre — elle attend un arbitrage. Elle devient donc une ligne INACTIVE
    dont la raison est `a_decider`, et non plus une section à part.
    """
    if str(tache.get("closed_at") or ""):
        outcome = str(tache.get("outcome") or "").strip().lower()
        return ("abandonnee" if any(mot in outcome for mot in ABANDONS) else "faite"), False
    decision = (
        str(tache.get("owner") or "") == "moi"
        and not str(tache.get("project_slug") or "").strip()
        and not a_des_tickets
    )
    return "brouillon", decision


def _origine(tache: dict) -> str:
    """`ORIGINES` n'a pas de valeur `tache_v1` et en inventer une la ferait rejeter en silence."""
    return "humain" if str(tache.get("owner") or "") == "moi" else "cloture_agent"


def _tickets_par_tache() -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for link in tasks_service.all_links():
        index.setdefault(str(link["task_id"]), []).append(link)
    return index


def _deplacer_une_tache(tache: dict, tickets: list[dict]) -> str:
    """Crée la ligne de `tache`, pose son état et ses tickets. Rend l'id de la ligne."""
    etat, decision = etat_cible(tache, bool(tickets))
    ligne = micros_service.create_micro(
        titre=str(tache.get("title") or "").strip(), corps=str(tache.get("intent") or ""),
        projet_slug=str(tache.get("project_slug") or ""), origine=_origine(tache),
        decision=decision)
    maintenant = _now()
    with micros_service._tx() as conn:
        conn.execute(LIEN)
        conn.execute("INSERT OR REPLACE INTO micro_taches_v1 (task_id, micro_id, at)"
                     " VALUES (?, ?, ?)", (str(tache["id"]), ligne["id"], maintenant))
        if etat != "brouillon":
            conn.execute("UPDATE micros SET etat = ?, updated_at = ? WHERE id = ?",
                         (etat, maintenant, ligne["id"]))
        #  Les tickets suivent la ligne : sans eux, une ligne migrée qui tourne n'aurait AUCUN
        #  signe de vie.
        for link in tickets:
            conn.execute(
                "INSERT OR IGNORE INTO micro_tickets (micro_id, slug, ticket_id, at)"
                " VALUES (?, ?, ?, ?)",
                (ligne["id"], str(link.get("slug") or ""), str(link.get("ticket_id") or ""),
                 str(tache.get("updated_at") or "")))
    return ligne["id"]


def migrer_taches_v1() -> int:
    """Déplace les tâches v1 non encore déplacées. Rend le nombre de lignes créées.

    Une tâche sans titre reste en v1 : `create_micro` la refuserait, et fabriquer un titre
    inventerait du contenu. Le passage suivant la réessaiera si elle est corrigée."""
    taches = tasks_service.list_tasks(include_closed=True)
    if not taches:
        return 0
    tickets_par_tache = _tickets_par_tache()
    with micros_service._tx() as conn:
        deja = _liens_connus(conn)
    cree = 0
    for tache in taches:
        task_id = str(tache.get("id") or "")
        if not task_id or task_id in deja or not str(tache.get("title") or "").strip():
            continue
        deja[task_id] = _deplacer_une_tache(tache, tickets_par_tache.get(task_id, []))
        cree += 1
    return cree


def ligne_de_tache(task_id: str) -> str:
    """L'id de la ligne qui porte cette tâche v1, ou chaîne vide. Sert aux tests et au support."""
    with micros_service._tx() as conn:
        conn.execute(LIEN)
        found = conn.execute("SELECT micro_id FROM micro_taches_v1 WHERE task_id = ?",
                             (task_id,)).fetchone()
    return str(found[0]) if found else ""
