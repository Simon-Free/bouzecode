# [desc] Le champ `execution` à la CRÉATION d'un ticket (cible local | rundeck, projets, fichiers non suivis, options Rundeck) : même contrat que le lancement d'une tâche du Bureau. [/desc]
"""`POST /api/projects/{slug}/tickets` accepte le champ `execution` de `taches_execution`
(contrat : docs/specs/assistant_execution.md), pour qu'un ticket créé hors du Bureau (CLI
`bouzecode tickets creer`, script) puisse partir sur Rundeck ou recevoir des fichiers non suivis.

* `cible="local"` : le prompt reçoit la section « Execution », le ticket porte `execution`,
  puis la création suit son cours ordinaire (agent local) ;
* `cible="rundeck"` : aucun agent local — le ticket est confié au lanceur distant
  (`taches_execution.lancer_distant`) ; le watchdog (ou `bouzecode tickets suivre`) le suit.
"""
from __future__ import annotations

from .. import tickets


def valider(payload: dict, slug: str) -> dict | None:
    """L'`execution` validée, ou None (création ordinaire). Lève `Refus` (400)."""
    brut = payload.get("execution")
    if not brut:
        return None
    from .. import taches_execution
    from .refus import Refus
    if not isinstance(brut, dict):
        raise Refus("execution_invalide", "execution attend un objet {cible, projets, ...}", 400)
    return taches_execution.valider(brut, slug)


def prompt_avec_section(prompt: str, execution: dict | None) -> str:
    from .. import taches_execution
    return prompt + taches_execution.section_prompt(execution)


def lancer_sur_rundeck(slug: str, titre: str, prompt: str, execution: dict, parent: str) -> dict:
    """Crée le ticket et le confie au lanceur distant. Rend `{ticket, distant}`."""
    from .. import taches_execution
    verdict = taches_execution.lancer_distant({"titre": titre}, prompt, slug, execution, parent)
    return {"ticket": tickets.get_ticket(slug, verdict["ticket_id"]), "distant": verdict["distant"]}
