# [desc] Ce qu'on a le droit de CACHER d'un agent, et depuis quand il attend une réponse. [/desc]
"""Deux règles de visibilité, partagées par toutes les listes d'agents.

Elles vivent ici, hors de `purge.py`, parce qu'elles ne purgent rien : elles décident de
ce que les surfaces MONTRENT. `store.list_agent_sessions` et `fleet.agent_tree` les
appliquent toutes les deux, ce qui garantit que la sidebar et l'arbre ne peuvent pas
diverger sur « qui est visible ».
"""
from __future__ import annotations

from pathlib import Path

from bouzecode.web_v2.services.horodatage import en_iso

from ...runtime import pending
from ...runtime.runner import agent_etat, agent_fiche

# États qui prouvent qu'un agent n'a PAS fini : il travaille, il démarre, il attend une
# réponse humaine, ou il est CHAUD ET OISIF. Mêmes états que
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
# ranger (cas 9d0789f2fdca / 63343a4b4a4a). Il reste restaurable via `restore(key)`, donc
# aucune régression de joignabilité comme en 2026-07-28 (qui visait un agent EN COURS).
ARCHIVE_PROTECTED_STATES = ("running", "awaiting_input", "awaiting_plan_validation")


def hidden_by_archive(agent: agent_fiche.Agent, deleted: dict) -> bool:
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
    son sens.

    NUANCE ORPHELIN : un état `awaiting_*` n'est protégé QUE si le process est VIVANT
    (`returncode is None`). Après un restart serveur, un agent dont le process est MORT mais
    qui avait persisté une question `AskUserQuestion` sur disque est reclassé `awaiting_input`
    par `agent_status` (branche process mort) : il NE travaille plus, personne ne le relancera
    tel quel, et l'utilisateur doit pouvoir le ranger (cas signalé 9d0789f2fdca / 63343a4b4a4a
    et le ticket « Suite du ticket 3… », tous awaiting ORPHELINS). L'incident 2026-07-28 visait
    au contraire un agent EN COURS (process vivant) : distinguer sur `returncode` corrige l'un
    sans rouvrir l'autre."""
    from . import store

    if f"agent/{agent.agent_id}" not in deleted:
        return False
    status = store.agent_status(agent)
    state = status.get("state")
    if state not in ARCHIVE_PROTECTED_STATES:
        return True
    # Awaiting ORPHELIN (process mort) : plus de travail en cours → archivable.
    if state in ("awaiting_input", "awaiting_plan_validation"):
        return status.get("returncode") is not None
    return False


def answer_no_longer_expected(agent: agent_fiche.Agent, paused: dict) -> str:
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
    if agent.ipc_dir and (Path(agent.ipc_dir) / "cancel.flag").is_file():
        return "cancelled"
    return "answered" if paused.get("ask_tc_id") in _resolved_after_pause(agent) else ""


def _resolved_after_pause(agent: agent_fiche.Agent) -> set:
    """tool_call_id résolus dans la session, seulement si elle a été retouchée APRÈS la mise
    en pause (sinon elle ne peut pas porter la réponse — et on évite de re-décoder des Mo de
    JSON à chaque construction de l'arbre)."""
    from . import store

    if not agent.session_path:
        return set()
    session_path = Path(agent.session_path)
    marker = pending.pending_path(agent.session_path)
    if not (session_path.is_file() and marker.is_file()):
        return set()
    if session_path.stat().st_mtime <= marker.stat().st_mtime:
        return set()
    data = store.load_session_json(session_path) or {}
    return {m.get("tool_call_id") for m in data.get("messages") or [] if m.get("role") == "tool"}


def asked_at(agent: agent_fiche.Agent) -> str:
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
            return en_iso(path.stat().st_mtime, "auto")
    updated_at = agent_etat.get_ipc_state(agent).get("updated_at")
    if isinstance(updated_at, (int, float)):
        return en_iso(updated_at, "auto")
    return ""
