# [desc] Récolte du travail d'un agent qui a LIVRÉ : commit sur sa branche, ou signalement du péril. [/desc]
"""Le chaînon manquant entre « l'agent a fini » et « son travail existe quelque part ».

`worktrees.harvest` est le SEUL geste qui commite le travail non commité d'un agent
sur sa branche `agent/<ticket>`. Il n'était appelé que depuis trois endroits, tous
CONDITIONNELS : la transition CRASH (`workflow._act_report_crash`), le merge demandé
à la main (`integration.integrate_ticket`) et le spawn manuel d'un validateur. Le
chemin NOMINAL — l'agent a fini proprement, son run est `completed` — n'en avait
aucun.

Ce n'est pas un oubli d'origine : le correctif aca2f03c en avait posé un sur le
chemin de succès de l'époque, le TEST-GATE. Le retrait de la chaîne automatique
travail→validation→merge a supprimé le test-gate, et ce harvest avec lui ; seul
celui du crash a survécu. D'où le cas vécu du 28/07 : deux codeurs `finished`, rc=0,
`close_reason=final_answer`, run `completed` — et deux branches VIDES, tout leur
travail encore non commité dans le worktree, à un `POST /archive` de la destruction
(`reaper.reap_archived` → `git worktree remove --force`).

Deux garanties, dans cet ordre :
  1. RÉCOLTER  — une livraison commite le travail sur la branche de l'agent ;
  2. SIGNALER  — si la récolte n'aboutit pas (index git verrouillé, dépôt en vrac),
     le ticket porte `uncommitted` = les fichiers en péril, `derive_status` renvoie
     « livraison non commitée » et `liveness.classify_ticket` renvoie `stalled`. Un
     agent livré dont le worktree est sale n'est JAMAIS affiché comme réussi.

Câblé comme une TRANSITION déclarative de `workflow` (state `work_done`, garde
`delivery_unharvested`), donc rejoué par tous les chemins qui rejouent la chaîne :
hook `/completed`, watchdog, route liste. Aucune nouvelle boucle."""
from __future__ import annotations

from . import tickets as tickets_svc, worktrees

# États de worktree où une récolte a encore un sens : le bac à sable existe et n'a pas
# déjà été mergé/nettoyé/parké. `conflict` est exclu — un résolveur y travaille.
HARVESTABLE_STATES = frozenset({"provisioned", "committed"})

_MAX_FLAGGED_FILES = 20  # le drapeau nomme les fichiers en péril, il n'archive pas un diff


def work_run(ticket: dict) -> dict | None:
    """Le run de TRAVAIL le plus récent du ticket (c'est lui qui produit du code)."""
    return next((r for r in ticket.get("runs") or []
                 if isinstance(r, dict) and r.get("kind") == "work"), None)


def needs_delivery_harvest(ticket: dict) -> bool:
    """GARDE PURE : ce ticket a-t-il une livraison à récolter ? (aucune I/O)

    Vrai quand un run de travail a fini PROPREMENT (`completed`, donc ni crash ni
    abandon), que son bac à sable existe encore, et qu'on ne l'a pas déjà récolté.
    `harvested` est posé par `harvest_delivery` et persisté sur le run : un nouveau
    run (`add_run`) repart sans le drapeau, donc un agent relancé est re-récolté."""
    meta = ticket.get("worktree")
    if not (isinstance(meta, dict) and meta.get("worktree") and meta.get("branch")):
        return False  # ticket `shared` (travaille dans le dépôt principal) : rien à récolter
    if meta.get("state") not in HARVESTABLE_STATES:
        return False
    run = work_run(ticket)
    return bool(run and run.get("completed") and not run.get("harvested"))


def delivery_at_risk(ticket: dict) -> bool:
    """PUR : le travail livré de ce ticket peut-il encore être perdu en silence ?

    Deux cas : la récolte n'a pas encore eu lieu, ou elle a eu lieu et a laissé le
    worktree sale. C'est ce prédicat qui interdit à `liveness.classify_ticket` de
    présenter une telle livraison comme une attente de décision ordinaire."""
    return bool(ticket.get("uncommitted")) or needs_delivery_harvest(ticket)


def harvest_delivery(slug: str, ticket: dict, done_agent: str = "") -> None:
    """ACTION : commite le travail livré sur la branche de l'agent, puis dit la vérité.

    Le drapeau `uncommitted` est posé quand il reste du non-commité APRÈS la récolte,
    et RETIRÉ dès qu'une récolte réussit — il ne colle donc pas à un ticket réparé.
    Idempotent via `run['harvested']` : rejouer la chaîne ne recommite rien.

    `done_agent` fait partie du contrat des actions de `workflow.ACTIONS` ; il n'est
    pas utilisé ici (la récolte porte sur le worktree, pas sur un agent en particulier)."""
    meta = ticket.get("worktree")
    run = work_run(ticket)
    if not (isinstance(meta, dict) and run):
        return
    harvested = worktrees.harvest(meta, ticket.get("title", ""))
    run["harvested"] = True
    meta["delivered_head"] = harvested.get("head", "")
    remaining = harvested.get("dirty") or []
    if remaining:
        ticket["uncommitted"] = remaining[:_MAX_FLAGGED_FILES]
    else:
        ticket.pop("uncommitted", None)
    tickets_svc.update_ticket(slug, ticket)


def reopen_for_new_work(slug: str, ticket_id: str) -> None:
    """Un agent RELANCÉ sur le même run (follow-up : `continue_agent` / réponse à une
    question) va produire du travail NEUF. Sa livraison précédente ne doit plus valoir
    quitus de récolte, sinon ce travail neuf ne serait jamais commité — le trou d'origine,
    rouvert un tour plus tard. Une vraie relance (`tickets.add_run`) repart d'un run neuf,
    donc sans drapeau : il n'y a que le follow-up à rouvrir explicitement. No-op sinon."""
    if not (slug and ticket_id):
        return
    ticket = tickets_svc.get_ticket(slug, ticket_id)
    run = work_run(ticket) if ticket else None
    if not (run and run.get("harvested")):
        return
    run.pop("harvested", None)
    tickets_svc.update_ticket(slug, ticket)


def harvest_before_reclaiming(ticket: dict) -> None:
    """Filet de dernier recours, appelé JUSTE AVANT de détruire un worktree (archivage,
    suppression de projet). `reap_archived` fait `git worktree remove --force` : sans
    cette récolte, archiver un ticket effaçait pour de bon le travail non commité d'un
    agent — précisément le geste qu'on demande à l'utilisateur pour ranger son board.

    Ne persiste RIEN (l'appelant écrit le ticket juste après) et ne juge rien : un
    worktree déjà propre rend `harvest` no-op (`status --porcelain` vide)."""
    meta = ticket.get("worktree")
    if not (isinstance(meta, dict) and meta.get("worktree") and meta.get("branch")):
        return
    if meta.get("state") in ("integrated", "cleaned"):
        return  # déjà mergé puis nettoyé : plus rien à sauver
    worktrees.harvest(meta, ticket.get("title", ""))
