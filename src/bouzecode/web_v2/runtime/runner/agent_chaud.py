# [desc] Reprise CHAUDE d'un process vivant : boîte de messages, answer.txt, états warm / mid-turn. [/desc]
"""Parler à un process encore vivant : est-il chaud, en pause question, en plein tour ? Dépôt
du message dans sa boîte ou de la réponse dans answer.txt, transition du ticket."""
from __future__ import annotations

import logging
import uuid

from .. import ipc
from . import agent_fiche
from . import agent_vivacite
from . import agent_processus
from . import agent_etat
from .agent_fiche import Agent


def _signaler_au_ticket(agent: Agent, quoi: str) -> None:
    """Ce qu'on vient de faire à l'agent devient une transition de son ticket (`message` :
    reprise chaude → running ; `reponse` : question répondue ; `arret` : tué → stopped)."""
    slug, ticket_id = getattr(agent, "ticket_slug", ""), getattr(agent, "ticket_id", "")
    if not (slug and ticket_id):
        return
    from ...services.work import runs_ticket  # local : `runs_ticket` tire les services
    runs_ticket.signaler(slug, ticket_id, agent.agent_id, quoi)


def _adopt_live_session_process(agent: Agent) -> bool:
    """La fiche porte un pid PÉRIMÉ alors qu'un process vit pour cette session ? On adopte
    le pid réel (et on le persiste). True si une adoption a eu lieu.

    Deux gardes jugeaient la même question — « ce process est-il vivant ? » — avec deux
    mesures différentes : la garde CHAUDE par `psutil.pid_exists(agent.pid)` (la FICHE),
    la garde FROIDE de `_respawn` par cmdline (`_session_process_running`). Dès que la
    fiche se désynchronise du process réel (warm pool relancé hors fiche, pid recyclé),
    la chaude dit « mort » et la froide dit « vivant » : le message tombait dans un TROU
    NOIR (ni push, ni respawn → None → 409 `not_delivered` que le front du Bureau retente
    toutes les 4 s à l'infini). On resynchronise la fiche sur la MESURE QUI FAIT FOI, la
    cmdline : le process est là, on lui parle."""
    if agent.pid and not agent_vivacite.processus_absent(agent):
        return False
    live = [proc for proc in agent_processus._procs_for_session(agent.session_path) if proc.is_running()]
    if not live:
        return False
    logging.getLogger(__name__).warning(
        "pid de fiche périmé (%s) : adoption du process vivant %s pour %s",
        agent.pid, live[0].pid, agent.session_path)
    agent.pid = live[0].pid
    agent.pid_create_time = agent_vivacite._instant_de_creation(agent.pid)
    agent_fiche._save(agent)
    return True


def _is_warm(agent: Agent) -> bool:
    """True ssi le process de l'agent est ENCORE VIVANT et reprenable à chaud.

    Warm = pid vivant + IPC status 'idle' OU 'finished' : le process bouzecode
    tourne toujours dans son run_agent_event_loop (keep_warm). 'idle' = il poll
    déjà followup.txt. 'finished' = FENÊTRE transitoire post-FinalAnswer : le tour
    a stampé l'IPC FINISHED (via _fire_completion) et le on_completion/test-gate
    peut bloquer jusqu'à ~1900s AVANT que la warm loop ne réécrive 'idle'. Pendant
    cette fenêtre le pid est vivant : refuser la reprise chaude condamnait le
    follow-up à un TROU NOIR — ni chaud (status≠idle) ni froid (_respawn refuse un
    pid vivant via sa garde anti-double-spawn) → clic « Envoyer » sans effet ni
    erreur. Pousser followup.txt marche : la warm loop le pop dès on_completion fini.
    On peut donc reprendre IN-PROCESS (push followup.txt) sans cold-start respawn."""
    if not agent.pid or not agent.ipc_dir:
        return False
    if agent_vivacite.processus_absent(agent):
        return False
    return agent_etat.get_ipc_state(agent).get("status") in ("idle", "finished")


is_warm = _is_warm  # alias public (fleet._node badge 'chaud')


def _deposer(paths: "ipc.IPCPaths", prompt: str, message_id: str = "") -> None:
    """Le prompt rejoint la FILE du process : sa boîte, où rien n'écrase rien. Un process de
    l'ancien code (pas de drapeau `boite` dans son état) ne sonde que followup.txt : il le
    reçoit là, comme avant (un 2e message arrivé avant lecture y remplace le 1er)."""
    if ipc.lit_sa_boite(paths):
        ipc.deposer_message(paths, message_id or uuid.uuid4().hex[:10], prompt)
    else:
        ipc.ecrire_followup_herite(paths, prompt)


def _push_followup(agent: Agent, prompt: str, message_id: str = "") -> Agent:
    """Reprise CHAUDE : dépose le prompt dans la boîte du process vivant.

    Le run_agent_event_loop idle du process relève sa boîte et exécute le tour DANS LE
    MÊME PROCESS (zéro cold-start). Deux messages déposés avant qu'il ne relève le premier
    forment un seul tour, dans l'ordre (avant : followup.txt écrasé, le 1er perdu).
    `message_id` nomme le dépôt pour que la file des messages suive sa lecture. On reset
    finished_at/returncode pour que web_v2 cesse de le voir 'terminé'."""
    paths = ipc.from_dir(agent.ipc_dir)
    # Un nouveau tour demandé par l'utilisateur ANNULE toute interruption pendante :
    # sinon un cancel.flag laissé par un /interrupt précédent (le process est resté vivant/idle,
    # pas de cold-respawn qui purge l'IPC) est consommé dès le 1er point d'interruption du tour
    # relancé → l'agent « s'interromp en permanence malgré les messages et les relances ».
    ipc.consume_cancel(paths)
    _deposer(paths, prompt, message_id)
    agent.finished_at = ""
    agent.returncode = None
    agent_fiche._save(agent)
    _signaler_au_ticket(agent, "message")
    return agent


def _joignable_en_tour(agent: Agent) -> bool:
    """Process vivant qui joue son tour ET relève sa boîte : un message lui parvient à sa
    prochaine frontière de tour. Sans ça, un réveil arrivé juste après qu'il a relevé une
    relance tentait un respawn, refusé (pid vivant) : message perdu."""
    if not agent.pid or not agent.ipc_dir or agent_vivacite.processus_absent(agent):
        return False
    paths = ipc.from_dir(agent.ipc_dir)
    return ipc.read_state(paths).get("status") == ipc.STATUS_RUNNING and ipc.lit_sa_boite(paths)


def _is_warm_awaiting(agent: Agent) -> bool:
    """True ssi le process est vivant ET en pause question (awaiting_input/plan)."""
    if not agent.pid or not agent.ipc_dir:
        return False
    if agent_vivacite.processus_absent(agent):
        return False
    return agent_etat.get_ipc_state(agent).get("status") in ("awaiting_input", "awaiting_plan_validation")


def is_mid_turn(agent: Agent) -> bool:
    """L'agent joue-t-il ENCORE un tour ? (par opposition à : il a cédé)

    `is_running` — pid vivant — répond à une AUTRE question, et c'est celle-là que
    `/interrupt` posait pour décider d'escalader vers le kill. Or un agent chaud est CONÇU
    pour survivre à son tour : `ipc.run_agent_event_loop` écrit `idle` puis sonde
    `followup.txt`, process résident. Son pid existait donc toujours après une annulation
    PARFAITEMENT réussie → l'escalade le tuait à TOUS LES COUPS, et le message suivant
    repartait en cold-respawn (process neuf, imports, contexte réémis) là où un simple
    `_push_followup` sur le process vivant aurait suffi. C'est ce qui rendait une
    interruption web lente là où le Ctrl+C du TUI est immédiat.

    Céder, c'est ne plus tenir le tour, de quelque façon que ce soit : process parti,
    retombé oisif (`_is_warm`), ou mis en pause sur une question (`_is_warm_awaiting`) —
    les trois états dans lesquels on peut de nouveau lui parler."""
    if not agent_vivacite.is_running(agent):
        return False
    return not (_is_warm(agent) or _is_warm_awaiting(agent))


def _push_answer(agent: Agent, answer: str) -> Agent:
    """Reprise CHAUDE d'une pause question : pousse la réponse dans answer.txt."""
    paths = ipc.from_dir(agent.ipc_dir)
    # Symétrique de _push_followup : une reprise chaude d'AskUserQuestion doit purger un
    # cancel.flag pendant, sinon le tour relancé s'auto-interrompt aussitôt (boucle).
    ipc.consume_cancel(paths)
    paths.answer.write_text(answer, encoding="utf-8")
    agent.finished_at = ""
    agent.returncode = None
    agent_fiche._save(agent)
    _signaler_au_ticket(agent, "reponse")
    return agent
