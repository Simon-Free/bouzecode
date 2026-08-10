# [desc] Parc d'agents tous projets confondus, groupé par manager (parent). [/desc]
"""Vue cross-projet : chaque agent web avec son projet, son état et son parent.

Le groupement par parent (agent manager, "dispatcher:manual", ou "") est laissé
au front. `suspect_dead` repère les vrais morts anormaux : fini sans aucun tour
ET avec un returncode non nul (ou absent). Un agent fini avec rc=0 est un succès
propre — il n'est JAMAIS suspect, même à 0 tour (ex. validateur terminé OK)."""
from __future__ import annotations

import logging
from datetime import datetime
from types import SimpleNamespace
from typing import Any

# run_kind → rôle lisible. Fallback = run_kind.capitalize() pour tout kind inconnu.
_ROLE_BY_RUN_KIND = {
    "work": "Agent",
    "validate": "Validateur",
}


def _short_label(agent) -> str:
    """Libellé court d'un noeud de sidebar/onglet.

    Une conversation user (run_kind "work") est identifiée par SON SUJET : on prend
    la 1re ligne non vide du prompt (tronquée). Afficher le rôle ("Agent") ou le profil
    y était inutile — tous les onglets s'appelaient "Agent", ou pire portaient le nom du
    profil projet (ex. "demo-dashboard-refacto"), donnant l'illusion que l'agent n'était
    pas en mode "default". Les agents STRUCTURELS (validate/merge/dispatch…) n'ont pas de
    sujet user parlant : on garde leur rôle lisible. Aucune heure cuite dans le titre
    (le front la dérive de `started_at`). Prompt complet dispo via `title_full` (tooltip)."""
    if (agent.run_kind or "work") == "work":
        for line in (agent.prompt or "").splitlines():
            line = line.strip()
            if line:
                return line[:60]
        return "Agent"
    return _ROLE_BY_RUN_KIND.get(agent.run_kind) or (agent.run_kind or "Agent").capitalize()

from concurrent.futures import ThreadPoolExecutor
from datetime import timezone

from ...runtime import runner, warmpool
from ..sessions import category, purge, store, visibility
from . import (_tree_page, activity, fleet_cache, fleet_live, launch_phase, liveness, projects,
               repos, tickets, worktrees)

_log = logging.getLogger(__name__)

# Façade. Ce module CONSTRUIT UNE VUE ; terminer des process est un geste de nature opposée,
# qui vit dans `warm_pool` — les garder ensemble avait déjà coûté cher (le ménage tournait DANS
# le calcul de l'arbre, donc une lecture tuait des process). Ré-exportés pour que les appelants
# gardent `fleet.sweep_warm_pool()` et `fleet.WARM_POOL_MAX`.
from .warm_pool import WARM_POOL_MAX, sweep_warm_pool  # noqa: F401,E402 — ré-export façade

# La politique de cache de l'arbre (servir d'abord, recalculer en fond, un verrou par clé) vit
# dans `fleet_cache` — cf. son en-tête pour les mesures qui l'ont motivée.

# États où l'agent attend une réponse de l'utilisateur : ils remontent en tête de la
# liste ET de la pagination (la page 1 doit contenir ce sur quoi il faut agir).
_AWAITING = ("awaiting_input", "awaiting_plan_validation")



def _node(agent, meta: dict, project_list: list[dict]) -> dict[str, Any]:
    project = projects.project_for_cwd(agent.cwd, project_list)
    status = meta.get("status") or store.agent_status(agent)
    state = status.get("state", "")
    # Phase de démarrage (cf. store.demarrage_phase) : ce qui se passe pendant les secondes
    # où « en cours » ne dit rien à personne. Vide dès qu'un état ordinaire suffit.
    phase = status.get("phase", "")
    turns = meta.get("turn_count", 0)
    key = repos.repo_key(agent.cwd) if agent.cwd else None
    awaiting = state in ("awaiting_input", "awaiting_plan_validation")
    # Verdict lisible (chips validateur) et état DÉRIVÉ DE PREUVES : MÊMES helpers partagés
    # que /api/interrupted, le panneau de conversation et la liste de tickets (croisent pid
    # vivant + close_reason + final_answer + verdict). Aucune règle recopiée ici.
    _verdict = liveness.run_verdict(agent, state)
    _liveness_v = liveness.classify_agent(agent, state)
    return {
        "agent_id": agent.agent_id,
        "key": f"agent/{agent.agent_id}",
        # Process encore VIVANT et idle (reprise CHAUDE possible : followup in-process).
        "warm": runner.is_warm(agent),
        # Récence réelle pour l'éviction LRU du warm-pool (last save/finished/start).
        "last_activity": max(agent.started_at or "", agent.finished_at or "",
                             meta.get("saved_at", "")),
        # ticket_id du ticket porté par ce run. Sert (a) à dédupliquer le node
        # synthétique 'launching' dès que le vrai agent apparaît, (b) au front à
        # rebrancher l'onglet launching/<ticket> sur agent/<id> après spawn.
        "ticket_id": getattr(agent, "ticket_id", "") or "",
        "session_path": agent.session_path or "",
        "parent": agent.parent or "",
        "title": _short_label(agent),
        "title_full": (agent.prompt or "").strip(),
        "project_slug": project["slug"] if project else "",
        "project_name": project["name"] if project else "",
        "repo": repos.repo_name(agent.cwd, key) if agent.cwd else "",
        "branch": repos.branch_of(agent.cwd) if agent.cwd else "",
        "isolated": str(worktrees.WORKTREES_DIR) in (agent.cwd or ""),
        "model": agent.model,
        "state": state,
        "phase": phase,
        # Surface the pending question so the dispatcher sees the agent is blocked
        # ON THEM (web_v1 did this; web_v2 dropped it). Answer via the ticket
        # comments endpoint (send=true → runner.resume_pending_agent).
        "question": status.get("question", "") if awaiting else "",
        "options": (status.get("options") or []) if awaiting else [],
        # `allow_freetext` n'a de sens QUE face à une question : il dit si la réponse peut
        # être libre ou doit être une des options. Servi à `True` sur les ~960 nœuds sans
        # question, il ressemblait à un signal et n'en portait aucun — au point de faire
        # croire que la question était exposée alors qu'elle ne l'était pas. Absent = rien
        # à répondre ; présent = la contrainte réelle de CETTE question.
        **({"allow_freetext": bool(status.get("allow_freetext", True))} if awaiting else {}),
        "returncode": agent.returncode,
        "started_at": agent.started_at,
        # Dernière interaction (saved_at du JSON session ≈ dernière sauvegarde/activité),
        # propagée depuis store.list_agent_sessions. Sert de clé de tri (récence réelle,
        # pas date de création). Vide si la session n'a pas encore été sauvegardée.
        "saved_at": meta.get("saved_at", ""),
        "turn_count": turns,
        "has_recap": bool(meta.get("has_recap")),  # → pastille « Récap » dans la sidebar
        # Vrai mort anormal : fini SANS aucun tour ET rc non nul/absent. rc=0 = succès
        # propre → jamais suspect (corrige e5b6c622 : validateur finished+rc0 flaggé à tort).
        "suspect_dead": state == "finished" and turns == 0
        and agent.returncode != 0,
        # Verdict lisible pour les chips validateur (calculé plus haut, réutilisé par
        # le classifieur de liveness). Vide sinon (le front n'affiche rien).
        "verdict": _verdict,
        # Nature STRUCTURELLE du run (work/validate/merge/dispatch/manual), dérivée du
        # run_kind stocké à la création de l'agent. Bien plus fiable que deviner via le
        # titre. Le front s'en sert pour NE JAMAIS promouvoir un validate/merge en racine
        # (orphelin dont le parent codeur a disparu de l'arbre).
        "kind": agent.run_kind or "",
        # NATURE de la conversation (user/meta/subagent/test), MÊME classifieur que
        # /api/sessions (services/sessions/category.py) : une conv doit avoir la même
        # catégorie dans les deux surfaces. Le front s'en sert pour filtrer/étiqueter
        # la sidebar — il tournait jusqu'ici sur une heuristique de repli (titre + cwd
        # isolé) qui classait tout dispatch manuel en « méta ».
        "category": category.classify_agent(agent),
        # État DÉRIVÉ DE PREUVES (running/delivered/crashed), MÊME classifieur partagé
        # que /api/interrupted et la liste tickets : croise pid vivant + close_reason +
        # final_answer + verdict, au lieu de deviner via returncode seul. Ticket vide {}
        # (l'arbre montre des agents isolés, hors chaîne d'intégration → pas de stalled).
        "liveness": _liveness_v,
        # Planté/interrompu (crash/restart sans FinalAnswer). Traité côté front comme
        # un « input à await » (décider du sort de l'agent) : remonte en section
        # needinput avec le formatage awaiting. Même classifieur que /api/interrupted.
        "interrupted": _liveness_v == "crashed",
        # CE QUE L'AGENT FAIT (outil en cours, âge du dernier battement, silence anormal) —
        # servi pour les seuls agents VIVANTS, cf. `activity.describe`. Sans ces champs, un
        # node « en cours » ne portait aucune information sur son propre travail.
        **activity.describe(status, meta),
    }


def agent_tree(offset: int = 0, limit: int | None = None) -> dict[str, Any]:
    """Vue tree, page de racines — voir _agent_tree_uncached. JAMAIS d'attente sur un recalcul
    dès lors qu'une version existe.

    `limit` = nombre de RACINES servies à partir d'`offset`, chacune avec tous ses
    sous-agents. Sans `limit`, l'arbre COMPLET est renvoyé (rétro-compatible : aucun
    appelant existant n'a besoin de connaître la pagination). Une entrée de cache par
    couple (offset, limit) — le front rejoue les mêmes couples à chaque poll.

    SERVIR D'ABORD, RECALCULER ENSUITE. Une entrée périmée est rendue TELLE QUELLE et le
    recalcul part dans un thread de fond : le poll suivant récupérera la version fraîche. Seul
    le PREMIER appel d'une clé (aucune donnée à servir) attend le calcul. Avant, un poll sur
    deux payait 2,2 s (page de 15 racines) à 9,45 s (arbre complet) EN LIGNE, puisque le TTL de
    10 s tombe sous la cadence de poll de 8 s du front.

    Le prix de ce choix est une fraîcheur bornée à `_TREE_TTL` + la durée d'un recalcul, au lieu
    du seul TTL. C'est le bon échange ici : l'arbre est une VUE D'OBSERVATION (aucune décision
    ne s'y prend), et une seconde de retard sur un statut est sans conséquence là où une
    interface qui se fige plusieurs secondes est le défaut rapporté. Les chemins où la fraîcheur
    est contractuelle (répondre à un agent, intégrer, clore) ne lisent pas ce cache.

    LA PHASE, ELLE, N'ATTEND PAS. Ce qu'un agent change plusieurs fois par tour (sa phase de
    démarrage, ce qu'il est en train de faire) est relu À CHAQUE LECTURE par-dessus la page
    mémorisée — cf. `fleet_live`. Le badge de la sidebar accusait sinon 6,56 s de retard sur
    une information que le serveur détenait déjà (mesuré le 2026-08-04 sur un vrai lancement).
    Le prix est le recensement des agents VIVANTS : 22-38 ms, contre 160-235 ms pour recalculer
    la page — c'est ce rapport qui a écarté la baisse du TTL."""
    page = fleet_cache.cached(
        ("agent_tree", offset, limit), lambda: _agent_tree_uncached(offset, limit)
    )
    return fleet_live.overlay(page)


def clear_tree_cache() -> None:
    """Oublie l'arbre mémorisé : le prochain appel rend la photo de MAINTENANT.

    Seam explicite pour les tests, qui doivent pouvoir observer un statut qui vient de changer
    sans attendre la fin du TTL."""
    fleet_cache.clear()


def _awaiting_rank_and_recency(agent, meta: dict) -> tuple[int, str]:
    """Clé de tri d'une racine : 0 si elle attend une réponse user, puis sa récence."""
    status = meta.get("status") or store.agent_status(agent)
    rank = 0 if status.get("state", "") in _AWAITING else 1
    return rank, (meta.get("saved_at") or agent.started_at or "")


def _agent_tree_uncached(offset: int = 0, limit: int | None = None) -> dict[str, Any]:
    """Les agents web, à plat, avec parent/projet/état (le front groupe).

    Léger : utilise store.list_agent_sessions() (PAS list_sessions) pour éviter
    le parcours des sessions daily (glob JSON coûteux, jeté ici). Tri : les
    conversations en attente d'input user (awaiting_*) remontent EN HAUT, puis
    par dernière interaction décroissante (saved_at, fallback started_at).

    Avec `limit`, seules `limit` racines à partir d'`offset` (et leurs descendants)
    sont CONSTRUITES : les infos git, qui dominent le coût, ne sont donc payées que
    sur les nodes servis — c'est ce qui borne le fetch que le front subissait sur
    l'arbre entier. `total_roots` renvoie le nombre total de racines pour que le
    front sache quand arrêter de scroller."""
    project_list = projects.list_projects()
    meta_by_key = {a["key"]: a for a in store.list_agent_sessions()}
    # Agents archivés/purgés : hors du tree (réversible via restore) — SAUF s'ils sont
    # encore vivants. Un agent qui tourne, ou qui attend une réponse de l'utilisateur,
    # reste visible quoi qu'il arrive : la vivacité prime sur le drapeau, sinon un simple
    # rangement suffit à faire disparaître l'agent à qui l'on doit une réponse (et il ne
    # repart jamais, faute d'être trouvable). Cf. sessions/visibility.py.
    deleted = purge.load_deleted()
    agents = [
        agent for agent in runner.list_agents()
        if not visibility.hidden_by_archive(agent, deleted)
    ]
    roots = _tree_page.roots_in_display_order(
        agents,
        lambda agent: _awaiting_rank_and_recency(
            agent, meta_by_key.get(f"agent/{agent.agent_id}", {})
        ),
    )
    total_roots = len(roots)
    if limit is not None:
        agents = _tree_page.with_descendants(roots[offset:offset + limit], agents)
    # PRÉ-WARM PARALLÈLE des infos git par cwd. _node() appelle repos.repo_key +
    # repos.branch_of pour CHAQUE agent : à froid (caches vides ou TTL branche expiré)
    # c'est 1-2 subprocess git PAR agent. En séquentiel, ~1000 agents × ~100-200 ms =
    # 2 min+ de sidebar bloquée (bug rapporté). git est I/O-bound → on warm les cwd
    # UNIQUES en parallèle AVANT la boucle _node ; ensuite _node lit tout en cache (0
    # subprocess). repo_key/branch_of sont thread-safe (verrou interne) et idempotents.
    unique_cwds = {agent.cwd for agent in agents if agent.cwd}
    if unique_cwds:
        with ThreadPoolExecutor(max_workers=min(32, len(unique_cwds))) as pool:
            for cwd in unique_cwds:
                pool.submit(repos.repo_key, cwd)
                pool.submit(repos.branch_of, cwd)
    nodes = [
        _node(agent, meta_by_key.get(f"agent/{agent.agent_id}", {}), project_list)
        for agent in agents
    ]
    # Un manager hérite de la pastille « Récap » si ≥1 de ses enfants a un récap propre :
    # sa vue /recap concatène alors les récaps des sous-agents (lot consolidé).
    recap_parents = {n["parent"] for n in nodes if n["has_recap"] and n["parent"]}
    if recap_parents:
        for n in nodes:
            if n["agent_id"] in recap_parents or n["key"] in recap_parents:
                n["has_recap"] = True
    # STATUT EFFECTIF HIÉRARCHIQUE : un ancêtre est « en cours » tant qu'au moins un de ses
    # descendants (transitivement) tourne. `liveness` posé par _node est SELF-ONLY (pid/ipc/
    # close_reason de CET agent), donc un ancêtre terminé dont un descendant tourne encore
    # restait faussement « delivered/crashed ». On remonte ici chaque chaîne parent depuis les
    # agents « running » et on force les ancêtres à « running ». Le `parent` peut être stocké
    # en id nu OU en key (« agent/<id> »), d'où le double index — même robustesse que recap.
    #
    # « Tourne » inclut « attend une réponse » (liveness.ALIVE) : un descendant bloqué sur
    # une question n'est pas fini, donc son manager ne l'est pas non plus. Un ancêtre qui
    # attend LUI-MÊME une réponse garde son propre `awaiting_input` : c'est l'information
    # la plus actionnable de la chaîne, un « running » hérité l'effacerait.
    by_id = {n["agent_id"]: n for n in nodes}
    by_key = {n["key"]: n for n in nodes}
    for node in nodes:
        if node["liveness"] not in liveness.ALIVE:
            continue
        seen: set[str] = set()
        parent_ref = node["parent"]
        while parent_ref and parent_ref not in seen:
            seen.add(parent_ref)
            ancestor = by_id.get(parent_ref) or by_key.get(parent_ref)
            if ancestor is None:
                break
            if ancestor["liveness"] not in liveness.ALIVE:
                ancestor["liveness"] = "running"
            parent_ref = ancestor["parent"]
    # Tickets EN COURS DE LANCEMENT (worktree+venv+spawn en fond) : aucun agent
    # n'existe ENCORE pour eux → invisibles de list_agents(). On les injecte comme
    # nodes synthétiques (state="provisioning") pour qu'ils apparaissent IMMÉDIATEMENT
    # en sidebar + onglet, avec la phase en cours (provisioning_worktree / _venv /
    # spawning). Dédup : si un agent porte déjà ce ticket_id (spawn effectué entre le
    # set_launching et ce calcul), on ne double pas — le vrai node agent prime.
    have_ticket = {n["ticket_id"] for n in nodes if n.get("ticket_id")}
    project_by_slug = {p["slug"]: p for p in project_list}
    for slug, ticket in tickets.launching_tickets():
        project = project_by_slug.get(slug)
        # Slug HORS du registre des projets ouverts : le node serait inouvrable (aucune page
        # projet derrière). Ces slugs fantômes existent (drapeaux `launching` figés par un
        # serveur tué en plein provisioning, fixtures de test) et n'ont rien à faire dans
        # l'arbre live. Le vrai node agent prime toujours sur le node synthétique.
        if project is None or ticket["id"] in have_ticket:
            continue
        nodes.append({
            "agent_id": ticket["id"],
            "key": f"launching/{ticket['id']}",
            "ticket_id": ticket["id"],
            "session_path": "",
            "parent": ticket.get("parent") or "",
            "title": ticket.get("title") or "Nouvelle conversation",
            "title_full": (ticket.get("prompt") or "").strip(),
            "project_slug": slug,
            "project_name": project["name"],
            "repo": "",
            "branch": "",
            "isolated": True,  # un launching provisionne toujours un worktree
            "model": ticket.get("model") or "",
            "state": "provisioning",
            # Phase COURANTE du lancement + son libellé + son heure (`launch_phase`). C'est le
            # champ qui n'était lu que par ce node et que PERSONNE n'écrivait : toutes les
            # étapes — worktree (~50 s par essai sur ce poste, jusqu'à 3 essais), `uv sync`
            # (jusqu'à 600 s), spawn — se présentaient sous un unique « provisioning » muet.
            **launch_phase.phase_view(ticket),
            # Pas d'`allow_freetext` : un ticket en cours de provisioning n'a rien demandé.
            "question": "", "options": [],
            "returncode": None,
            "started_at": ticket.get("created_at") or "",
            "saved_at": "",
            "turn_count": 0,
            "has_recap": False,
            "suspect_dead": False,
            "verdict": "",
            "kind": "work",
            # Nature déduite des mêmes champs que pour un agent (prompt + parent) :
            # un ticket en cours de lancement doit être étiqueté comme la conversation
            # qu'il deviendra, sinon il change de catégorie au spawn.
            "category": category.classify_agent(SimpleNamespace(
                agent_id=ticket["id"],
                prompt=ticket.get("prompt") or ticket.get("title") or "",
                parent=ticket.get("parent") or "",
            )),
            "liveness": "running",
        })
    # Recent first BY LAST INTERACTION (saved_at ≈ last save/activity, fallback
    # started_at for never-saved sessions), then a STABLE pass that floats awaiting_*
    # conversations to the top while preserving the recent-first order within each group.
    nodes.sort(key=lambda n: n.get("saved_at") or n["started_at"], reverse=True)
    nodes.sort(key=lambda n: 0 if n["state"] in _AWAITING else 1)
    # `total_roots` ne compte QUE les racines agents : les nodes de tickets en cours de
    # lancement sont servis sur TOUTES les pages (ils sont peu nombreux, sans coût git,
    # et doivent apparaître immédiatement) — ils ne consomment donc pas de rang de page.
    return {"nodes": nodes, "total_roots": total_roots}
