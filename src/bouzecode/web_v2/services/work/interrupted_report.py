"""Rapport des agents interrompus par le dernier arrêt serveur (crash/restart).

Construit AU BOOT (app.py::main, après reconcile_dead_agents) un SNAPSHOT FIGÉ des
travaux qui étaient « en cours » quand le serveur est tombé et qui nécessitent une
relance MANUELLE (on ne relance JAMAIS automatiquement ici — l'utilisateur décide).

Trois familles d'interrompus :
  (a) agents stampés rc=-1 au reconcile de CE boot (pid mort + IPC non-finished) ;
  (b) tickets restés en `launching` (spawn différé) sans run démarré ;
  (c) runs 'work' dont l'agent est mort sans clôture propre, donc à reprendre.

Le rapport est persisté avec le timestamp du boot, servi par GET /api/agents?state=interrupted.
"""
from __future__ import annotations

import json
import logging

from bouzecode.web_v2.services.horodatage import maintenant_iso

from bouzecode.web_v2.runtime.runner import agent_fiche
from bouzecode.web_v2.services.sessions import purge
from bouzecode.web_v2.services.work import liveness, tickets, wake
from bouzecode.web_v2.services.work.fsm import etats

logger = logging.getLogger(__name__)

REPORT_PATH = tickets.TICKETS_DIR.parent / "interrupted_boot_report.json"


def _now() -> str:
    return maintenant_iso("auto")


def _empty() -> dict:
    return {"boot_at": "", "items": []}


def _agent_item(agent_id: str, reason: str, action: str) -> dict | None:
    """Item enrichi (ticket/slug/kind) à partir d'un agent chargé, ou None si inconnu."""
    agent = agent_fiche.load_agent(agent_id)
    if agent is None:
        return None
    return {
        "agent_id": agent_id,
        "ticket": agent.ticket_id,
        "slug": agent.ticket_slug,
        "kind": agent.run_kind,
        "reason": reason,
        "action": action,
    }


def _is_deleted(agent_id: str, deleted: dict) -> bool:
    """Vrai si l'agent est archivé/purgé (réversible) — MÊME critère que la fleet
    (fleet._agent_tree_uncached : `f"agent/{id}" not in purge.load_deleted()`). Un tel
    agent DISPARAÎT de la liste des agents : il ne doit jamais ressortir « crashed »
    dans le bandeau des interrompus (sinon incohérence source-statut ↔ fleet)."""
    return bool(agent_id) and f"agent/{agent_id}" in deleted


def _scan_tickets(by_agent: dict[str, dict], deleted: dict) -> None:
    """Ajoute les interrompus dérivés des tickets (cas b et c) dans `by_agent`.

    Un item déjà présent (cas a — crashé) n'est jamais écrasé : (a) prime, il porte
    la raison la plus précise. Le cas (b) n'a pas d'agent_id (aucun run démarré) → il
    est indexé sur une clé synthétique "launching:<slug>:<id>".
    """
    # `all_tickets()` lit le store SQLite (UNE requête, tous projets, archivés compris — les
    # done/archived sont nécessaires ici pour RETIRER un item (a) erroné). Itérait avant
    # `TICKETS_DIR.glob("*.json")` : depuis la migration SQLite il n'en reste AUCUN, donc les
    # cas (b) et (c) ne remontaient PLUS JAMAIS dans le bandeau, en silence.
    for slug, ticket in tickets.all_tickets():
        _scan_one_ticket(slug, ticket, by_agent, deleted)


def _scan_one_ticket(slug: str, ticket: dict, by_agent: dict[str, dict], deleted: dict) -> None:
    """Sort d'UN ticket : retiré du rapport s'il est terminal, ajouté s'il est resté en
    `launching` sans run (cas b), sinon chacun de ses runs est examiné (cas c)."""
    runs = [r for r in (ticket.get("runs") or []) if isinstance(r, dict)]
    # Ticket terminal (done/archived) : aucun run à lister, même si le cas (a)
    # a stampé un de ses agents comme crashé au reconcile de ce boot. On retire
    # explicitement ces agent_id d'un éventuel item (a) erroné.
    if ticket.get("state") in etats.CLOS or ticket.get("archived"):
        for run in runs:
            by_agent.pop(str(run.get("agent_id", "") or ""), None)
        return
    # (b) ticket en cours de lancement, spawn différé jamais abouti (add_run
    # retire `launching` dès qu'un run existe) → rien à continuer, à RELANCER.
    if ticket.get("state") == etats.PROVISIONING and not runs:
        key = f"launching:{slug}:{ticket.get('id', '')}"
        by_agent.setdefault(key, {
            "agent_id": "",
            "ticket": ticket.get("id", ""),
            "slug": slug,
            "kind": "work",
            "reason": "launching_no_run",
            "action": "launch",
        })
        return
    # (c) un run work/merge dont l'agent est mort sans clôture utile.
    # Le bandeau ne liste que les MÉTA-AGENTS (relance MANUELLE par l'utilisateur) :
    # runs 'work' dont le ticket n'a PAS de parent manager (parent vide/absent ou
    # 'dispatcher:*'). Les SOUS-AGENTS (merge, work enfant d'un manager) sont SIGNALÉS au
    # boot à leur parent, ou à l'humain par un signalement (interruptions_boot) → hors bandeau.
    parent = str(ticket.get("parent", "") or "")
    for run in runs:
        _scan_run(slug, ticket, run, parent, by_agent, deleted)


_KINDS_SUIVIS = ("work", "merge")


def _run_suivi(kind: str, agent_id: str) -> bool:
    return bool(agent_id) and kind in _KINDS_SUIVIS


def _item_du_bandeau(slug: str, ticket: dict, run: dict, parent: str, agent_id: str,
                     kind: str) -> dict | None:
    """L'entrée du bandeau pour ce run, ou None s'il n'a rien à y faire.

    - méta-agent (work d'un parent non manager) planté → bandeau ;
    - sinon (sous-agent, signalé à part ; run non crashé) → jamais dans le bandeau.
    La classification croise pid mort + close_reason + final_answer : elle capte
    aussi une mort au restart stampée autrement."""
    item = {"agent_id": agent_id, "ticket": ticket.get("id", ""), "slug": slug,
            "kind": kind, "action": "continue"}
    if kind != "work" or wake.is_manager_parent(parent):
        return None
    if liveness.classify_agent_run(ticket, run) == "crashed":
        return {**item, "reason": "crashed"}
    return None


def _scan_run(slug: str, ticket: dict, run: dict, parent: str,
              by_agent: dict[str, dict], deleted: dict) -> None:
    """Sort d'UN run : ajouté au bandeau (méta interrompu) ou retiré (agent purgé, sous-agent,
    run non crashé). Le run
    rattaché au ticket a le dernier mot sur un item posé au boot sans contexte."""
    kind = str(run.get("kind", ""))
    agent_id = run.get("agent_id", "")
    if not _run_suivi(kind, agent_id):
        return
    agent = agent_fiche.load_agent(agent_id)
    if agent is None or agent.returncode is None:
        return  # inconnu ou encore vivant → pas interrompu
    if _is_deleted(str(agent_id), deleted):
        by_agent.pop(str(agent_id), None)  # archivé/purgé : absent de la flotte
        return
    item = _item_du_bandeau(slug, ticket, run, parent, agent_id, kind)
    if item is None:
        by_agent.pop(agent_id, None)
    else:
        by_agent[agent_id] = item


def build_boot_report(crashed_ids: list[str]) -> dict:
    """Construit et persiste le snapshot des interrompus. Best-effort : un échec ne
    doit jamais empêcher le serveur de démarrer (l'appelant l'entoure d'un try)."""
    by_agent: dict[str, dict] = {}
    # Agents archivés/purgés (réversible) : EXCLUS du bandeau, au MÊME critère que la
    # fleet (fleet._agent_tree_uncached). Sans ce filtre, un agent retiré de la liste des
    # agents mais encore chargeable ressort « crashed » ici → incohérence UI (bug ticket).
    deleted = purge.load_deleted()
    # (a) agents crashés au reconcile de CE boot — la source la plus fiable.
    for agent_id in crashed_ids:
        if _is_deleted(str(agent_id), deleted):
            continue
        item = _agent_item(agent_id, reason="crashed", action="continue")
        if item is not None:
            by_agent[agent_id] = item
    # (b) + (c) dérivés des tickets.
    _scan_tickets(by_agent, deleted)

    # FUSION avec le rapport précédent (cas 4) : deux redémarrages rapprochés ne doivent
    # PAS perdre les items non traités du premier boot. Un item survivant sort SEULEMENT si
    # son ticket est clos/terminal (clos, archivé ou livré : `ticket.state`). Les
    # items fraîchement détectés (by_agent) PRIMENT toujours (raison la plus récente).
    merged = _merge_previous(by_agent, deleted)

    report = {
        "boot_at": _now(),
        "items": list(merged.values()),
    }
    _write(report)
    return report


def _item_key(item: dict) -> str:
    """Clé stable d'un item : agent_id si présent, sinon la clé synthétique launching."""
    agent_id = item.get("agent_id") or ""
    if agent_id:
        return agent_id
    return f"launching:{item.get('slug', '')}:{item.get('ticket', '')}"


def _ticket_is_resolved(slug: str, ticket_id: str) -> bool:
    """Vrai si le ticket est clos/terminal : le retirer du rapport est légitime.

    Lit UNE ligne par sa clé (`get_ticket` → `_load_one`). Lisait avant le JSON
    `TICKETS_DIR/<slug>.json` et décodait toute la liste pour trouver un id : ce fichier
    n'existe plus, la lecture échouait donc TOUJOURS et renvoyait False — tout item du
    rapport précédent survivait indéfiniment, même ticket mergé."""
    ticket = tickets.get_ticket(slug, ticket_id)
    if ticket is None:
        return True  # ticket disparu → considéré résolu
    if ticket.get("state") in etats.CLOS or ticket.get("archived"):
        return True
    return ticket.get("state") == etats.DELIVERED


def _merge_previous(by_agent: dict[str, dict], deleted: dict) -> dict[str, dict]:
    """Fusionne les items du boot courant avec ceux du rapport précédent NON résolus.
    Les nouveaux priment ; un ancien item n'est conservé QUE si son ticket n'est pas
    clos/terminal — jamais retiré au seul motif qu'un boot est passé (cas 4)."""
    merged: dict[str, dict] = {}
    previous = read_report()
    for item in previous.get("items") or []:
        if not isinstance(item, dict):
            continue
        # Agent archivé/purgé APRÈS le snapshot précédent : ne survit PAS à la fusion
        # (couvre l'archivage post-boot sans reboot — sinon le snapshot figé le garderait).
        if _is_deleted(str(item.get("agent_id", "") or ""), deleted):
            continue
        key = _item_key(item)
        if _ticket_is_resolved(item.get("slug", ""), item.get("ticket", "")):
            continue
        merged[key] = item
    # Les items fraîchement détectés écrasent (raison la plus récente/précise).
    for item in by_agent.values():
        merged[_item_key(item)] = item
    return merged


def _write(report: dict) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = REPORT_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(REPORT_PATH)


def _encore_interrompu(item: dict) -> bool:
    """Cet item décrit-il ENCORE un travail interrompu, à l'instant où on le lit ?

    Le rapport est figé au boot, à dessein : il dit ce que le dernier arrêt a
    interrompu. Mais il est LU longtemps après, et le monde a bougé. Le servir tel
    quel fait annoncer « planté » deux catégories d'agents qui ne le sont pas :

    1. **Les ressuscités.** Un agent listé ici a pu être relancé depuis. Constaté le
       2026-08-24 : après un redémarrage à 11:15, `4b69bb8ab056` (tour 21) et
       `40435234c772` (tour 16), tous deux EN COURS, sortaient `crashed`.
    2. **Ceux qui avaient livré.** `build_boot_report` prend pour argent comptant les
       `crashed_ids` du reconcile de boot, sans relire la clôture de la session. Or
       un agent surpris dans sa boucle chaude par l'arrêt du serveur a déjà écrit sa
       `final_answer`. Même jour : `f52cb5297f4f` (143 tours), `c25290d58b2e` (48) et
       `d5f9b8eb83c6` (30) portaient tous `close_reason=final_answer` — trois
       livraisons présentées comme des pannes.

    D'où un seul critère, celui du classifieur partagé : on ne garde que ce qu'il
    appelle encore `crashed`. `MISSING` sort aussi — un agent dont l'enregistrement a
    disparu ne peut plus être relancé, l'afficher n'offre aucune action.

    Le snapshot n'est PAS réécrit : il reste la trace de ce que l'arrêt a cassé. Le
    filtre est à la LECTURE, sur la même source que la flotte et la liste de tickets,
    pour qu'aucune vue ne contredise les autres."""
    agent_id = str(item.get("agent_id") or "")
    if not agent_id:
        return True
    run = {"agent_id": agent_id, "kind": item.get("kind") or "work"}
    return liveness.classify_agent_run({}, run) == "crashed"


def read_report() -> dict:
    if not REPORT_PATH.exists():
        return _empty()
    try:
        data = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    items = data.get("items")
    if isinstance(items, list):
        data = {**data, "items": [i for i in items
                                  if isinstance(i, dict) and _encore_interrompu(i)]}
    return data
