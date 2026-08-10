# [desc] Intégration MANUELLE d'un ticket isolé : merge du worktree dans la base, sur demande explicite. [/desc]
"""Intégration du worktree d'un ticket isolé dans sa branche de base.

Depuis le retrait de la chaîne automatique (cf. `docs/design_p10_orchestration.md`),
ce module ne spawne plus AUCUN agent de lui-même : ni validateur, ni rework. Il ne
reste que le merge, déclenché EXPLICITEMENT par le manager ou l'utilisateur via
`POST /api/tickets/<slug>/<id>/integrate`. Idempotent : ne fait rien si déjà intégré."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ...runtime import runner
from ..sessions import store
from . import tickets, worktrees
# Prédicats purs extraits (split conformité <200L) — ré-exportés ici pour compat :
# `integration.latest_verdict`, `integration._work_running` restent accessibles par
# les consommateurs (wake, reaper, routes/work) qui accèdent par MODULE.
from ._predicates import (  # noqa: F401
    _work_running,
    latest_verdict,
)

_CONFLICT_PROMPT = (
    "Tu es dans un worktree git en plein conflit de merge. `git status` liste les "
    "fichiers en conflit (marqueurs <<<<<<< ======= >>>>>>>). Résous TOUS les conflits "
    "en préservant l'intention des deux côtés, puis `git add -A` et `git commit --no-edit`. "
    "Ne modifie rien d'autre que la résolution. Termine quand `git status` est propre."
)


def _coder_recap_body(ticket: dict) -> str:
    """Formate le recap structuré du codeur (run kind=work) en markdown, pour l'embarquer
    dans le message de commit intégré. Lit `recap` depuis le session JSON du codeur (même
    source que l'endpoint GET /recap). Renvoie "" si aucun run work / aucun recap."""
    run = next((r for r in ticket.get("runs") or []
                if isinstance(r, dict) and r.get("kind") == "work"), None)
    if not run:
        return ""
    agent = runner.load_agent(run.get("agent_id"))
    if not agent or not getattr(agent, "session_path", None):
        return ""
    data = store.load_session_json(Path(agent.session_path)) or {}
    recap = data.get("recap")
    if not isinstance(recap, dict) or not recap:
        return ""
    lines: list[str] = []
    if str(recap.get("symptoms", "")).strip():
        lines += ["## Symptoms", str(recap["symptoms"]).strip(), ""]
    if str(recap.get("explanation", "")).strip():
        lines += ["## Explanation", str(recap["explanation"]).strip(), ""]
    if str(recap.get("tests", "")).strip():
        lines += ["## Tests", str(recap["tests"]).strip(), ""]
    changes = recap.get("changes")
    if isinstance(changes, list) and changes:
        lines.append("## Changes")
        for item in changes:
            if isinstance(item, dict) and str(item.get("file", "")).strip():
                summary = str(item.get("summary", "")).strip()
                lines.append(f"- {str(item['file']).strip()} — {summary}")
        lines.append("")
    return "\n".join(lines).strip()


def _run_report(run: dict | None) -> str:
    """RAPPORT (FinalAnswer) d'un run donné — lu par le digest de réveil du parent."""
    if not run:
        return ""
    agent = runner.load_agent(run["agent_id"])
    if not agent:
        return ""
    data = store.load_session_json(Path(agent.session_path)) or {}
    return tickets.extract_final_answer(data.get("messages", []))


def _reap_ticket_agents(ticket: dict) -> None:
    """Le ticket vient d'être intégré (terminal) : tuer tout process d'agent encore vivant sur
    ses session-files. Attrape le JUMEAU d'un double-spawn (même --session-file) que kill_agent
    (un seul pid tracké) rate, et qui continuerait à brûler des tokens sur du travail déjà mergé."""
    seen: set[str] = set()
    for run in ticket.get("runs") or []:
        agent_id = run.get("agent_id") if isinstance(run, dict) else None
        if not agent_id or agent_id in seen:
            continue
        seen.add(agent_id)
        runner.reap_session_processes(str(runner.AGENTS_DIR / f"{agent_id}.session.json"))


def integrate_ticket(slug: str, ticket: dict, done_agent: str = "") -> dict[str, Any]:
    """Merge le worktree du ticket dans sa branche de base. APPELÉ UNIQUEMENT depuis la
    route `/integrate` (manager ou utilisateur) — plus aucun appel automatique."""
    meta = ticket.get("worktree")
    if not meta or meta.get("state") in ("integrated", "cleaned"):
        return {"ok": False, "error": "rien à intégrer (pas de worktree ou déjà intégré)"}
    if _work_running(ticket, done_agent):
        return {"ok": False, "error": "l'agent de travail tourne encore"}

    worktrees.harvest(meta, ticket["title"], body=_coder_recap_body(ticket))
    result = worktrees.integrate(meta)

    if result["ok"]:
        worktrees.cleanup(meta)
        meta["state"] = "cleaned"
        ticket["done"] = True  # merge propre → done posé (mirror finalize_ephemeral),
        # sinon derive_status reste bloqué sur 'valide' à vie malgré le merge effectif.
        rc = result.get("restore_conflict")
        if rc:
            # Le merge EST livré, mais la restauration du WIP humain de l'arbre principal a
            # conflicté : l'arbre a été réaligné sur l'état mergé et le WIP re-stashé. On expose
            # l'info sur le meta du ticket (sérialisé côté API → visible dans l'UI) pour que
            # personne ne croie son travail non commité perdu.
            meta["restore_conflict"] = rc
            print(f"[integrate_ticket] {slug} : restore du WIP humain en conflit — WIP re-stashé "
                  f"sous {rc.get('stash_ref') or 'la pile git stash'} "
                  f"(fichiers : {', '.join(rc.get('files') or []) or '?'})", flush=True)
        tickets.update_ticket(slug, ticket)
        _reap_ticket_agents(ticket)
        return {"ok": True, "state": "integrated",
                **({"restore_conflict": rc} if rc else {})}

    if result["state"] == "conflict":
        # On relance la SESSION DU CODEUR avec les fichiers en conflit — préserve son
        # contexte — plutôt qu'un agent générique neuf. Fallback create_agent si introuvable.
        files = result["files"]
        work = next((r for r in ticket.get("runs") or []
                     if isinstance(r, dict) and r.get("kind") == "work"), None)
        coder = runner.load_agent(work["agent_id"]) if work else None
        prompt = _CONFLICT_PROMPT + "\n\nFichiers en conflit à résoudre : " + ", ".join(files)
        if coder is not None:
            runner.continue_agent(coder, prompt)
            agent_id = coder.agent_id
        else:
            # Rattacher au codeur (id réel) pour l'imbrication d'affichage, jamais un
            # littéral "dispatcher:*" qui remonterait l'agent en fausse racine.
            merge_parent = work["agent_id"] if work else "dispatcher:auto-merge"
            agent_id = runner.create_agent(_CONFLICT_PROMPT, "", meta["worktree"],
                                           parent=merge_parent).agent_id
        meta["state"] = "conflict"
        meta["conflict_agent"] = agent_id
        tickets.add_run(slug, ticket, agent_id, "merge", "")
        tickets.update_ticket(slug, ticket)
        return {"ok": False, "state": "conflict", "files": files, "agent": agent_id}

    # Échec de merge NON-conflit (erreur git, arbre principal sale, untracked à écraser) :
    # PARKÉ comme 'needs_attention' — worktree conservé, re-tentable via /integrate. Aucune
    # transition ne matche cet état : le ticket attend une décision humaine, jamais un retry
    # automatique (le retry auto était une rustine de la course entre merges automatiques).
    meta["state"] = "needs_attention"
    meta["integrate_error"] = result.get("error", "")
    tickets.update_ticket(slug, ticket)
    return {"ok": False, "state": "needs_attention", "error": result.get("error", "")}


def resume_after_conflict(slug: str, ticket: dict, done_agent: str = "") -> dict[str, Any]:
    """Après que le codeur a résolu le conflit + commité dans son worktree, RÉ-INTÈGRE.
    Ce n'est PAS une intégration automatique : c'est la SUITE d'un `/integrate` demandé
    explicitement, qui a buté sur un conflit. Sans elle, un conflit résolu resterait garé
    à vie. No-op si le ticket n'est pas en conflit, ou si le résolveur tourne encore."""
    meta = ticket.get("worktree")
    if not isinstance(meta, dict) or meta.get("state") != "conflict":
        return {"ok": False, "error": "pas en conflit"}
    conflict_agent = meta.get("conflict_agent") or ""
    agent = runner.load_agent(conflict_agent) if conflict_agent else None
    if agent is not None and runner.is_running(agent):
        return {"ok": False, "error": "résolveur de conflit encore en cours"}
    meta["state"] = "provisioned"  # ré-ouvre l'intégration
    return integrate_ticket(slug, ticket, done_agent)


def finalize_ephemeral(slug: str, ticket: dict, done_agent: str = "") -> dict[str, Any]:
    """Clôture d'un ticket ÉPHÉMÈRE (bac à sable de test) : NE MERGE JAMAIS sur la base.
    On AUTO-REAPE le bac à sable (worktree + branche jetable) immédiatement. Appelée par
    la route `/integrate` quand le ticket est éphémère. Idempotent (déjà nettoyé → no-op)."""
    meta = ticket.get("worktree")
    if _work_running(ticket, done_agent):
        return {"ok": False, "error": "l'agent de travail tourne encore"}
    if isinstance(meta, dict) and meta.get("worktree") and meta.get("state") not in ("integrated", "cleaned"):
        worktrees.reap(meta, delete_branch=True)
        meta["state"] = "cleaned"  # → derive_state='done' (terminal), pas de commit sur la base
    ticket["ephemeral"] = True
    ticket["reaped"] = True
    ticket["done"] = True
    tickets.update_ticket(slug, ticket)
    return {"ok": True, "state": "ephemeral"}
