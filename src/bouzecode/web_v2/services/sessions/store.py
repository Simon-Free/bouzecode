# [desc] Index, résolution par clé et statut des sessions (agents web + sessions CLI daily). [/desc]
"""Source de vérité = les JSON de session écrits par save_progressive(), jamais le stdout.

Clés de session :
  - ``agent/<agent_id>``                      → agent web (~/.bouzecode/web_agents/)
  - ``daily/<YYYY-MM-DD>/<session_x.json>``   → session CLI (~/.bouzecode/sessions/daily/)
"""
from __future__ import annotations
from bouzecode.paths import data_dir as bouzecode_data_dir

import json
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from bouzecode.web_v2.services.horodatage import cle_chrono

from ...runtime import pending
from ...runtime.runner import agent_chaud, agent_etat, agent_fiche, agent_registre, agent_vivacite
from . import meta_index, visibility

DAILY_DIR = bouzecode_data_dir() / "sessions" / "daily"
CACHE_PATH = bouzecode_data_dir() / "web_v2" / "index_cache.json"
_KEY_AGENT = re.compile(r"^agent/([0-9a-f]{6,32})$")
_KEY_DAILY = re.compile(r"^daily/(\d{4}-\d{2}-\d{2})/([A-Za-z0-9_.-]+\.json)$")
MAX_DAYS_LISTED = 10

# Cache du statut consolidé des agents TERMINÉS. Un agent "finished" (rc connu,
# process mort) est un état TERMINAL immuable (refresh_agent_status retourne tôt
# dès que returncode is not None) : il ne redevient jamais running/awaiting. On
# memoize donc son statut par agent_id, SANS TTL. Cela élimine, à chaque appel de
# list_agent_sessions/tree/overview, les ~500 refresh_agent_status + get_ipc_state
# + is_running (syscall PID) qui dominaient le 1er chargement de /api/agents/tree.
# On NE cache JAMAIS les états volatils (running/starting/awaiting_*).
_status_cache: dict[str, dict] = {}
_status_cache_lock = threading.Lock()


def invalidate_status(agent_id: str) -> None:
    """Purge l'entrée cachée d'un agent dans _status_cache.

    À appeler quand un agent TERMINÉ est respawné (continue/resume) : sans ça,
    agent_status() court-circuite en tête sur le "finished" mémorisé à vie et
    renvoie "finished" même si le process re-tourne → la sidebar l'affiche
    « Terminés » alors qu'il avance. Purger force le prochain agent_status() à
    recalculer (is_running → "running"). No-op si l'agent n'est pas caché."""
    with _status_cache_lock:
        _status_cache.pop(agent_id, None)


def reset_status_cache() -> None:
    """Forget every memorised status. For test isolation only.

    The cache is keyed by agent id and lives as long as the process. Two tests that
    happen to use the same short agent id in the same pytest worker therefore see each
    other's verdict: a `finished` agent named `recent` in one test made the `recent`
    agent of another test disappear from the orphan-question list, in whichever worker
    the two landed together."""
    with _status_cache_lock:
        _status_cache.clear()


@dataclass
class SessionRef:
    key: str
    kind: str  # "agent" | "daily"
    path: Path
    agent: agent_fiche.Agent | None = None


def resolve(key: str) -> SessionRef | None:
    """Résout une clé en chemin validé (aucun chemin arbitraire accepté)."""
    agent_match = _KEY_AGENT.match(key)
    if agent_match:
        agent = agent_fiche.load_agent(agent_match.group(1))
        if agent is None:
            return None
        return SessionRef(key=key, kind="agent", path=Path(agent.session_path), agent=agent)
    daily_match = _KEY_DAILY.match(key)
    if daily_match and ".." not in key:
        path = DAILY_DIR / daily_match.group(1) / daily_match.group(2)
        if path.is_file():
            return SessionRef(key=key, kind="daily", path=path)
    return None


def load_session_json(path: Path) -> dict | None:
    """Lecture tolérante : une sauvegarde progressive peut être en cours d'écriture."""
    for attempt in range(2):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            if attempt == 0:
                time.sleep(0.05)
    return None


def _unanswered_question(agent: agent_fiche.Agent) -> dict | None:
    """La question posée à l'utilisateur et JAMAIS répondue, lue sur DISQUE.

    `<session>.pending.json` (runtime/pending.py) est écrit quand AskUserQuestion met le
    tour en pause, et SUPPRIMÉ dès que la réponse arrive (repl._build_turn_generator) ou
    que la question est annulée (pending.cancel). Sa présence prouve donc, à elle seule,
    qu'une question attend une réponse — et elle survit à tout.

    C'est la seule trace DURABLE : l'état IPC `awaiting_input`, lui, est écrasé par un
    `finished` nu au bout des 900 s d'attente de `repl._resume_paused_warm`. Passé ce
    quart d'heure, un agent bloqué sur une question devenait indistinguable d'un agent
    terminé — question et options perdues (cas vécu : manager 9d0789f2fdca, question de
    12:27:32, IPC écrasé à 12:42:32, invisible ensuite)."""
    if not agent.session_path or not pending.exists(agent.session_path):
        return None
    paused = pending.load(agent.session_path)
    if paused is None:
        return None
    # Le marqueur SURVIT à tout sauf à une réponse reçue : un agent tué le laisse derrière
    # lui et paraîtrait attendre indéfiniment. `visibility` dit ce qui prouve le contraire.
    return None if visibility.answer_no_longer_expected(agent, paused) else paused


def demarrage_phase(agent: agent_fiche.Agent, state: str, ipc_state: dict) -> str:
    """Où en est un agent pendant les ~10 s où l'écran ne montrait RIEN.

    Mesuré le 2026-07-30 sur un dispatch réel : 0,5 s pour enregistrer la demande, ~3,9 s
    avant le premier signe de vie du process, puis 6,1 s d'attente du modèle sur le PREMIER
    tour (il écrit 20 K tokens de cache au lieu de les lire ; au 3ᵉ tour il ne met plus que
    1,5 s). Sans rien afficher, l'utilisateur croit que ça a planté — c'est le défaut
    rapporté, pas la lenteur elle-même.

    DÉRIVÉ, jamais stampé par l'agent : uniquement à partir de ce qui existe déjà sur disque.
    Aucune modification de la boucle d'agent, donc aucune divergence possible entre ce qu'elle
    croit faire et ce qu'on affiche — et la REPRISE est couverte sans un mot de plus, puisque
    la même absence de sortie partielle vaut pour un tour 1 et pour un tour 12.

    Rend "" dès qu'un état ordinaire suffit (terminé, à répondre, planté) : la phase n'est
    qu'un raffinement de l'attente, pas un état de plus.
    """
    if state not in ("starting", "running"):
        return ""
    session = Path(agent.session_path) if agent.session_path else None
    if session is None or not session.is_file():
        # Le process se lance : interpréteur, harnais, lecture du dépôt.
        return "demarrage"
    if (_sortie_partielle_vide(session) and not _outil_en_cours(ipc_state)
            and _rien_produit_depuis_le_dernier_message_utilisateur(session)):
        # La requête est partie, rien n'est encore revenu du modèle POUR CE MESSAGE. Entre deux
        # tours d'un même message (outils exécutés, modèle relancé), l'agent TRAVAILLE : la
        # phase restait collée sur « le modèle lit ta demande » pendant une relance entière.
        return "attente_modele"
    return ""


def _outil_en_cours(ipc_state: dict) -> bool:
    """L'agent écrit `tools` (liste) dans son état IPC pendant l'exécution des outils."""
    return bool(ipc_state.get("tool") or ipc_state.get("tools"))


def _rien_produit_depuis_le_dernier_message_utilisateur(session: Path) -> bool:
    """Le dernier message persisté est celui de l'utilisateur (le checkpoint est écrit dès
    son ajout) : aucune réponse, aucun outil depuis. Illisible → on ne l'affirme pas."""
    try:
        messages = json.loads(session.read_text(encoding="utf-8")).get("messages") or []
    except (OSError, ValueError, AttributeError):
        return False
    return bool(messages) and isinstance(messages[-1], dict) and messages[-1].get("role") == "user"


def _sortie_partielle_vide(session: Path) -> bool:
    """Vrai tant qu'AUCUN caractère de la réponse en cours n'est arrivé.

    `<session>.partial.json` est écrit au fil du streaming. Son absence — ou son vide —
    signifie que le modèle n'a pas encore rendu son premier token."""
    partiel = session.with_suffix(session.suffix + ".partial.json")
    if not partiel.is_file():
        partiel = session.with_name(session.name.replace(".json", ".partial.json"))
    if not partiel.is_file():
        return True
    donnees = load_session_json(partiel) or {}
    return not (donnees.get("text") or donnees.get("thinking") or donnees.get("content"))


def _etat_process_vivant(agent: agent_fiche.Agent) -> str:
    """État d'un agent dont le process existe.

    Chaud mais oisif (`idle`) n'est pas « en cours » : un agent du warm pool qui a fini son
    tour garde un process vivant, mais doit rester joignable par `/continue` (qui refuse un
    agent `running`). L'IPC `idle` est une affirmation du process lui-même, donc testée
    avant l'inférence « session pas encore écrite » → `starting`."""
    if agent_chaud.is_warm(agent):
        return "idle"
    session_path = agent.session_path or ""
    if session_path and not Path(session_path).is_file():
        return "starting"
    return "running"


def _etat_et_question(agent: agent_fiche.Agent, ipc_state: dict) -> tuple[str, dict | None]:
    """(état, question pendante sur disque) — l'IPC, puis le process, puis le disque.

    Process mort : la question persistée par AskUserQuestion fait foi. Elle est lue APRÈS
    `is_running` pour ne pas annoncer « en attente » pendant qu'une reprise tourne déjà."""
    ipc_status = ipc_state.get("status")
    if ipc_status in _NEED_INPUT_STATES:
        return ipc_status, None
    if agent_vivacite.is_running(agent):
        return _etat_process_vivant(agent), None
    session_ecrite = bool(agent.session_path and Path(agent.session_path).is_file())
    if agent.returncode is None and not session_ecrite:
        # Jamais démarré (subprocess pas encore lancé) : surtout pas « finished ».
        return "starting", None
    paused = _unanswered_question(agent)
    return ("awaiting_input" if paused is not None else "finished"), paused


def _question_affichee(ipc_state: dict, paused: dict, state: str = "") -> dict:
    """Question, options et saisie libre : l'IPC vivant d'abord, la question persistée sinon.

    Une question ne s'affiche QUE sous un état qui l'attend : une fois la réponse livrée,
    l'agent repart en `running` et la question résiduelle (state.json plus ancien, pending
    non encore supprimé) doit disparaître, sinon l'interface réclame un geste humain déjà
    fait (2026-09-29)."""
    if state and state not in _NEED_INPUT_STATES:
        return {"question": "", "options": [], "allow_freetext": True}
    return {
        "question": ipc_state.get("question") or paused.get("question", ""),
        "options": ipc_state.get("options") or paused.get("options") or [],
        "allow_freetext": ipc_state.get("allow_freetext", paused.get("allow_freetext", True)),
    }


def _fin_connue(agent) -> str:
    """Horodatage de fin porté par la fiche, "" s'il n'y en a pas.

    Tolère un agent qui n'est pas un `runner.Agent` complet : plusieurs appelants (et les
    tests de recovery/status) passent un objet minimal sans `finished_at`. Lu à l'identique
    à l'écriture et à la relecture du statut prouvé, donc la comparaison reste juste."""
    return str(getattr(agent, "finished_at", "") or "")


def agent_status(agent: agent_fiche.Agent) -> dict:
    """Statut consolidé process + IPC + question pendante sur disque. L'agent peut être
    mort ET en attente de réponse (AskUserQuestion persiste l'état puis quitte le process)."""
    from . import status_cache

    cached = _status_cache.get(agent.agent_id)
    if cached is None and agent.returncode is not None:
        # Process neuf : le statut terminal a peut-être déjà été prouvé lors d'un listing
        # précédent. L'accepter ici évite de relire fiche + état IPC de ~480 agents finis.
        # Retenu aussitôt dans la mémoire du process, comme un statut calculé : sinon CHAQUE
        # appel suivant rouvrait la même preuve (3 680 appels pour un premier /api/inbox).
        cached = status_cache.statut_prouve(agent.agent_id, _fin_connue(agent))
        if cached is not None:
            with _status_cache_lock:
                _status_cache[agent.agent_id] = cached
    if cached is not None and not agent_vivacite.is_running(agent):
        return dict(cached)
    #  Un « finished » mémorisé ne survit pas à un process VIVANT : un agent chaud relancé
    #  (/continue, « même agent »), ou dont le pid de fiche vient d'être rattrapé sur le vrai
    #  process, travaillait sous l'étiquette « terminé » tant que personne n'invalidait le cache.
    if cached is not None:
        invalidate_status(agent.agent_id)
    agent = agent_etat.refresh_agent_status(agent)
    ipc_state = agent_etat.get_ipc_state(agent)
    state, paused = _etat_et_question(agent, ipc_state)
    result = {
        "state": state,
        "phase": demarrage_phase(agent, state, ipc_state),
        **_question_affichee(ipc_state, paused or {}, state),
        "returncode": agent.returncode,
        # Battement de cœur (epoch du dernier changement d'état IPC) : distingue un agent
        # qui travaille d'un agent bloqué. 0.0 si l'IPC n'a jamais écrit.
        "last_event_at": float(ipc_state.get("updated_at") or 0.0),
        # Tour en cours selon le process (l'index de sessions ne bouge qu'à la sauvegarde).
        "ipc_turn": int(ipc_state.get("turn") or 0),
        # Outils du lot en cours ; vide sur un harnais ancien (repli : services/work/activity.py).
        "tools": [str(t) for t in (ipc_state.get("tools") or [])],
    }
    if state == "finished":
        with _status_cache_lock:
            _status_cache[agent.agent_id] = result
        status_cache.memoriser(agent.agent_id, _fin_connue(agent), result)
    return result


def _save_cache(cache: dict) -> None:
    meta_index.save_index(CACHE_PATH, cache)


def _metas_fraiches() -> meta_index.DirtyTrackingIndex:
    """Les méta BÂTIES pendant un listing (le reste vient du memo, amorcé depuis le fichier une
    fois par process) : c'est tout ce que `_save_cache` a à fusionner dans le fichier."""
    return meta_index.DirtyTrackingIndex()


def _last_tool_called(data: dict) -> str:
    """Nom du dernier outil appelé par l'assistant dans cette session ('' si aucun).

    Le dernier message assistant PORTEUR de tool_calls fait foi : on remonte les messages,
    et le dernier appel du lot gagne (c'est celui qui a démarré en dernier)."""
    for message in reversed(data.get("messages") or []):
        if message.get("role") != "assistant":
            continue
        calls = message.get("tool_calls") or []
        if calls:
            return str(calls[-1].get("name") or "")
    return ""


def _build_meta(path: Path) -> dict:
    """Méta d'une session, au prix d'un décodage COMPLET de son JSON (jusqu'à 112 Mo) :
    `turn_count` et `close_reason` sont écrits après le tableau `messages`, donc rien de
    moins ne suffit. Ne l'appeler qu'à travers `_session_meta` (index + memo)."""
    data = load_session_json(path) or {}
    return {
        "first_message": data.get("first_message") or path.name,
        "model": data.get("model", ""),
        "turn_count": data.get("turn_count", 0),
        "saved_at": data.get("saved_at", ""),
        "close_reason": data.get("close_reason", ""),
        # Dernier outil ENREGISTRÉ dans la session. Repli d'activité quand l'IPC ne publie
        # rien (agent lancé par une version antérieure du harnais, ou tour déjà sauvegardé) :
        # gratuit, puisqu'on décode déjà tout le JSON ici et que le résultat est mémorisé par
        # mtime — aucune lecture supplémentaire, à aucun appel.
        "last_tool": _last_tool_called(data),
        # Récap structuré présent ? (gratuit : on parse déjà la session, cache mtime) →
        # l'UI n'affiche la pastille « Récap » que pour les agents qui en ont vraiment un.
        "has_recap": isinstance(data.get("recap"), dict) and bool(data.get("recap")),
    }


def _session_meta(path: Path, cache: dict) -> dict:
    """Méta d'une session, mémorisée par mtime dans le memo du process (amorcé une fois depuis
    `index_cache.json`) ; une méta bâtie est ajoutée à `cache`, que l'appelant sauve.

    Voir `meta_index` : le memo est ce qui empêche une entrée d'index perdue (écriture
    concurrente) de faire re-décoder des centaines de Mo à chaque requête suivante."""
    if not path.is_file():
        return {"first_message": "(pas encore de session)", "model": "", "turn_count": 0, "saved_at": ""}
    meta_index.amorcer(CACHE_PATH)
    return meta_index.memoized_meta(path, cache, lambda: _build_meta(path))


def agent_meta(agent: agent_fiche.Agent, cache: dict | None = None) -> dict:
    """Méta d'UN SEUL agent (mémorisée par mtime), sans parcourir le parc.

    `list_agent_sessions` est le chemin des LISTINGS : elle bâtit la méta de tous les agents, ce
    qui coûte le décodage complet de chaque session dont le mtime a bougé — 13,7 s mesurées à
    froid sur le parc réel. Un appelant qui n'a besoin de la méta que de quelques agents vivants
    passe par ici : il paie ces agents-là, pas les 250 autres."""
    return _session_meta(Path(agent.session_path), cache if cache is not None else {})


_NEED_INPUT_STATES = {"awaiting_input", "awaiting_plan_validation"}


def _ligne_conversation(agent: agent_fiche.Agent, meta: dict, archived: bool, cat: str) -> dict:
    """Une conversation telle que la sert le listing (cf. `list_agent_sessions`)."""
    status = agent_status(agent)
    return {
        "key": f"agent/{agent.agent_id}",
        "title": (agent.prompt or "").strip().split("\n")[0][:90] or agent.agent_id,
        "model": agent.model or meta["model"],
        "cwd": agent.cwd or "",
        "started_at": agent.started_at,
        "saved_at": meta["saved_at"],
        "turn_count": meta["turn_count"],
        "status": status,
        # Archivé MAIS gardé parce que vivant : le front l'étiquette « archivé ».
        "archived": archived,
        "close_reason": meta.get("close_reason", ""),
        "has_recap": meta.get("has_recap", False),
        "profile": agent.profile or "",
        "typology": agent.profile or "",
        "category": cat,
        "need_input": status.get("state") in _NEED_INPUT_STATES,
        # Le ticket porté par l'agent : l'historique de l'assistant du Bureau reprend une
        # conversation par lui (`POST /api/projects/<slug>/tickets/<id>/messages`).
        "ticket_id": getattr(agent, "ticket_id", "") or "",
        "ticket_slug": getattr(agent, "ticket_slug", "") or "",
    }


def list_agent_sessions(include_tests: bool = False, cache: dict | None = None) -> list[dict]:
    """Les conversations des agents web, statut live compris (utilisé par fleet.agent_tree).

    Chaque conversation porte ``category`` ∈ {"user","meta","subagent","test"} et
    ``need_input``. Tri : en attente de réponse d'abord, puis récence (saved_at||started_at).
    Les sessions archivées et finies sont exclues (un archivé vivant reste visible,
    cf. sessions/visibility.py) ; les conversations de test aussi, sauf ``include_tests``.

    ``cache`` : méta fraîches de l'appelant, enrichies sur place et NON sauvegardées ici
    (l'appelant les sauve une fois). Absent, la fonction tient les siennes et les sauve."""
    from . import category, purge, status_cache

    owns_cache = cache is None
    if cache is None:
        cache = _metas_fraiches()
    deleted = purge.load_deleted()
    agents = []
    for agent in agent_registre.list_agents():
        if visibility.hidden_by_archive(agent, deleted):
            continue
        cat = category.classify_agent(agent)
        if cat == category.CATEGORY_TEST and not include_tests:
            continue
        meta = _session_meta(Path(agent.session_path), cache)
        agents.append(_ligne_conversation(agent, meta, f"agent/{agent.agent_id}" in deleted, cat))
    agents.sort(
        key=lambda item: (item["need_input"], cle_chrono(item.get("saved_at") or item["started_at"])),
        reverse=True,
    )
    if owns_cache:
        _save_cache(cache)
    # Une seule écriture pour tous les statuts terminaux découverts pendant ce listing.
    status_cache.flush()
    return agents


def list_sessions(include_tests: bool = False) -> dict:
    """Agents web (avec statut live) + sessions CLI des derniers jours.

    ``include_tests`` propagé à list_agent_sessions (défaut : tests exclus).

    L'index de méta n'est lu qu'une fois par PROCESS (`meta_index.amorcer`) et sauvegardé au
    plus une fois pour tout l'appel, seulement si une méta a été bâtie : les méta fraîches
    sont passées à list_agent_sessions, qui les enrichit sans rien réécrire (ce chemin est
    parcouru à chaque poll du front, et le JSON complet fait plusieurs Mo)."""
    from . import purge

    cache = _metas_fraiches()
    deleted = purge.load_deleted()
    agents = list_agent_sessions(include_tests=include_tests, cache=cache)

    days = []
    if DAILY_DIR.exists():
        day_dirs = sorted((d for d in DAILY_DIR.iterdir() if d.is_dir()), reverse=True)
        for day_dir in day_dirs[:MAX_DAYS_LISTED]:
            rows = []
            for session_file in day_dir.glob("session_*.json"):
                if session_file.name.endswith(".bak.json"):
                    continue
                daily_key = f"daily/{day_dir.name}/{session_file.name}"
                if daily_key in deleted:
                    continue
                meta = _session_meta(session_file, cache)
                rows.append({
                    "key": daily_key,
                    "title": str(meta["first_message"])[:90],
                    "model": meta["model"],
                    "turn_count": meta["turn_count"],
                    "saved_at": meta["saved_at"],
                    "close_reason": meta.get("close_reason", ""),
                })
            rows.sort(key=lambda r: r["saved_at"] or "", reverse=True)
            if rows:
                days.append({"date": day_dir.name, "sessions": rows})
    _save_cache(cache)
    return {"agents": agents, "days": days}


def session_meta_full(data: dict) -> dict:
    """Méta affichée en tête de page session."""
    return {
        "first_message": data.get("first_message", ""),
        "model": data.get("model", ""),
        "turn_count": data.get("turn_count", 0),
        "saved_at": data.get("saved_at", ""),
        "input_tokens": data.get("total_input_tokens", 0),
        "output_tokens": data.get("total_output_tokens", 0),
        "files_edited": len(data.get("file_snapshots") or {}),
        "close_reason": data.get("close_reason", ""),
        "final_answer": data.get("final_answer", ""),
    }
