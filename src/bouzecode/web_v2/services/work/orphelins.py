# [desc] Tâches orphelines (« Sans chantier ») nées d'une fin d'agent : rattachées une fois, avec trace, au chantier de la tâche de leur ancêtre. [/desc]
"""Une suite de clôture n'est « Sans chantier » que parce qu'on n'a pas su remonter.

Le pont de clôture hérite désormais le chantier de l'ANCÊTRE du ticket
(`micros.macro_du_ticket` remonte les parents). Les lignes créées avant ce correctif restent
orphelines : ce balayage (tick du watchdog) les range, UNE fois.

Garde-fous :

* seulement une tâche née d'une fin d'agent (`origine = cloture_agent`), jamais lancée,
  encore brouillon, liée à son ticket d'origine (`micro_suites`, lien « creee ») ;
* chantier trouvé par la filiation réelle (ticket → agent parent → tâche), jamais deviné ;
* `micro_rattachements_auto` garde la trace : une tâche que l'utilisateur remet « Sans
  chantier » n'est plus jamais reprise.
"""
from __future__ import annotations

from bouzecode.web_v2.services.horodatage import maintenant_iso

from . import micros


def _candidates() -> list[tuple[str, str]]:
    """`(micro_id, ticket d'origine)` des orphelines rattachables."""
    with micros._tx() as conn:
        lignes = conn.execute(
            "SELECT m.id, s.ticket_id FROM micros m JOIN micro_suites s ON s.micro_id = m.id"
            " WHERE m.macro_id = '' AND m.origine = 'cloture_agent'"
            " AND m.etat IN ('brouillon', 'prete') AND s.lien = 'creee'"
            " AND NOT EXISTS (SELECT 1 FROM micro_tickets t WHERE t.micro_id = m.id)"
            " AND NOT EXISTS (SELECT 1 FROM micro_rattachements_auto r WHERE r.micro_id = m.id)"
            " ORDER BY m.created_at").fetchall()
    vues: dict[str, str] = {}
    for micro_id, ticket_id in lignes:
        vues.setdefault(micro_id, ticket_id)
    return list(vues.items())


def _rattacher(micro_id: str, macro_id: str, ticket_id: str) -> bool:
    maintenant = maintenant_iso()
    with micros._tx() as conn:
        fait = conn.execute("UPDATE micros SET macro_id = ?, updated_at = ? WHERE id = ?"
                            " AND macro_id = '' AND etat IN ('brouillon', 'prete')",
                            (macro_id, maintenant, micro_id)).rowcount == 1
        if fait:
            conn.execute("INSERT OR REPLACE INTO micro_rattachements_auto"
                         " (micro_id, macro_id, ticket_id, at) VALUES (?, ?, ?, ?)",
                         (micro_id, macro_id, ticket_id, maintenant))
    if fait:
        micros._touch()
        titre = (micros.get_macro(macro_id) or {}).get("titre") or macro_id
        micros.add_precision(micro_id, f"Rangée automatiquement dans le chantier « {titre} » : "
                             f"elle vient de la fin d'un agent (ticket {ticket_id}) lancé depuis "
                             "une tâche de ce chantier.", auteur="bureau")
    return fait


def balayer() -> list[str]:
    """Tick du watchdog. Rend les ids rattachés. Aucune écriture sans candidate."""
    ranges = []
    for micro_id, ticket_id in _candidates():
        macro_id = micros.macro_du_ticket(ticket_id)
        if macro_id and _rattacher(micro_id, macro_id, ticket_id):
            ranges.append(micro_id)
    return ranges
