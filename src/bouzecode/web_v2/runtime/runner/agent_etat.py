# [desc] État IPC d'un agent et constat de sa fin (returncode, finished_at) par `refresh_agent_status`. [/desc]
"""Lecture de l'état d'un agent : état IPC (mis en cache par mtime), code de retour déduit de
la session, constat d'une fin dont le process est parti. Ne tue ni ne lance rien."""
from __future__ import annotations

import json

import psutil

from bouzecode.web_v2.services.horodatage import maintenant_iso

from .. import ipc
from ... import close_reasons
from . import agent_fiche
from . import agent_vivacite
from . import agent_respawn
from .agent_fiche import Agent


# Le classement vit dans web_v2/close_reasons.py — une table unique, lue aussi par
# `wake` et `liveness`. Ici la question est « une livraison est-elle PROUVÉE ? » (rc 0) :
# seul FinalAnswer livre, une clôture sur prose (`text_no_tools`) n'est pas une livraison.
_DELIVERY_CLOSE_REASONS = close_reasons.DELIVERY_CLOSE_REASONS


def _ipc_says_graceful(agent: Agent) -> bool:
    """Repli IPC : quand le session JSON ne porte PAS de close_reason gracieux
    (bug racine historique : la session restait close_reason='' à la clôture
    gracieuse), consulter l'état IPC <agent>.ipc/state.json. Gracieux ssi
    status=finished ET close_reason gracieux. status=running ou close_reason
    absent → PAS gracieux (on ne présume rien sans preuve)."""
    ipc_dir = getattr(agent, "ipc_dir", "") or ""
    if not ipc_dir:
        return False
    state = ipc.read_state(ipc.from_dir(ipc_dir))
    if state.get("status") != ipc.STATUS_FINISHED:
        return False
    return state.get("close_reason", "") in _DELIVERY_CLOSE_REASONS


def _returncode_from_session(agent: Agent) -> int:
    """Derive a return code from the disk session's close_reason when the real
    rc is lost (pid gone, Popen not retained). A graceful close (FinalAnswer)
    → 0 ; anything else (api_error, or death without a clean close, or an
    unreadable/absent session) → -1 so web_v2 reports a crash.

    REPLI IPC : si la session ne porte pas de close_reason gracieux (session
    vide/illisible = symptôme du bug racine), on consulte l'IPC en dernier
    ressort — une session vide + IPC=finished:final_answer est une clôture
    GRACIEUSE, pas un crash."""
    try:
        with open(agent.session_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return 0 if _ipc_says_graceful(agent) else -1
    close_reason = data.get("close_reason", "")
    if close_reason in _DELIVERY_CLOSE_REASONS:
        return 0
    return 0 if _ipc_says_graceful(agent) else -1


def _suivre_le_deplacement_en_vol(agent: Agent) -> None:
    """Un agent VIVANT qui s'est déplacé lui-même (`Environment(action='worktree')`) le signale
    dans `env.json` : sa fiche l'adopte TOUT DE SUITE, pas seulement au prochain respawn.

    Sans ça, la fiche d'un enfant parti en partagé puis isolé en vol gardait pour cwd le dépôt
    principal pendant tout son travail (essai du 2026-09-24) : l'arbre le montrait au mauvais
    endroit et le garde-fou anti-collision le comptait comme écrivain de l'arbre partagé."""
    avant = (agent.cwd, agent.worktree_root, agent.base_venv)
    agent_respawn._adopter_le_signal_d_environnement(agent)
    if (agent.cwd, agent.worktree_root, agent.base_venv) != avant:
        agent_fiche._save(agent)


def _raison_du_code(returncode: int) -> str:
    if returncode < 0:
        import signal
        try:
            return f"processus tué par {signal.Signals(-returncode).name}"
        except ValueError:
            return f"processus tué par le signal {-returncode}"
    return f"processus terminé (code {returncode})"


def _ramasser_le_zombie(agent: Agent) -> int | None:
    """Code de sortie d'un zombie dont on est le parent ; None sinon (autre parent)."""
    try:
        return psutil.Process(agent.pid).wait(timeout=0.1)
    except (psutil.Error, OSError):
        return None


def _constater_la_fin(agent: Agent, raison: str) -> None:
    """Stampe la fin d'un agent dont le process n'est plus là, avec une raison LISIBLE.

    Ne tue rien, ne relance rien : il n'y a plus de process, on ÉCRIT ce qui est arrivé.
    Le vrai code de retour n'est connu que pour un zombie qu'on ramasse soi-même ; sinon la
    session disque fait foi (clôture non gracieuse → -1, affiché comme un crash)."""
    code = _ramasser_le_zombie(agent) if raison == agent_vivacite.ZOMBIE else None
    if raison == agent_vivacite.ZOMBIE:
        raison = _raison_du_code(code) if code is not None else "processus zombie (terminé)"
    agent.finished_at = maintenant_iso("auto")
    agent.returncode = code if code is not None else _returncode_from_session(agent)
    agent.fin_constatee = raison
    agent_fiche._save(agent)


def refresh_agent_status(agent: Agent) -> Agent:
    """Constate la fin d'un agent dont le process est parti (returncode + finished_at).

    Ne TUE jamais rien (spec ticketing B1, constat C2) : cette fonction est appelée par des
    LECTURES (`store.agent_status`, `list_agents`). Un process vivant dont l'IPC dit
    `finished` est dans la fenêtre post-FinalAnswer que `_is_warm` juge reprenable à chaud ;
    le terminer ici cassait la reprise (ticket resté `awaiting_decision` alors que l'agent
    repartait). Sa fin relève du seul pool chaud (`warm_pool.sweep_warm_pool`, au tick du
    watchdog), qui l'évince selon sa politique (LRU / TTL) comme tout process chaud.

    Ne LANCE rien non plus : les vérifications différées d'une clôture `final_answer_deferred`
    sont drainées par le watchdog (`tick_annexes.drainer_les_verifications_differees`), jamais
    par une lecture — elles exécutent des commandes et peuvent relancer l'agent."""
    if agent.returncode is not None:
        return agent
    _suivre_le_deplacement_en_vol(agent)
    raison = agent_vivacite.processus_absent(agent)
    if raison:
        _constater_la_fin(agent, raison)
    return agent


_ipc_state_cache: dict = {}  # ipc_dir -> (mtime, state) : évite de relire le fichier IPC de
# CHAQUE agent à chaque construction du tree/compteurs (961 lectures/requête). Un agent fini a
# un IPC stable → jamais relu ; un agent actif change de mtime → relu.


def get_ipc_state(agent: Agent) -> dict:
    if not agent.ipc_dir:
        return {"status": "unknown"}
    paths = ipc.from_dir(agent.ipc_dir)
    try:
        mtime = paths.state.stat().st_mtime
    except OSError:
        return ipc.read_state(paths)  # fichier absent → défaut géré par read_state
    cached = _ipc_state_cache.get(agent.ipc_dir)
    if cached and cached[0] == mtime:
        return cached[1]
    state = ipc.read_state(paths)
    _ipc_state_cache[agent.ipc_dir] = (mtime, state)
    return state
