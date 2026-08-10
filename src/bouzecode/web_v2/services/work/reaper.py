# [desc] Faucheur (GC) des bacs à sable de tickets TERMINAUX : purge worktree/branche selon l'issue. [/desc]
"""GC du cycle de vie des tickets : plus aucun nettoyage manuel de worktrees/branches.

On ne PERD le worktree (working tree + venv, coûteux en disque) que dans DEUX cas : le travail
est réellement FINI (mergé/éphémère), ou le ticket est ARCHIVÉ explicitement par le user. Un
ticket crashed/failed reste REPRENABLE — on conserve TOUT (worktree + branche) :

  * integrated / done  → travail mergé          → retirer worktree + SUPPRIMER la branche.
  * éphémère (test)     → travail jetable        → retirer worktree + branche.
  * failed / crashed    → REPRENABLE             → TOUT CONSERVER (worktree ET branche).
  * archivage explicite → décision du user       → retirer worktree, GARDER la branche (`reap_archived`).

POURQUOI ne plus faucher crashed/failed : un « crash » n'est souvent qu'une mort de process
TRANSITOIRE (restart serveur, OOM, kill). Retirer son worktree condamnait un agent parfaitement
resumable et faisait croire à une perte de travail (cf. cause racine worktree readme_sync).

Le ticket est marqué `reaped=true` (persistant) → reap rejoué = no-op (idempotence). On ne
touche JAMAIS un ticket non-terminal ni un run encore actif (busy). Prédicats purs
(`terminal_outcome`, `should_reap`, `should_delete_branch`) testables sans git ; `reap_ticket`
et `reap_archived` sont les seuls à toucher le disque. Branché sur le tick du watchdog
(`wake.tick`), le rejeu de chaîne (`wake._run_chain`) et la route d'archivage de ticket."""
from __future__ import annotations

from . import delivery, integration, tickets, workflow, worktrees


# ── Prédicats purs (sur l'état persisté du ticket, sans git) ──────────────────

def terminal_outcome(ticket: dict) -> str | None:
    """Issue terminale du ticket : 'integrated' | 'needs_attention' | 'crashed' | 'failed',
    ou None si le ticket peut encore avancer. Pur. Ordre : crash signalé d'abord, puis merge
    réussi (worktree integrated/cleaned), puis merge demandé mais bloqué, puis verdict KO.

    Il n'y a plus de plafond de passes : la boucle de rework automatique a été retirée, donc
    un verdict KO d'un validateur lancé à la demande est directement une issue — c'est le
    manager qui décide de relancer le codeur ou non."""
    if ticket.get("crashed"):
        return "crashed"
    meta = ticket.get("worktree")
    if isinstance(meta, dict) and meta.get("state") in ("integrated", "cleaned"):
        return "integrated"
    # Merge demandé mais bloqué : terminal ICI pour réveiller le parent (avec l'info), sans
    # jamais faucher le worktree (cf. reap_ticket) — la branche reste réintégrable.
    if isinstance(meta, dict) and meta.get("state") == "needs_attention":
        return "needs_attention"
    if integration.latest_verdict(ticket) == "KO":
        return "failed"
    return None


def is_terminal(ticket: dict) -> bool:
    """Vrai quand le ticket a une issue terminale (rien de plus à jouer). Pur."""
    return terminal_outcome(ticket) is not None


def should_delete_branch(outcome: str, ephemeral: bool) -> bool:
    """Politique de branche (pure) : on supprime la branche `agent/<ticket>` quand le
    travail est mergé (integrated) ou jetable (éphémère). Pour failed/crashed on la GARDE
    pour le post-mortem — seul le worktree est retiré."""
    return ephemeral or outcome == "integrated"


def should_reap(ticket: dict) -> bool:
    """Faut-il faucher ce ticket ? Vrai s'il est terminal et pas déjà fauché. Pur : rend
    `reap_ticket` idempotent (marqué `reaped` → plus jamais re-tenté)."""
    if ticket.get("reaped"):
        return False
    return is_terminal(ticket)


# ── Action (seule à toucher le disque : git worktree/branch) ──────────────────

def is_resume_blocked(ticket: dict) -> str | None:
    """Message actionnable si l'agent d'un ticket NE DOIT PLUS être relancé (resume interdit),
    None sinon. Un ticket est verrouillé dès qu'il est mergé/reapé : son worktree a été nettoyé
    (integration.integrate_ticket → worktree.state='cleaned'/'integrated' puis reaper pose
    reaped=True et supprime l'arbre). Relancer l'agent le ferait renaître dans un dossier fantôme
    (AGENTS.md seul) → 'file not found'. Pur : lit uniquement le dict ticket."""
    if ticket.get("reaped") or terminal_outcome(ticket) == "integrated":
        return ("ticket déjà mergé/reapé — crée un ticket de suivi "
                "(le worktree a été nettoyé)")
    return None


def reap_ticket(slug: str, ticket: dict) -> bool:
    """GC automatique : fauche un ticket dont le travail est RÉELLEMENT FINI — mergé (integrated)
    ou jetable (éphémère). Retire alors le worktree + (selon politique) la branche, puis marque
    `reaped=true`. Un ticket crashed / failed / needs_attention reste REPRENABLE : son worktree
    ET sa branche sont CONSERVÉS (seul l'archivage explicite les réclame, cf. `reap_archived`).
    No-op si non-terminal, déjà fauché, ou run encore actif (busy). Idempotent (reap 2× = no-op)."""
    if not should_reap(ticket):
        return False
    if workflow.derive_state(ticket) == "busy":
        return False  # un run tourne encore : on ne fauche jamais sous les pieds d'un agent
    outcome = terminal_outcome(ticket)
    ephemeral = bool(ticket.get("ephemeral"))
    # On ne réclame le worktree QUE quand le travail est fini pour de bon. crashed/failed/
    # needs_attention → reprenables : TOUT est conservé. Un crash n'est souvent qu'une mort de
    # process transitoire (restart serveur) ; le faucher condamnait un agent resumable.
    if outcome != "integrated" and not ephemeral:
        return False
    meta = ticket.get("worktree")
    if isinstance(meta, dict) and meta.get("worktree"):
        worktrees.reap(meta, delete_branch=should_delete_branch(outcome, ephemeral))
    ticket["reaped"] = True
    tickets.update_ticket(slug, ticket)
    return True


def reap_archived(slug: str, ticket: dict) -> bool:
    """Archivage EXPLICITE (décision du user) : réclame le worktree (disque) mais CONSERVE la
    branche `agent/<ticket>` — les commits restent récupérables. C'est, avec le merge, la seule
    voie qui retire le worktree d'un ticket crashed/failed gardé par le GC. No-op si un run tourne
    encore (jamais faucher sous les pieds d'un agent) ou si le ticket n'a pas de worktree isolé.
    Renvoie True si un worktree a été retiré."""
    if workflow.derive_state(ticket) == "busy":
        return False
    meta = ticket.get("worktree")
    if not (isinstance(meta, dict) and meta.get("worktree")):
        return False
    # DERNIER RECOURS AVANT DESTRUCTION : `reap` fait `git worktree remove --force`, qui
    # emporte tout ce qui n'est pas commité. La branche est « préservée » — mais elle ne
    # préserve que ce qui y a été COMMITÉ. Sans cette récolte, archiver un ticket effaçait
    # le travail d'un agent qui avait pourtant livré (cf. services/work/delivery.py).
    delivery.harvest_before_reclaiming(ticket)
    worktrees.reap(meta, delete_branch=False)  # worktree retiré, branche préservée (récupérable)
    ticket["reaped"] = True
    tickets.update_ticket(slug, ticket)
    return True


def reap_project(slug: str) -> list[str]:
    """Suppression d'un projet : réclame le worktree de CHACUN de ses tickets (branche gardée,
    commits récupérables), en sautant tout run encore actif (busy, via reap_archived). Ferme la
    boucle des worktrees orphelins : sans ça, retirer un projet laissait ses worktrees sur disque
    sans ticket accessible. Renvoie les ids de tickets dont le worktree a été retiré."""
    reaped = []
    for ticket in tickets.list_tickets(slug, include_archived=True):
        if isinstance(ticket, dict) and reap_archived(slug, ticket):
            reaped.append(ticket.get("id"))
    return reaped
