"""Rapport des agents interrompus par le dernier arrêt serveur (crash/restart).

Construit AU BOOT (app.py::main, après reconcile_dead_agents) un SNAPSHOT FIGÉ des
travaux qui étaient « en cours » quand le serveur est tombé et qui nécessitent une
relance MANUELLE (on ne relance JAMAIS automatiquement ici — l'utilisateur décide).

Trois familles d'interrompus :
  (a) agents stampés rc=-1 au reconcile de CE boot (pid mort + IPC non-finished) ;
  (b) tickets restés en `launching` (spawn différé) sans run démarré ;
  (c) runs 'work'/'validate' dont l'agent est mort sans verdict (validate) / clôture
      propre (work), donc à reprendre.

Le rapport est persisté avec le timestamp du boot ; il expose un flag `dismissed`
(persisté) : une fois masqué par l'utilisateur, le bandeau ne réapparaît pas seul.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2.services.sessions import purge
from bouzecode.web_v2.services.work import liveness, tickets, wake

logger = logging.getLogger(__name__)

REPORT_PATH = tickets.TICKETS_DIR.parent / "interrupted_boot_report.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty() -> dict:
    return {"boot_at": "", "items": [], "dismissed": False}


def _agent_item(agent_id: str, reason: str, action: str) -> dict | None:
    """Item enrichi (ticket/slug/kind) à partir d'un agent chargé, ou None si inconnu."""
    agent = runner.load_agent(agent_id)
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
    if ticket.get("done") or ticket.get("archived"):
        for run in runs:
            by_agent.pop(str(run.get("agent_id", "") or ""), None)
        return
    # (b) ticket en cours de lancement, spawn différé jamais abouti (add_run
    # retire `launching` dès qu'un run existe) → rien à continuer, à RELANCER.
    if ticket.get("launching") and not runs:
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
    # (c) un run work/validate/merge dont l'agent est mort sans clôture utile.
    # Le bandeau ne liste que les MÉTA-AGENTS (relance MANUELLE par l'utilisateur) :
    # runs 'work' dont le ticket n'a PAS de parent manager (parent vide/absent ou
    # 'dispatcher:*'). Les SOUS-AGENTS (validate, merge, work enfant d'un manager)
    # sont repris AUTOMATIQUEMENT au boot (auto_resume.resume_subagents) → exclus du
    # bandeau, SAUF si leur reprise auto a échoué (run['auto_resume_error'] posé).
    parent = str(ticket.get("parent", "") or "")
    for run in runs:
        _scan_run(slug, ticket, run, parent, by_agent, deleted)


def _scan_run(slug: str, ticket: dict, run: dict, parent: str,
              by_agent: dict[str, dict], deleted: dict) -> None:
    """Sort d'UN run : ajouté au bandeau (méta interrompu, ou reprise auto échouée avec sa
    raison) ou retiré (agent purgé, sous-agent repris sans erreur, run non crashé)."""
    kind = str(run.get("kind", ""))
    agent_id = run.get("agent_id", "")
    if not agent_id or not (kind == "work" or kind.startswith("validate") or kind == "merge"):
        return
    agent = runner.load_agent(agent_id)
    if agent is None or agent.returncode is None:
        return  # inconnu ou encore vivant → pas interrompu
    # Agent archivé/purgé (réversible) : ABSENT de la fleet → jamais listé
    # comme interrompu (retire aussi un item (a) erroné, comme done/archived).
    if _is_deleted(str(agent_id), deleted):
        by_agent.pop(str(agent_id), None)
        return
    is_meta = kind == "work" and not wake.is_manager_parent(parent)
    auto_err = run.get("auto_resume_error")
    verdict_missing = kind.startswith("validate") and not run.get("verdict")
    # Classification dérivée de PREUVES (pid mort + close_reason + final_answer
    # + verdict) : croise plus que le seul returncode==-1, donc capte aussi une
    # mort au restart stampée autrement / sans clôture (cas 5). Un run 'delivered'
    # ou 'running' n'est jamais listé comme interrompu.
    crashed = liveness.classify_agent_run(ticket, run) == "crashed"
    item = {"agent_id": agent_id, "ticket": ticket.get("id", ""), "slug": slug,
            "kind": kind, "action": "continue"}
    if auto_err:
        # Sous-agent dont la reprise auto a échoué → bandeau AVEC la raison.
        by_agent[agent_id] = {**item, "reason": "auto_resume_failed", "error": str(auto_err)}
    elif is_meta and (crashed or verdict_missing):
        # Méta-agent interrompu → bandeau (relance manuelle). verdict_missing ne
        # concerne que 'validate' (jamais méta), donc en pratique crashed ici.
        by_agent[agent_id] = {**item,
                              "reason": "no_verdict" if verdict_missing else "crashed"}
    else:
        # Sous-agent (validate/merge/work-enfant) repris auto sans erreur, ou non crashé :
        # jamais dans le bandeau. On retire un éventuel item (a) erroné (le reconcile de ce
        # boot a pu le stamper crashé sans contexte ticket) — le run rattaché au ticket a
        # le dernier mot.
        by_agent.pop(agent_id, None)


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
    # son ticket est clos/terminal (done/archived OU classify_ticket == 'delivered'). Les
    # items fraîchement détectés (by_agent) PRIMENT toujours (raison la plus récente).
    merged = _merge_previous(by_agent, deleted)

    report = {
        "boot_at": _now(),
        "items": list(merged.values()),
        "dismissed": False,
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
    if ticket.get("done") or ticket.get("archived"):
        return True
    return liveness.classify_ticket(ticket) == "delivered"


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


def read_report() -> dict:
    if not REPORT_PATH.exists():
        return _empty()
    try:
        data = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    return data


def dismiss() -> None:
    """Masque le bandeau (persisté) sans effacer le rapport lui-même."""
    report = read_report()
    report["dismissed"] = True
    _write(report)
