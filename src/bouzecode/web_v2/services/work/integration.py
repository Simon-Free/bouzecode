# [desc] Intégration MANUELLE d'un ticket isolé : merge du worktree dans la base sur demande explicite, transitions delivered → integrating → closed | conflict | delivered. [/desc]
"""Intégration du worktree d'un ticket isolé dans sa branche de base.

Aucun agent n'est lancé d'ici : ni validateur, ni rework, ni résolveur de conflit. Le merge
est déclenché EXPLICITEMENT par le manager ou l'utilisateur (`POST …/integrate`), ou par
l'agent lui-même (outil `Environment`, « auto-intégration » pendant son run).

Machine à états (spec §4) : `delivered` (ou `conflict` résolu) → `integrating` → `closed`
(merge propre, `integration.merged_at`), `conflict` (fichiers en cause), ou `delivered` avec la
raison `merge_echoue` (git a refusé). Une AUTO-intégration pendant le run ne change pas l'état :
elle note `integration`, et la fin du run la conclut (`constats.fin_de_run`)."""
from __future__ import annotations

from bouzecode.web_v2.services.horodatage import maintenant_iso
from typing import Any

from ...runtime.runner import agent_arret, agent_fiche
from . import delivery, etat_ticket, ticket_fsm, tickets, worktrees
from ._integration_recap import archiver_les_brouillons_de_fusion, coder_recap_body
from .fsm import cycle_des_runs, etats


def _maintenant() -> str:
    return maintenant_iso()


def _reap_ticket_agents(ticket: dict) -> None:
    """Le ticket vient d'être intégré : tuer tout process d'agent encore vivant sur ses
    session-files (le JUMEAU d'un double-spawn continuerait à brûler des tokens)."""
    for agent_id in {r.get("agent_id") for r in ticket.get("runs") or [] if isinstance(r, dict)}:
        if agent_id:
            agent_arret.reap_session_processes(str(agent_fiche.AGENTS_DIR / f"{agent_id}.session.json"))


def _auto(ticket: dict, done_agent: str) -> bool:
    """L'agent du run courant intègre lui-même sa branche (outil Environment)."""
    courant = cycle_des_runs.run_courant(ticket)
    return bool(done_agent and courant and courant.get("agent_id") == done_agent
                and ticket.get("state") in (etats.RUNNING, etats.AWAITING_INPUT))


def _refus_prealable(ticket: dict, done_agent: str) -> dict | None:
    if not ticket.get("worktree") or etat_ticket.integre(ticket):
        return {"ok": False, "code": "rien_a_integrer",
                "error": "rien à intégrer (pas de worktree ou déjà intégré)"}
    if not _auto(ticket, done_agent) and ticket.get("state") in etats.ACTIFS:
        return {"ok": False, "code": "agent_actif", "state": ticket.get("state"),
                "error": "l'agent de travail tourne encore (ou une intégration est en cours)"}
    return None


def _ressortir_la_branche(slug: str, ticket: dict, meta: dict) -> dict | None:
    """C5b : un worktree disparu ne vaut jamais « rien à intégrer » — la branche existe
    toujours. On la re-sort dans un worktree neuf ; None si elle ne porte aucun travail."""
    from . import branch_rescue
    from .provisioning import meta_du_worktree
    worktrees.discard_worktree(meta["repo_root"], ticket["id"])  # purge l'entrée git orpheline
    neuf = branch_rescue.resume_on_branch(meta["repo_root"], ticket["id"], meta["branch"],
                                          meta["base"], worktrees.WORKTREES_DIR)
    if not neuf:
        return None
    neuf = meta_du_worktree({**neuf, **({"in_place": True} if meta.get("in_place") else {})})
    tickets.poser(slug, ticket, worktree=neuf)
    return neuf


def _entrer(slug: str, ticket: dict) -> None:
    """`conflict` (résolu) → `delivered` → `integrating` : deux transitions listées."""
    if ticket.get("state") == etats.CONFLICT:
        ticket.update(ticket_fsm.appliquer(slug, ticket["id"], etats.CONFLICT_CLEARED))
    ticket.update(ticket_fsm.appliquer(slug, ticket["id"], etats.INTEGRATE_STARTED))


#: Issue d'une AUTO-intégration, rejouée en transitions quand le run se termine livré.
AUTO_ISSUES = {etats.INTEGRATED: "integre", etats.CONFLICT_DETECTED: "conflit",
               etats.INTEGRATE_FAILED: "echec"}


def _conclure(slug: str, ticket: dict, auto_agent: str, evenement: str, integration: dict,
              **raison) -> None:
    """Note l'issue dans `ticket.integration` ; hors auto-intégration, applique la transition.
    Une auto-intégration (pendant le run de l'agent) note `auto` : `constats.fin_de_run` la
    rejouera en transitions quand le run sera livré."""
    note = {**(ticket.get("integration") or {}), **integration}
    if auto_agent:
        note["auto"] = {"agent_id": auto_agent, "issue": AUTO_ISSUES[evenement],
                        "raison": raison}
    else:
        note.pop("auto", None)
    tickets.poser(slug, ticket, integration=note)
    if not auto_agent:
        ticket.update(ticket_fsm.appliquer(slug, ticket["id"], evenement, **raison))


def _apres_merge_propre(slug: str, ticket: dict, meta: dict, result: dict, cleanup: bool,
                        auto: str) -> dict[str, Any]:
    cleanup = cleanup and not worktrees.dirty_files(meta)  # B9, C15 : jamais un arbre sale
    if cleanup:
        worktrees.cleanup(meta)
        tickets.poser(slug, ticket, worktree={**meta, "retire_at": _maintenant()})
    rc = result.get("restore_conflict")
    _conclure(slug, ticket, auto, etats.INTEGRATED,
              {"merged_at": _maintenant(), "merge_commit": result.get("merge_commit", ""),
               **({"base_avant": result["base_avant"]} if result.get("base_avant") else {}),
               "conflict_files": [], **({"restore_conflict": rc} if rc else {})}, code="integre")
    _reap_ticket_agents(ticket)
    archiver_les_brouillons_de_fusion(ticket)
    return {"ok": True, "state": ticket.get("state"), **({"restore_conflict": rc} if rc else {})}


def integrate_ticket(slug: str, ticket: dict, done_agent: str = "",
                     cleanup: bool = True) -> dict[str, Any]:
    """Merge le worktree du ticket dans sa branche de base. Le travail non commité est récolté
    JUSTE AVANT. Un conflit est renvoyé tel quel (`conflit`, fichiers en cause), personne n'est
    relancé. `cleanup` : retirer le worktree après un merge propre (jamais s'il reste sale)."""
    refus = _refus_prealable(ticket, done_agent)
    if refus:
        return refus
    meta = ticket["worktree"]
    if not worktrees.dir_exists(meta):
        meta = _ressortir_la_branche(slug, ticket, meta)
        if meta is None:
            return {"ok": False, "code": "rien_a_integrer",
                    "error": "le worktree a disparu et sa branche ne porte aucun travail"}
    bloque = worktrees.blocage_recolte(meta["worktree"])
    if bloque is not None:  # merge inachevé / marqueurs : ni commit ni transition
        return {"ok": False, "code": "conflit_en_cours", "state": ticket.get("state"),
                "error": bloque["message"], "retryable": False, "remede": bloque["message"],
                "files": bloque["fichiers"]}
    auto = done_agent if _auto(ticket, done_agent) else ""
    if not auto:
        _entrer(slug, ticket)
    return executer(slug, ticket, meta, auto, cleanup)


def _sha_base(meta: dict) -> str:
    """Sha courant de la branche de base (vide si illisible) : sert au rollback d'un passage."""
    import subprocess
    repo, base = str(meta.get("repo_root") or ""), str(meta.get("base") or "")
    if not repo or not base:
        return ""
    try:
        out = subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "--quiet", base],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def executer(slug: str, ticket: dict, meta: dict, auto: str = "",
             cleanup: bool = True) -> dict[str, Any]:
    """Le merge lui-même, ticket déjà `integrating` (ou auto-intégration) : récolte, merge sous
    le verrou de la base, puis `closed` | `conflict` | `delivered{merge_echoue}`."""
    recolte = worktrees.harvest(meta, ticket["title"], body=coder_recap_body(ticket))
    delivery.noter_recolte(slug, ticket, recolte)
    base_avant = _sha_base(meta)
    result = worktrees.integrate(meta)
    if result["ok"]:
        if not result.get("merge_commit"):
            result = {**result, "merge_commit": _sha_base(meta)}
        if base_avant and base_avant != result.get("merge_commit"):
            result = {**result, "base_avant": base_avant}
        return _apres_merge_propre(slug, ticket, meta, result, cleanup, auto)
    if result["state"] == "conflict":
        _conclure(slug, ticket, auto, etats.CONFLICT_DETECTED,
                  {"conflict_files": result["files"]}, code="conflit",
                  details={"files": result["files"]})
        return {"ok": False, "code": "conflit", "state": etats.CONFLICT, "files": result["files"]}
    remede = result.get("remede", "") or "corrige la cause indiquée puis relance l'intégration"
    _conclure(slug, ticket, auto, etats.INTEGRATE_FAILED, {"error": result.get("error", "")},
              code=MERGE_ECHOUE, message=str(result.get("error", ""))[:500],
              details={"remede": remede, "retryable": bool(result.get("retryable"))})
    return {"ok": False, "code": "merge_echoue", "state": etats.DELIVERED,
            "error": result.get("error", ""), "retryable": bool(result.get("retryable")),
            "remede": remede, "files": result.get("files") or []}


#: Raison d'un ticket rendu `delivered` après un merge que git a refusé (spec §5.4).
MERGE_ECHOUE = "merge_echoue"


def finalize_ephemeral(slug: str, ticket: dict, done_agent: str = "") -> dict[str, Any]:
    """Clôture d'un ticket ÉPHÉMÈRE (bac à sable de test) : NE MERGE JAMAIS sur la base ; le bac
    à sable (worktree + branche jetable) est fauché aussitôt. Idempotent."""
    if ticket.get("state") in etats.ACTIFS and not _auto(ticket, done_agent):
        return {"ok": False, "code": "agent_actif", "error": "l'agent de travail tourne encore"}
    meta = ticket.get("worktree")
    if isinstance(meta, dict) and meta.get("worktree") and not meta.get("retire_at"):
        worktrees.reap(meta, delete_branch=True)
        tickets.poser(slug, ticket, worktree={**meta, "retire_at": _maintenant()})
    tickets.poser(slug, ticket, ephemeral=True)
    if ticket.get("state") == etats.DELIVERED:
        ticket.update(ticket_fsm.appliquer(slug, ticket["id"], etats.CLOSE, code="ephemere"))
    elif ticket.get("state") not in etats.CLOS:
        ticket.update(ticket_fsm.appliquer(slug, ticket["id"], etats.ABANDON, code="ephemere"))
    return {"ok": True, "state": "ephemeral"}


def conclure_l_auto_integration(slug: str, ticket: dict) -> None:
    """Le run d'un agent qui s'est AUTO-intégré vient de finir livré : son merge (ou son
    conflit) devient les transitions qu'il aurait suivies — `integrate_started` puis
    `integrated` / `conflict`. Un échec git laisse le ticket livré, avec sa raison."""
    integration = dict(ticket.get("integration") or {})
    auto = integration.pop("auto", None)
    if not auto:
        return
    tickets.poser(slug, ticket, integration=integration)
    evenement = {v: k for k, v in AUTO_ISSUES.items()}[auto["issue"]]
    if evenement == etats.INTEGRATE_FAILED:
        ticket_fsm.motiver(slug, ticket["id"], MERGE_ECHOUE,
                           str((auto.get("raison") or {}).get("message") or ""))
        return
    ticket.update(ticket_fsm.appliquer(slug, ticket["id"], etats.INTEGRATE_STARTED, "agent"))
    ticket.update(ticket_fsm.appliquer(slug, ticket["id"], evenement, "agent",
                                       **(auto.get("raison") or {})))


def deja_integre(ticket: dict) -> bool:
    """La branche du ticket est fusionnée : ticket clos par un merge, ou AUTO-intégration
    réussie pendant le run en cours (pas encore conclue en transitions)."""
    auto = (ticket.get("integration") or {}).get("auto") or {}
    return etat_ticket.integre(ticket) or auto.get("issue") == "integre"
