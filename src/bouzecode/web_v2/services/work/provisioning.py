# [desc] Provisionnement du bac à sable d'un ticket : worktree, venv, ré-isolation, re-logement d'un respawn. [/desc]
"""Tout ce qui PRÉPARE le terrain d'un agent, sorti de `dispatch.py` (qui décidait ET creusait).

Ces étapes sont les LONGUES du lancement, et c'est pourquoi elles vivent ensemble : sur ce
poste un `git worktree add` coûte ~50 s par essai (antivirus d'entreprise) et peut être rejoué
3 fois, un `uv sync --all-extras` court jusqu'à 600 s, et la ré-isolation d'un ticket abandonné
enchaîne récolte, retrait de worktree et re-sortie de branche. Chacune pose sa phase via
`launch_phase` pour que l'attente soit lisible au lieu d'être un « provisioning » muet.

Ré-exporté par `dispatch` (façade) : les appelants existants continuent d'écrire
`dispatch.reisolate` / `dispatch.rehome_agent_cwd`.
"""
from __future__ import annotations

import os
from typing import Any

from ...runtime import env_signal
from ...runtime.runner import agent_fiche
from . import branch_rescue, delivery, launch_phase, projects, repos, tickets, worktrees
from .isolation import SHARED, WORKTREE

_RESUMED_COMMENT = (
    "♻️ Relance SUR la branche existante `{branch}` : elle portait du travail commité, "
    "il est conservé et le nouvel agent repart de là. (La relance recréait la branche "
    "depuis la base, ce qui effaçait ces commits.)"
)
_NO_ISOLATION_COMMENT = (
    "⚠️ Isolation NON obtenue : le provisionnement du worktree a échoué ({error}). L'agent "
    "travaille dans le dépôt principal, partagé — sa livraison n'est sur aucune branche "
    "d'agent. Relancer le ticket re-tente le provisionnement."
)
_RESCUED_COMMENT = (
    "🛟 La branche `{branch}` a été supprimée pour re-provisionner ce ticket, mais elle "
    "portait des commits absents de la base : ils sont conservés sous le tag `{tag}` "
    "(`git log {tag}` pour les revoir, `git cherry-pick` / `git branch X {tag}` pour les "
    "reprendre)."
)


def _path_of(slug: str, project_list: list[dict[str, Any]]) -> str | None:
    return next((p["path"] for p in project_list if p.get("slug") == slug), None)


def reisolate(slug: str, ticket: dict, project_path: str) -> str:
    """Re-provisionne un worktree pour un ticket ABANDONNÉ (crashé/reapé) en réutilisant son id.
    Renvoie le cwd (le worktree, ou le dépôt principal si non-git).

    AUCUN TRAVAIL N'EST DÉTRUIT ICI. La version précédente purgeait worktree ET branche
    (`git branch -D agent/<id>`) avant de re-créer la branche depuis la base : tout ce que
    l'agent précédent avait commité disparaissait, et le reflog de la branche avec lui. Ordre
    désormais :
      1. récolter ce qui traîne encore dans le worktree (il va être supprimé) ;
      2. retirer le worktree SEUL, la branche reste ;
      3. si la branche porte du travail, la re-sortir telle quelle → la relance CONTINUE ;
      4. sinon seulement, la supprimer — et `discard_stale` la tague d'abord si besoin."""
    root = repos.repo_root(project_path)
    if not root:
        return _provision_worktree(slug, ticket, project_path,
                                   isolation=ticket.get("isolation") or WORKTREE)
    meta = ticket.get("worktree") if isinstance(ticket.get("worktree"), dict) else {}
    branch = meta.get("branch") or branch_rescue.agent_branch(ticket["id"])
    base = meta.get("base") or worktrees.current_branch(root)
    # Chirurgie git (récolte, retrait du worktree, re-sortie de branche) : plusieurs dizaines de
    # secondes pendant lesquelles un `/continue` semblait ne rien faire. `rehome_agent_cwd`
    # passe ici avant tout respawn.
    launch_phase.set_phase(slug, ticket, launch_phase.REISOLATING, detail=f"branche {branch}")
    if not delivery.harvest_before_reclaiming(slug, ticket) and meta.get("worktree"):
        return meta["worktree"]  # merge inachevé : on reprend DANS ce worktree pour le finir
    worktrees.discard_worktree(root, ticket["id"])
    resumed = branch_rescue.resume_on_branch(root, ticket["id"], branch, base,
                                             worktrees.WORKTREES_DIR)
    if resumed:
        tickets.poser(slug, ticket, worktree=meta_du_worktree(resumed))
        tickets.add_comment(slug, ticket, _RESUMED_COMMENT.format(branch=branch), True)
        return resumed["worktree"]
    dropped = worktrees.discard_stale(root, ticket["id"], base_branch=base)
    if dropped.get("rescue_tag"):
        tickets.add_comment(slug, ticket, _RESCUED_COMMENT.format(
            branch=branch, tag=dropped["rescue_tag"]), True)
    return _provision_worktree(slug, ticket, project_path,
                               isolation=ticket.get("isolation") or WORKTREE)


def _is_live_worktree(cwd: str, ticket: dict | None) -> bool:
    """True quand `cwd` est un worktree git VIVANT (donc réutilisable tel quel). Un simple
    os.path.isdir NE suffit PAS : après un merge+reap le dossier peut subsister VIDE (readme_sync
    y repeint un AGENTS.md solitaire) alors que le code a disparu → l'agent renaît sans source.
    On exige donc : dossier présent ET un `.git` (fichier `gitdir:` dans un worktree, ou dossier
    dans un dépôt principal) ET un ticket qui n'est ni intégré ni à worktree retiré."""
    if not (cwd and os.path.isdir(cwd)):
        return False
    if not os.path.exists(os.path.join(cwd, ".git")):
        return False
    from . import etat_ticket
    retire = bool(((ticket or {}).get("worktree") or {}).get("retire_at"))
    return not (retire or etat_ticket.integre(ticket or {}))


def meta_du_worktree(provision: dict) -> dict:
    """Ce qu'un ticket garde d'un provisionnement : le chemin, la branche, la base… — jamais
    un `state` (l'état du ticket est `ticket.state`) ni le drapeau `ok` de l'appel."""
    return {k: v for k, v in provision.items() if k not in ("ok", "state")}


def _same_dir(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _deplacer(agent, cwd: str) -> str:
    agent.cwd = cwd
    agent_fiche._save(agent)
    return cwd


def _suivre_le_signal(agent) -> None:
    """L'agent a pu se déplacer LUI-MÊME en vol (`Environment(action='worktree')`, un chdir
    invisible d'ici) et l'a signalé dans son dossier IPC. Consulté AVANT le test de vivacité :
    le cas réel est un cwd encore valide mais PÉRIMÉ (l'arbre partagé d'où il est parti)."""
    signalled = env_signal.read(getattr(agent, "ipc_dir", "") or "").get("cwd") or ""
    if signalled and os.path.isdir(signalled) and not _same_dir(signalled, agent.cwd):
        _deplacer(agent, signalled)


def _reisoler(agent, slug: str, ticket: dict | None) -> str:
    """Un worktree NEUF depuis la base vivante (la reprise garde l'isolation ET voit le travail
    mergé). "" si le ticket n'est pas adossé à un dépôt git."""
    project_path = _path_of(slug, projects.list_projects()) if slug else None
    if ticket is None or not project_path or not repos.repo_root(project_path):
        return ""
    new_cwd = reisolate(slug, ticket, project_path)
    if not (new_cwd and os.path.isdir(new_cwd)):
        return ""
    # Ce chemin ne passe PAS par `add_run` : il retire lui-même la phase qu'il a posée.
    launch_phase.drop_phase(slug, ticket)
    return _deplacer(agent, new_cwd)


def rehome_agent_cwd(agent) -> str:
    """Give a respawn a valid cwd when the agent's worktree was cleaned away (ticket merged →
    worktree removed). Without this, `/continue` (and every resume) calls Popen(cwd=<gone>) →
    NotADirectoryError → HTTP 500.

    Re-provisions a FRESH worktree off the live base branch when the agent belongs to a
    git-backed ticket; else falls back to the ticket's recorded repo_root. No-op — returns the
    current cwd — when it still exists. Mutates and persists agent.cwd."""
    slug = getattr(agent, "ticket_slug", "") or ""
    ticket_id = getattr(agent, "ticket_id", "") or ""
    ticket = tickets.get_ticket(slug, ticket_id) if (slug and ticket_id) else None
    _suivre_le_signal(agent)
    if _is_live_worktree(agent.cwd, ticket):
        return agent.cwd
    nouveau = _reisoler(agent, slug, ticket)
    if nouveau:
        return nouveau
    repo_root = ((ticket or {}).get("worktree") or {}).get("repo_root") or ""
    if repo_root and os.path.isdir(repo_root):
        _deplacer(agent, repo_root)
    return agent.cwd


def _provision_worktree(slug: str, ticket: dict, project_path: str, resume_branch: str = "",
                        isolation: str = WORKTREE, work_branch: str = "") -> str:
    """Provisionne un worktree pour la tâche et le rattache au ticket ; le venv n'est
    provisionné QUE pour `isolation == 'worktree+venv'` (un `uv sync` par agent, c'est ce
    qui fait qu'un lancement prend 30 s — le worktree git seul est quasi gratuit).
    Renvoie le cwd à utiliser (le worktree si OK, sinon le path projet).
    resume_branch : base du worktree (point de départ) ; défaut = branche VIVE du dépôt.
    work_branch : branche EXISTANTE à sortir telle quelle (l'agent commite dessus).

    Le repli sur `project_path` quand le provisioning échoue est acceptable pour une branche
    NEUVE (l'agent travaille dans le dépôt principal, rien n'est perdu) mais INTERDIT quand
    une branche précise a été demandée : livrer ailleurs que là où on l'attend est justement
    le défaut qu'on corrige. Dans ce cas on lève — `_launch_bg` logge et pose le motif en
    commentaire sur le ticket."""
    root = repos.repo_root(project_path)
    if not root:
        if work_branch:
            raise RuntimeError(f"`work_branch='{work_branch}'` demandé mais {project_path} "
                               f"n'est pas un dépôt git — aucun agent lancé")
        return project_path  # pas un dépôt git → pas d'isolation possible
    base = resume_branch or worktrees.current_branch(root)
    launch_phase.set_phase(slug, ticket, launch_phase.PROVISIONING_WORKTREE,
                           detail=f"depuis {work_branch or base}")
    meta = worktrees.provision(
        root, ticket["id"], base_branch=base, with_venv=False, work_branch=work_branch,
        # Un essai raté est RENDU VISIBLE pendant que le suivant tourne (jusqu'à 3 essais de
        # ~50 s sur ce poste) : sans ça l'utilisateur ne distinguait pas un provisionnement
        # lent d'un serveur bloqué.
        on_attempt=lambda attempt, total, error: launch_phase.set_phase(
            slug, ticket, launch_phase.PROVISIONING_WORKTREE,
            detail=launch_phase.attempt_detail(attempt, total, error)),
    )
    if not meta.get("ok"):
        if work_branch:
            raise RuntimeError(f"worktree sur la branche demandée '{work_branch}' impossible : "
                               f"{meta.get('error') or 'échec du provisioning'}")
        # Repli sur le dépôt principal : acceptable pour une branche NEUVE, mais JAMAIS
        # silencieux. L'isolation DEMANDÉE n'a pas été obtenue et l'agent va écrire dans
        # l'arbre partagé — le ticket doit le dire, sinon la dégradation ne se lit nulle part.
        tickets.add_comment(slug, ticket, _NO_ISOLATION_COMMENT.format(
            error=meta.get("error") or "échec du provisioning"), True)
        return project_path
    meta = meta_du_worktree(meta)
    tickets.poser(slug, ticket, worktree=meta)
    if isolation == "worktree+venv":
        # `uv sync --all-extras` court jusqu'à 600 s en fond : la phase le DIT, et son issue est
        # rapportée sur le ticket au lieu d'être perdue (un venv en échec laisse l'agent dans un
        # worktree sans dépendances — le défaut le plus coûteux à diagnostiquer après coup).
        # Le `worktree` est écrit avant le lancement du thread : celui-ci écrit la phase via
        # `_mutate` (ligne fraîche), il ne court donc contre aucune écriture.
        launch_phase.set_phase(slug, ticket, launch_phase.SYNCING_VENV)
        worktrees.setup_venv_async(
            meta["worktree"], meta["repo_root"],
            on_result=lambda issue: _report_venv_issue(slug, ticket, issue),
        )
    return meta["worktree"]


_VENV_FAILED_COMMENT = (
    "⚠️ `uv sync --all-extras` a échoué dans le worktree : l'agent travaille SANS ses "
    "dépendances (imports et tests casseront). Relancer le ticket re-tente le provisionnement."
)


def _report_venv_issue(slug: str, ticket: dict, issue: str) -> None:
    """Rend l'issue du `uv sync` de fond SUR le ticket : phase finale, et commentaire si échec.

    `VENV_SKIPPED` (projet non Python) ne mérite ni phase ni commentaire : ce n'est pas un
    événement, juste l'absence d'un besoin. Un ticket dont le run a déjà démarré ne se voit pas
    reposer de phase — `phase_view` n'est lu que pour les tickets en cours de lancement, et
    `add_run` l'a déjà nettoyée : on ne rouvre donc rien, on ne fait que consigner."""
    if issue == worktrees.VENV_SKIPPED:
        return
    if issue == worktrees.VENV_FAILED:
        tickets.add_comment(slug, ticket, _VENV_FAILED_COMMENT, True)
