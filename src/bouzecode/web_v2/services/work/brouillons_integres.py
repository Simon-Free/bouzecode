# [desc] Brouillons « Fusionner / Intégrer la branche agent/XXXX » devenus sans objet : leur cible est posée à la création, et ils sont archivés automatiquement (avec une trace) dès que cette branche est intégrée. [/desc]
"""Un brouillon d'intégration qui survit à l'intégration ment au Bureau.

Cas réel (2026-09-24) : l'assistant a noté « Fusionner la branche de l'agent e9a71355 dans
main » pendant que l'agent travaillait ; l'agent a intégré sa branche lui-même, et le brouillon
est resté affiché comme un travail à faire.

Deux temps, un seul critère :

* **à la création** (`micros.create_micro`) la cible est posée dans `micro_cibles` : la branche
  donnée explicitement, sinon celle que le titre / brief NOMME (`cible_de`) ;
* **à l'intégration** (`integration.integrate_ticket` : outil Environment d'un agent ou bouton
  « Intégrer ») et **au tick du watchdog** (branche déjà intégrée, lignes plus anciennes que
  `micro_cibles`), les brouillons qui visent cette branche ou ce ticket sont classés « faite »
  avec une trace visible.

Garde-fous : seul un brouillon (`brouillon` / `prete`) JAMAIS lancé est archivé — la condition
est dans l'UPDATE lui-même, donc un lancement concurrent gagne ; un brouillon rouvert après un
archivage automatique ne l'est plus jamais (`micro_archivages_auto`).
"""
from __future__ import annotations

import logging
import re

from bouzecode.web_v2.services.horodatage import heure_locale, maintenant_iso

from . import micros

_log = logging.getLogger(__name__)

#  Le brouillon doit PARLER d'intégrer : « Améliorer X (vu sur agent/ab12cd34) » ne vise rien.
_VERBE = re.compile(r"\b(fusion\w*|int[ée]gr\w*|merg\w*)", re.IGNORECASE)
_BRANCHE = re.compile(r"(?<![\w/])agent/([0-9a-f]{8})(?![\w/-])")
_IDENTIFIANT = re.compile(r"(?<![\w/])([0-9a-f]{8})(?![\w/-])")
_ETATS_ARCHIVABLES = ("brouillon", "prete")


def _cible(branche: str) -> dict:
    ticket = branche.split("/", 1)[1] if branche.startswith("agent/") else ""
    return {"ticket_id": ticket, "branche": branche}


def cible_de(titre: str, corps: str = "", branche: str = "") -> dict:
    """`{ticket_id, branche}` qu'un brouillon d'intégration vise EXPLICITEMENT, `{}` sinon.

    Dans l'ordre : la branche donnée ; un titre qui parle d'intégrer et dont le titre ou le
    brief nomme `agent/<id>` ; un titre qui parle d'intégrer « la branche » d'un identifiant de
    ticket (« Fusionner la branche de l'agent e9a71355 »)."""
    branche = str(branche or "").strip()
    if branche:
        return _cible(branche)
    titre = str(titre or "")
    if not _VERBE.search(titre):
        return {}
    nommee = _BRANCHE.search(f"{titre}\n{corps or ''}")
    if nommee:
        return _cible(nommee.group(0))
    identifiant = _IDENTIFIANT.search(titre) if "branche" in titre.lower() else None
    return _cible(f"agent/{identifiant.group(1)}") if identifiant else {}


def archivages() -> dict[str, dict]:
    """`{micro_id: {texte, branche, ticket_id, at}}` : les archivages automatiques connus."""
    with micros._tx() as conn:
        lignes = conn.execute(
            "SELECT micro_id, ticket_id, branche, texte, at FROM micro_archivages_auto").fetchall()
    return {l[0]: {"ticket_id": l[1], "branche": l[2], "texte": l[3], "at": l[4]} for l in lignes}


def _candidats() -> list[tuple[str, dict]]:
    """Brouillons jamais lancés ni déjà archivés automatiquement, avec leur cible."""
    with micros._tx() as conn:
        lignes = conn.execute(
            "SELECT m.id, m.titre, m.corps, c.ticket_id, c.branche FROM micros m"
            " LEFT JOIN micro_cibles c ON c.micro_id = m.id"
            " WHERE m.etat IN ('brouillon', 'prete')"
            " AND NOT EXISTS (SELECT 1 FROM micro_tickets t WHERE t.micro_id = m.id)"
            " AND NOT EXISTS (SELECT 1 FROM micro_archivages_auto a WHERE a.micro_id = m.id)"
        ).fetchall()
    candidats = []
    for ident, titre, corps, ticket_id, branche in lignes:
        #  Repli prudent pour les lignes créées avant `micro_cibles` : même règle qu'à la création.
        cible = {"ticket_id": ticket_id, "branche": branche} if branche else cible_de(titre, corps)
        if cible:
            candidats.append((ident, cible))
    return candidats


def _quand(iso: str) -> str:
    return heure_locale(iso, "le %d/%m/%Y à %H:%M")


def _trace(branche: str, integree_le: str) -> str:
    if integree_le:
        return f"Archivée automatiquement : branche {branche} intégrée {_quand(integree_le)}."
    maintenant = maintenant_iso()
    return f"Archivée automatiquement : branche {branche} intégrée (constaté {_quand(maintenant)})."


def _archiver(micro_id: str, cible: dict, integree_le: str) -> bool:
    return archiver_avec_trace(micro_id, cible, _trace(cible["branche"], integree_le))


def archiver_avec_trace(micro_id: str, cible: dict, texte: str, etat: str = "faite") -> bool:
    """UPDATE conditionnel : si la tâche vient d'être lancée, il ne touche à rien.
    `cible` = `{ticket_id, branche}` ; `texte` est la trace montrée sur la ligne."""
    maintenant = maintenant_iso()
    with micros._tx() as conn:
        classee = conn.execute(
            "UPDATE micros SET etat = ?, pourquoi = ?, updated_at = ? WHERE id = ?"
            " AND etat IN ('brouillon', 'prete')"
            " AND NOT EXISTS (SELECT 1 FROM micro_tickets WHERE micro_id = ?)",
            (etat, texte, maintenant, micro_id, micro_id)).rowcount == 1
        if classee:
            conn.execute("INSERT OR REPLACE INTO micro_archivages_auto"
                         " (micro_id, ticket_id, branche, texte, at) VALUES (?, ?, ?, ?, ?)",
                         (micro_id, cible["ticket_id"], cible["branche"], texte, maintenant))
    if classee:
        micros.add_precision(micro_id, texte, auteur="bureau")
    return classee


def _archiver_ceux_qui_visent(integres: dict[str, str], par_branche: dict[str, str]) -> list[str]:
    """`integres` : {ticket_id: intégré le} ; `par_branche` : {branche: ticket_id}."""
    archives = []
    for micro_id, cible in _candidats():
        ticket_id = cible["ticket_id"] if cible["ticket_id"] in integres \
            else par_branche.get(cible["branche"], "")
        if ticket_id and _archiver(micro_id, cible, integres[ticket_id]):
            archives.append(micro_id)
    return archives


def _branche(ticket: dict) -> str:
    return str((ticket.get("worktree") or {}).get("branch") or f"agent/{ticket.get('id') or ''}")


def apres_integration(ticket: dict) -> list[str]:
    """La branche de `ticket` vient d'être intégrée : archive les brouillons qui la visent."""
    ticket_id = str(ticket.get("id") or "")
    if not ticket_id:
        return []
    return _archiver_ceux_qui_visent({ticket_id: _integre_le(ticket)}, {_branche(ticket): ticket_id})


def _integre_le(ticket: dict) -> str:
    """Quand la branche a été fusionnée (`integration.merged_at`, ou l'ancien champ du worktree)."""
    return str((ticket.get("integration") or {}).get("merged_at")
               or (ticket.get("worktree") or {}).get("integrated_at") or "")


def balayer() -> list[str]:
    """Tick du watchdog : les brouillons qui visent une branche DÉJÀ intégrée (intégrée avant
    la création du brouillon, ou avant ce mécanisme). Aucune lecture de ticket sans candidat."""
    if not _candidats():
        return []
    from . import _persistence
    integres: dict[str, str] = {}
    par_branche: dict[str, str] = {}
    from .etat_ticket import integre
    for _slug, ticket in _persistence.all_tickets():
        if integre(ticket):
            integres[str(ticket.get("id") or "")] = _integre_le(ticket)
            par_branche[_branche(ticket)] = str(ticket.get("id") or "")
    return _archiver_ceux_qui_visent(integres, par_branche) if integres else []
