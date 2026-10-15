# [desc] Liste des agents du parc (`list_agents`, cache TTL single-flight) et réconciliation au démarrage. [/desc]
"""Le parc d'agents vu du disque : `list_agents` (cache TTL + cache par mtime, un seul
recalcul à la fois) et `reconcile_dead_agents` au démarrage du serveur."""
from __future__ import annotations

import json
import logging
import threading
import time

from bouzecode.web_v2.services.horodatage import maintenant_iso

from . import agent_fiche
from . import agent_vivacite
from . import agent_etat
from .agent_fiche import Agent


# Un SEUL thread reconstruit la liste à la fois : sans ça, N requêtes concurrentes (le front
# poll toutes les ~1 s) tombant sur un cache expiré relançaient CHACUNE un scan complet de
# ~1000 fichiers → stampede → le serveur passe son temps à recalculer la même liste.
_list_agents_compute_lock = threading.Lock()
# Cache PERSISTANT par fichier, clé = mtime : un agent `finished` est immuable, on ne relit
# donc JAMAIS son JSON après le 1er chargement (seul un `stat` par fichier subsiste).
_agent_file_cache: dict = {}
_LIST_AGENTS_TTL = 3  # seconds


def list_agents() -> list[Agent]:
    """Return all agents, cached for up to _LIST_AGENTS_TTL seconds (thread-safe).
    Single-flight : un cache expiré ne déclenche qu'UN recalcul, les autres threads
    attendent puis réutilisent son résultat (pas de scan disque en rafale)."""
    now = time.time()
    with agent_fiche._list_agents_lock:
        if "expires" in agent_fiche._list_agents_cache and now < agent_fiche._list_agents_cache["expires"]:
            return list(agent_fiche._list_agents_cache["data"])
    with _list_agents_compute_lock:
        # Re-check : un thread concurrent a pu rafraîchir le cache pendant qu'on attendait.
        with agent_fiche._list_agents_lock:
            if "expires" in agent_fiche._list_agents_cache and time.time() < agent_fiche._list_agents_cache["expires"]:
                return list(agent_fiche._list_agents_cache["data"])
        result = _list_agents_uncached()
        with agent_fiche._list_agents_lock:
            agent_fiche._list_agents_cache["data"] = result
            agent_fiche._list_agents_cache["expires"] = time.time() + _LIST_AGENTS_TTL
        return list(result)


def _list_agents_uncached() -> list[Agent]:
    """Read all agent JSONs from disk + refresh status. Un cache par mtime évite de relire
    et re-parser les fichiers inchangés (l'essentiel : des agents `finished` immuables)."""
    agents: list[Agent] = []
    for path in agent_fiche.AGENTS_DIR.glob("*.json"):
        if ".session" in path.stem:  # skip session sidecars (.session/.pending/.deferred .json)
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        key = str(path)
        cached = _agent_file_cache.get(key)
        if cached and cached[0] == mtime:
            agent = cached[1]
        else:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                logging.getLogger(__name__).warning(
                    "Skipping corrupt agent file %s: %s", path, exc
                )
                continue
            agent = agent_fiche._agent_from_dict(data)
            if agent is None:
                continue
            _agent_file_cache[key] = (mtime, agent)
        agent_etat.refresh_agent_status(agent)  # bon marché si terminé (returncode connu → early return)
        agents.append(agent)
    agents.sort(key=lambda a: a.started_at, reverse=True)
    return agents


def reconcile_dead_agents() -> list[str]:
    """Démarrage web_v2 : stampe finished_at/returncode sur les agents au pid MORT mais non
    clôturés (crash/kill/redémarrage serveur). Sans ça, ces « zombies » se font réconcilier
    LAZY dans le chemin chaud `list_agents` — 99 `_save` sous contention du poller (retry
    WinError) tenant le compute-lock → tout /api/projects+/tree wedge (timeout 180 s observé).
    Réconcilie UNIQUEMENT (pas d'auto-retry/respawn : web_v2 pilote la reprise via son wake).
    Mono-thread au boot (aucun poller/requête concurrent) → pas de course fichier. Renvoie la
    LISTE des agent_ids stampés rc=-1 à CE boot (agents crashés à signaler dans le rapport des
    interrompus). Un agent légitimement `awaiting_input` garde son statut IPC (returncode 0,
    IPC intact) donc reste affiché « en attente » et n'est PAS dans la liste."""
    crashed_ids: list[str] = []
    for path in agent_fiche.AGENTS_DIR.glob("*.json"):
        if ".session" in path.stem:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        agent = agent_fiche._agent_from_dict(data)
        if agent is None or agent.returncode is not None:
            continue
        # Même preuve que le chemin chaud : un pid RECYCLÉ (fréquent après un redémarrage de
        # la machine) ou un zombie ne gardent plus un agent mort « en cours » pour toujours.
        raison = agent_vivacite.processus_absent(agent)
        if not raison:
            continue
        if raison == agent_vivacite.ZOMBIE:
            raison = "processus zombie (terminé)"
        agent.fin_constatee = f"{raison} — constaté au démarrage du serveur"
        agent.finished_at = maintenant_iso("auto")
        ipc_status = agent_etat.get_ipc_state(agent).get("status")
        # Agent en ATTENTE utilisateur (awaiting_input / awaiting_plan_validation) :
        # jamais crashé, rc=0 (comportement conservé). Pour tout le reste on délègue
        # à _returncode_from_session — MÊME source de vérité que le chemin CHAUD
        # (refresh_agent_status) : le close_reason disque fait foi. Sans ça, un agent
        # clos GRACIEUSEMENT sur `final_answer_deferred` (dont l'IPC n'est pas resté
        # `finished` pendant le drain deferred) était faussement stampé rc=-1 → listé
        # « crashed » dans le rapport des interrompus → faux bandeau « Cet agent a été
        # interrompu. Reprendre ? ». _returncode_from_session le classe rc=0 (gracieux).
        if ipc_status in ("awaiting_input", "awaiting_plan_validation"):
            agent.returncode = 0
        else:
            agent.returncode = agent_etat._returncode_from_session(agent)
        agent_fiche._save(agent)
        if agent.returncode == -1:
            crashed_ids.append(agent.agent_id)
    return crashed_ids
