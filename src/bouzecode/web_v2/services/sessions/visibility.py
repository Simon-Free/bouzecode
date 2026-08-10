# [desc] Ce qu'on a le droit de CACHER d'un agent, et depuis quand il attend une réponse. [/desc]
"""Deux règles de visibilité, partagées par toutes les listes d'agents.

Elles vivent ici, hors de `purge.py`, parce qu'elles ne purgent rien : elles décident de
ce que les surfaces MONTRENT. `store.list_agent_sessions` et `fleet.agent_tree` les
appliquent toutes les deux, ce qui garantit que la sidebar et l'arbre ne peuvent pas
diverger sur « qui est visible ».
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ...runtime import pending, runner

# États qui prouvent qu'un agent n'a PAS fini : il travaille, il démarre, il attend une
# réponse humaine, ou il est CHAUD ET OISIF. Mêmes états que `workflow._ACTIVE` /
# `isolation._ACTIVE_STATES`.
# `idle` = warm pool : le process est RÉSIDENT (il tient encore son worktree et reprend
# au premier message poussé). Il est distingué de `running` pour que la garde
# anti-double-tour et l'affichage cessent de le dire « en cours » — mais il reste bien
# VIVANT partout où « vivant » veut dire « n'y touche pas » : ne pas l'inscrire ici
# aurait fait disparaître des listes un agent parfaitement joignable.
ALIVE_STATES = ("running", "starting", "awaiting_input", "awaiting_plan_validation", "idle")

# États qu'un archivage MANUEL refuse de masquer — SOUS-ENSEMBLE STRICT d'ALIVE_STATES.
# Distinction voulue : `ALIVE_STATES` = « ne le fais pas disparaître des listes / de la
# joignabilité » (englobe `idle` warm-oisif et `starting`). `ARCHIVE_PROTECTED_STATES`
# = « l'archivage explicite refuse de le ranger », et ne couvre QUE les états où l'agent
# TRAVAILLE ou ATTEND une réponse humaine. Un warm-oisif (`idle`) ou un démarrage
# (`starting`) NE travaille pas : l'utilisateur qui l'archive délibérément doit pouvoir le
# ranger (cas 0123456789ab / 63343a4b4a4a). Il reste restaurable via `restore(key)`, donc
# aucune régression de joignabilité comme en 2026-07-28 (qui visait un agent EN COURS).
ARCHIVE_PROTECTED_STATES = ("running", "awaiting_input", "awaiting_plan_validation")


def hidden_by_archive(agent: runner.Agent, deleted: dict) -> bool:
    """Cet agent archivé doit-il être CACHÉ des listes ? Non s'il travaille encore.

    Le travail en cours PRIME sur le drapeau d'archivage : un agent qui tourne, ou qui
    attend une réponse humaine (`ARCHIVE_PROTECTED_STATES`), reste visible même si sa clé
    figure au registre des archivés. Sans cette règle, archiver une conversation (geste de
    rangement, parfois automatique) suffisait à faire disparaître un agent EN PLEIN TRAVAIL
    de la sidebar et de l'arbre — personne ne pouvait plus lui répondre, donc il ne repartait
    jamais (incident 2026-07-28, ~4h injoignable).

    En revanche un agent CHAUD MAIS OISIF (`idle`, warm pool) ou en simple DÉMARRAGE
    (`starting`) ne travaille pas : l'archivage explicite le range bien (il reste restaurable
    via `restore`). C'est la demande utilisateur — auparavant un warm-oisif archivé restait
    éternellement visible. Un agent terminé, lui aussi, reste caché : l'archivage garde tout
    son sens."""
    from . import store

    if f"agent/{agent.agent_id}" not in deleted:
        return False
    return store.agent_status(agent).get("state") not in ARCHIVE_PROTECTED_STATES


def answer_no_longer_expected(agent: runner.Agent, paused: dict) -> str:
    """Motif prouvant qu'une question pendante n'attend PLUS personne ; "" si elle attend.

    `<session>.pending.json` n'est supprimé que lorsque l'agent REÇOIT sa réponse. Un agent
    tué, ou dont la réponse est arrivée par un chemin qui n'a pas nettoyé le marqueur, laisse
    donc derrière lui un marqueur qui ment. Deux preuves, mesurées sur le parc réel (97
    marqueurs pendants, dont 5 portés par un agent encore enregistré) :

      * `cancel.flag` — quelqu'un a demandé l'arrêt (`runner.kill_agent` et
        `graceful_cancel_agent` l'écrivent). Un agent VIVANT le consomme et sort de sa
        pause ; s'il est encore là, c'est que l'agent n'était plus là pour le lire.
        Mesuré : `63cd2c4183e8` (tué, drapeau du 29/07 09:43) et `5de65ff25336`.
      * la question A DÉJÀ SA RÉPONSE dans la session — `ask_tc_id` figure parmi les
        `tool_call_id` résolus. Le marqueur n'est qu'un résidu. Mesuré : `47117594e206`
        (clos sur `final_answer_deferred`) et `8207c1d1daf7` (clos sur `final_answer`),
        les deux « attentes depuis le 15 et le 21 juillet » qui n'en étaient pas.

    Et surtout, ce qui ne doit PAS déclencher : l'agent qui a réellement expiré ses 900 s
    d'attente sans réponse ni demande d'arrêt (mesuré : `63343a4b4a4a`, IPC `finished` nu
    +893 s après sa question, `ask_tc_id` non résolu). Il attend toujours — c'est tout
    l'objet de la lecture du marqueur, et aucune des deux preuves ne le vise.

    On ne se sert PAS de « `finished` sans `close_reason` » comme critère : la mesure montre
    que `63cd2c4183e8`, pourtant tué, porte exactement cette signature (il était mort de son
    TTL AVANT qu'on le tue). La manière de mourir ne dit rien ; seule une réponse déjà reçue
    ou un arrêt demandé prouvent que plus personne n'est attendu."""
    from . import store

    if agent.ipc_dir and (Path(agent.ipc_dir) / "cancel.flag").is_file():
        return "cancelled"
    if not agent.session_path:
        return ""
    session_path = Path(agent.session_path)
    marker = pending.pending_path(agent.session_path)
    # Session pas retouchée depuis la mise en pause : elle ne peut pas porter la réponse.
    # Garde de COÛT autant que de sens — sans elle, chaque construction de l'arbre
    # re-décoderait le JSON (des Mo) de tout agent porteur d'un marqueur.
    if not (session_path.is_file() and marker.is_file()):
        return ""
    if session_path.stat().st_mtime <= marker.stat().st_mtime:
        return ""
    data = store.load_session_json(session_path) or {}
    resolved = {message.get("tool_call_id") for message in data.get("messages") or []
                if message.get("role") == "tool"}
    return "answered" if paused.get("ask_tc_id") in resolved else ""


def asked_at(agent: runner.Agent) -> str:
    """Quand la question en attente a été POSÉE (ISO 8601), ou "" si on ne sait pas.

    Deux traces, par ordre d'autorité :
      * `<session>.pending.json`, (ré)écrit à chaque mise en pause du tour et supprimé à
        la réponse : sa date de modification EST la date de la question, et elle survit
        à tout ;
      * `updated_at` de l'état IPC, horodatage écrit par `ipc.write_state` en même temps
        que le statut `awaiting_input`.
    Aucune des deux → "" : on ne DEVINE pas depuis quand quelqu'un attend, et surtout on
    ne confond pas cette date avec l'âge de l'agent (ils diffèrent de plusieurs jours sur
    un manager de longue haleine qui vient tout juste de poser sa première question)."""
    if agent.session_path:
        path = pending.pending_path(agent.session_path)
        if path.is_file():
            return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    updated_at = runner.get_ipc_state(agent).get("updated_at")
    if isinstance(updated_at, (int, float)):
        return datetime.fromtimestamp(updated_at, timezone.utc).isoformat()
    return ""
