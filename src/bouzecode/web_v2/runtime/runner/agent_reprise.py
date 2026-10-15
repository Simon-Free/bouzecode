# [desc] Continuer un agent (`continue_agent`), répondre à sa question, drainer ses vérifications différées. [/desc]
"""Reprises d'un agent existant : message (`continue_agent`), réponse à une question
(`resume_pending_agent`), échec d'une vérification différée. Chaud si possible, sinon respawn."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from .. import deferred as web_deferred
from .. import ipc
from . import agent_respawn
from . import agent_chaud
from .agent_fiche import Agent


def _run_deferred_check(command: str, cwd: str, timeout: int):
    """Même enveloppe shell que l'outil Bash (PowerShell sous Windows, jamais cmd.exe) :
    vit dans `deferred.lancer_une`, partagée avec le TUI."""
    return web_deferred.lancer_une(command, cwd, timeout)


def _maybe_drain_deferred(agent: Agent) -> Agent:
    """After a deferred FinalAnswer the subprocess exits leaving a
    `<session>.deferred.json`. Run each queued check sequentially; all green
    finalizes the close, any failure respawns the agent to fix it.

    Le verdict est CONSIGNÉ dans la session avant toute suite (vert comme rouge) : la
    réponse livrée disait « vérification non faite », elle dit désormais ce qu'il en est.
    Avant, un drain vert ne laissait de trace que dans le stdout de l'agent."""
    deferred = web_deferred.load(agent.session_path)
    if deferred is None:
        return agent
    checks = deferred.get("checks") or []
    with Path(agent.stdout_path).open("ab") as stdout_file:
        def _journal(texte: str) -> None:
            stdout_file.write(texte.encode("utf-8"))
            stdout_file.flush()

        _journal("\n\n--- Running deferred checks ---\n")
        verdict = web_deferred.executer(checks, agent.cwd, lancer=_run_deferred_check,
                                        journal=_journal)
        if verdict["statut"] == "vert":
            _journal("--- All deferred checks passed ---\n")
    echec = verdict.get("echec")
    if echec is None:
        web_deferred.consigner(agent.session_path, verdict)
        web_deferred.delete(agent.session_path)
        return agent
    web_deferred.consigner(agent.session_path, verdict,
                           apres_echec="L'agent est relancé pour corriger.")
    if "timeout" in echec:
        error_log = f"Command timed out after {echec['timeout']}s: {echec['command']}"
    else:
        error_log = (
            f"Command failed (exit {echec['code']}): {echec['command']}\n"
            f"{echec['stdout']}\n{echec['stderr']}"
        )
    return resume_deferred_agent(agent, error_log)


def resume_deferred_agent(agent: Agent, error_log: str, model: str = "") -> Agent:
    """Respawn an agent after a deferred check failed, so it can fix and re-emit."""
    agent.auto_retry_count = 0
    return agent_respawn._respawn(
        agent,
        extra_args=["--resume-deferred", error_log],
        banner="\n\n--- Reprise apres echec d un check differe ---\n\n",
        model=model,
    )


def _session_has_persisted_turn(session_path: str) -> bool:
    """True ssi la session JSON existe et contient au moins un tour persisté.

    Tolère l'absence de fichier, un fichier vide ou un JSON invalide → False. Sert à
    distinguer un « reprendre » sur un agent qui n'a jamais persisté de tour (crash très
    précoce, reboot forcé) — où il faut REJOUER le prompt d'origine du ticket — d'un
    continue normal sur une session vivante — où le texte donné doit être transmis."""
    try:
        with open(session_path, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except (OSError, FileNotFoundError):
        return False
    if not raw.strip():
        return False
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return False
    return bool(data.get("messages"))


# Prompt de reprise injecté quand « Reprendre » relance une session AVEC tours mais sans
# nouveau texte (POST {text:""}). Un positionnel vide tuerait le CLI (-p + prompt vide →
# cli.py sys.exit(1)). Ce prompt non vide passe le guard ET relance un vrai tour de reprise.
RESUME_PROMPT = "Reprends la tâche interrompue là où elle s'est arrêtée."


def continue_agent(agent: Agent, prompt: str, model: str = "",
                   message_id: str = "") -> "Agent | None":
    """Respawn a finished agent as the same session (same ID, logs, IPC).

    Renvoie l'agent respawné, ou None si le respawn a été ignoré (garde anti-double-spawn :
    un process est encore vivant pour cette session). Les appelants qui enregistrent un run
    (continue_coder) DOIVENT ne le faire QUE si le respawn a réellement eu lieu.

    Cas « reprendre » (bouton UI, prompt vide OU session jamais persistée) : si la session
    n'a AUCUN tour persisté (agent crashé avant d'écrire quoi que ce soit, p.ex. reboot
    forcé), on IGNORE `prompt` et on rejoue le prompt d'origine du ticket (`agent.prompt`) —
    sinon l'agent est relancé avec un texte vide/parasite et « ne reprend rien »."""
    agent.auto_retry_count = 0
    # Reprise CHAUDE : si le process est encore vivant (idle), on dépose le prompt
    # dans sa boîte et le tour est exécuté IN-PROCESS — pas de cold-start respawn.
    # (skip si un model override est demandé : il faut alors un nouveau process.)
    # Si le pid de la fiche est périmé, on adopte le process réel de la session AVANT de
    # conclure « pas chaud » : sinon `_respawn` refusera (garde cmdline) et le message
    # serait perdu (cf. `_adopt_live_session_process`).
    if not model and not agent_chaud._is_warm(agent):
        agent_chaud._adopt_live_session_process(agent)
    if not model and agent_chaud._is_warm(agent):
        return agent_chaud._push_followup(agent, prompt, message_id)
    # En plein tour : déposé dans sa boîte, lu à sa prochaine frontière de tour. Ni
    # consume_cancel (une interruption demandée tient) ni reset : il n'a pas fini.
    if not model and agent_chaud._joignable_en_tour(agent):
        ipc.deposer_message(ipc.from_dir(agent.ipc_dir), message_id or uuid.uuid4().hex[:10],
                            prompt)
        return agent
    # Reprise FROIDE : process mort → respawn. Si la session n'a AUCUN tour persisté
    # (crash très précoce / reboot forcé), on rejoue le prompt d'origine du ticket.
    if _session_has_persisted_turn(agent.session_path):
        # Le bouton « Reprendre » POST {text:""} → prompt vide. Sur une session AVEC tours,
        # passer "" au CLI (`-p ... --resume-from <s> ""`) faisait argparse→prompt=[""]→
        # initial=""→ cli.py `if print_mode and not initial: sys.exit(1)` : le process
        # mourait AUSSITÔT sans jouer de tour → « Reprendre ne relance rien ». On substitue
        # un prompt de reprise non vide qui passe le guard ET relance un vrai tour.
        effective = prompt or RESUME_PROMPT
    else:
        effective = agent.prompt
    respawne = agent_respawn._respawn(
        agent,
        extra_args=[effective],
        banner=f"\n\n--- Session continued ---\n\n\u00bb {effective}\n\n",
        model=model,
    )
    #  Reprise FROIDE (agent arr\u00eat\u00e9, process mort) : comme la chaude, elle ram\u00e8ne le ticket \u00e0
    #  `running`. Sans \u00e7a, \u00ab Continuer \u00bb un agent arr\u00eat\u00e9 le faisait travailler sous un ticket
    #  rest\u00e9 `stopped` (t\u00e2che du Bureau \u00ab En \u00e9chec \u00bb pendant qu'il travaille).
    if respawne is not None:
        agent_chaud._signaler_au_ticket(respawne, "message")
    return respawne


def resume_pending_agent(agent: Agent, answer: str, model: str = "") -> "Agent | None":
    """Respawn a paused agent to consume `<session>.pending.json` with the answer.

    Rend `None` — comme `continue_agent` — quand `_respawn` a REFUSÉ de lancer (un process
    tourne déjà pour cette session) : la réponse n'a alors PAS été remise, et l'appelant doit
    le dire au lieu de conclure au succès."""
    # Reprise CHAUDE d'une pause : process vivant en awaiting → push answer.txt in-process.
    # Même repli que `continue_agent` : un pid de fiche périmé ne doit pas condamner la
    # réponse de l'humain au trou noir (cf. `_adopt_live_session_process`).
    if not model and not agent_chaud._is_warm_awaiting(agent):
        agent_chaud._adopt_live_session_process(agent)
    if not model and agent_chaud._is_warm_awaiting(agent):
        return agent_chaud._push_answer(agent, answer)
    agent.auto_retry_count = 0
    respawne = agent_respawn._respawn(
        agent,
        extra_args=["--resume-pending", answer],
        banner=f"\n\n--- Resuming from AskUserQuestion ---\n\u00bb {answer}\n\n",
        model=model,
    )
    if respawne is not None:  # m\u00eame transition que la reprise chaude (`_push_answer`)
        agent_chaud._signaler_au_ticket(respawne, "reponse")
    return respawne
