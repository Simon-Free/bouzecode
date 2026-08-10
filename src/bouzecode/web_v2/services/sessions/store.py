# [desc] Index, résolution par clé et statut des sessions (agents web + sessions CLI daily). [/desc]
"""Source de vérité = les JSON de session écrits par save_progressive(), jamais le stdout.

Clés de session :
  - ``agent/<agent_id>``                      → agent web (~/.bouzecode/web_agents/)
  - ``daily/<YYYY-MM-DD>/<session_x.json>``   → session CLI (~/.bouzecode/sessions/daily/)
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ...runtime import pending, runner
from . import meta_index, visibility

DAILY_DIR = Path.home() / ".bouzecode" / "sessions" / "daily"
CACHE_PATH = Path.home() / ".bouzecode" / "web_v2" / "index_cache.json"
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


@dataclass
class SessionRef:
    key: str
    kind: str  # "agent" | "daily"
    path: Path
    agent: runner.Agent | None = None


def resolve(key: str) -> SessionRef | None:
    """Résout une clé en chemin validé (aucun chemin arbitraire accepté)."""
    agent_match = _KEY_AGENT.match(key)
    if agent_match:
        agent = runner.load_agent(agent_match.group(1))
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


def _unanswered_question(agent: runner.Agent) -> dict | None:
    """La question posée à l'utilisateur et JAMAIS répondue, lue sur DISQUE.

    `<session>.pending.json` (runtime/pending.py) est écrit quand AskUserQuestion met le
    tour en pause, et SUPPRIMÉ dès que la réponse arrive (repl._build_turn_generator) ou
    que la question est annulée (pending.cancel). Sa présence prouve donc, à elle seule,
    qu'une question attend une réponse — et elle survit à tout.

    C'est la seule trace DURABLE : l'état IPC `awaiting_input`, lui, est écrasé par un
    `finished` nu au bout des 900 s d'attente de `repl._resume_paused_warm`. Passé ce
    quart d'heure, un agent bloqué sur une question devenait indistinguable d'un agent
    terminé — question et options perdues (cas vécu : manager 0123456789ab, question de
    12:27:32, IPC écrasé à 12:42:32, invisible ensuite)."""
    if not agent.session_path or not pending.exists(agent.session_path):
        return None
    paused = pending.load(agent.session_path)
    if paused is None:
        return None
    # Le marqueur SURVIT à tout sauf à une réponse reçue : un agent tué le laisse derrière
    # lui et paraîtrait attendre indéfiniment. `visibility` dit ce qui prouve le contraire.
    return None if visibility.answer_no_longer_expected(agent, paused) else paused


def demarrage_phase(agent: runner.Agent, state: str, ipc_state: dict) -> str:
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
    if _sortie_partielle_vide(session) and not ipc_state.get("tool"):
        # La requête est partie, rien n'est encore revenu du modèle.
        return "attente_modele"
    return ""


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


def agent_status(agent: runner.Agent) -> dict:
    """Statut consolidé process + IPC + question pendante sur disque. L'agent peut être
    mort ET en attente de réponse (AskUserQuestion persiste l'état puis quitte le process)."""
    cached = _status_cache.get(agent.agent_id)
    if cached is not None:
        return dict(cached)
    agent = runner.refresh_agent_status(agent)
    ipc_state = runner.get_ipc_state(agent)
    paused = None
    if ipc_state.get("status") == "awaiting_input":
        state = "awaiting_input"
    elif ipc_state.get("status") == "awaiting_plan_validation":
        state = "awaiting_plan_validation"
    elif runner.is_running(agent):
        # CHAUD MAIS OISIF ≠ EN TRAIN DE TRAVAILLER. Un agent qui a fini son tour reste
        # résident dans le warm pool (ipc.run_agent_event_loop écrit STATUS_IDLE puis
        # sonde followup.txt). Son process EXISTE, donc `is_running` est vrai — mais il
        # ne joue AUCUN tour. Confondre les deux le rendait totalement INJOIGNABLE : la
        # garde anti-double-tour de `/api/agents/<id>/continue` (et de
        # `messaging.send_to_ticket_agent`) refuse en 409 sur `state == "running"`, donc
        # plus personne — ni l'utilisateur, ni un autre agent — ne pouvait lui parler,
        # pendant que l'UI l'annonçait « en cours » (cas vécu : manager 0123456789ab,
        # IPC `idle` depuis 18:07:43, 20 min de 409, débloqué seulement en TUANT le
        # process). L'information existait déjà dans l'IPC et se perdait ICI, faute
        # d'une branche pour la lire.
        #
        # On la relit par `runner.is_warm` — MÊME prédicat (pid vivant + IPC `idle`) que
        # celui dont `continue_agent` se sert déjà pour choisir la reprise chaude, et
        # frère de `_is_warm_awaiting` : aucune 2e règle de vivacité n'est ouverte ici.
        # Il est testé AVANT "starting" parce que l'IPC `idle` est une affirmation
        # POSITIVE du process lui-même (« j'ai fini un tour, j'attends »), là où
        # « fichier session absent » n'est qu'une inférence.
        session_path = agent.session_path or ""
        if runner.is_warm(agent):
            state = "idle"
        elif session_path and not Path(session_path).is_file():
            state = "starting"
        else:
            state = "running"
    elif agent.returncode is None and not (agent.session_path and Path(agent.session_path).is_file()):
        # NI vivant, NI returncode, NI session écrite : le process n'a JAMAIS démarré
        # (worktree provisionné, subprocess pas encore lancé). Le confondre avec "finished"
        # ouvre la FENÊTRE DE START qui déclenche un validateur prématuré sur worktree vide
        # (→ no_diff verrouillé). On le classe "starting" : le run reste ACTIF pour le workflow
        # (_ACTIVE) → derive_state=busy → aucun spawn_validator tant que la vie n'est pas confirmée.
        state = "starting"
    else:
        # Process mort : la question pendante sur disque fait foi. Testée APRÈS
        # `is_running` pour ne pas annoncer « en attente » pendant la fenêtre où un
        # `--resume-pending` tourne déjà mais n'a pas encore effacé le fichier.
        paused = _unanswered_question(agent)
        state = "awaiting_input" if paused is not None else "finished"
    result = {
        "state": state,
        "phase": demarrage_phase(agent, state, ipc_state),
        "question": ipc_state.get("question") or (paused or {}).get("question", ""),
        "options": ipc_state.get("options") or (paused or {}).get("options") or [],
        "allow_freetext": ipc_state.get(
            "allow_freetext", (paused or {}).get("allow_freetext", True)),
        "returncode": agent.returncode,
        # BATTEMENT DE CŒUR. `ipc.write_state` horodate CHAQUE changement d'état du process
        # (`updated_at`, epoch), et `runner.get_ipc_state` le rendait déjà — c'est ICI qu'il
        # se perdait, jeté au moment de recomposer le statut. Sans lui, « en cours » depuis
        # 3 s et « en cours » depuis 11 min sont le MÊME mot : c'est exactement ce qui rendait
        # indistinguables un agent qui travaille et un agent bloqué (cas eac1f0bef295, 11 min
        # d'écart entre le dernier battement et la lecture, avec `state: "running"` inchangé).
        # 0.0 quand l'IPC n'a jamais écrit (agent trop jeune, ou pas d'IPC du tout).
        "last_event_at": float(ipc_state.get("updated_at") or 0.0),
        # Tour EN COURS selon le process lui-même, pas selon l'index de sessions (qui ne bouge
        # qu'à la sauvegarde). Les deux divergeaient de plusieurs tours sur un agent actif.
        "ipc_turn": int(ipc_state.get("turn") or 0),
        # Outils du lot en cours d'exécution, publiés par `dag._announce_activity`. Vide sur
        # un agent lancé par une version antérieure du harnais : l'appelant retombe alors sur
        # le dernier outil ENREGISTRÉ dans la session (cf. `services/work/activity.py`).
        "tools": [str(t) for t in (ipc_state.get("tools") or [])],
    }
    if state == "finished":
        with _status_cache_lock:
            _status_cache[agent.agent_id] = result
    return result


def _load_cache() -> dict:
    return meta_index.read_file(CACHE_PATH)


def _save_cache(cache: dict) -> None:
    meta_index.merge_into_file(CACHE_PATH, cache)


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
    """Méta d'une session, mémorisée par mtime dans le memo du process PUIS dans `cache`.

    Voir `meta_index` : le memo est ce qui empêche une entrée d'index perdue (écriture
    concurrente) de faire re-décoder des centaines de Mo à chaque requête suivante."""
    if not path.is_file():
        return {"first_message": "(pas encore de session)", "model": "", "turn_count": 0, "saved_at": ""}
    return meta_index.memoized_meta(path, cache, lambda: _build_meta(path))


def agent_meta(agent: runner.Agent, cache: dict | None = None) -> dict:
    """Méta d'UN SEUL agent (mémorisée par mtime), sans parcourir le parc.

    `list_agent_sessions` est le chemin des LISTINGS : elle bâtit la méta de tous les agents, ce
    qui coûte le décodage complet de chaque session dont le mtime a bougé — 13,7 s mesurées à
    froid sur le parc réel. Un appelant qui n'a besoin de la méta que de quelques agents vivants
    passe par ici : il paie ces agents-là, pas les 250 autres."""
    return _session_meta(Path(agent.session_path), cache if cache is not None else _load_cache())


_NEED_INPUT_STATES = {"awaiting_input", "awaiting_plan_validation"}


def list_agent_sessions(include_tests: bool = False, cache: dict | None = None) -> list[dict]:
    """SEULEMENT les agents web (statut live). Léger : ne parcourt PAS les sessions
    daily (glob JSON coûteux, inutile pour l'onglet Conversations qui n'affiche que
    les agents). Utilisé par fleet.agent_tree.

    Chaque conversation porte :
      - ``category`` ∈ {"user","meta","subagent","test"} (nature, cf. category.py).
      - ``need_input`` bool : l'agent attend une réponse utilisateur (awaiting_input
        ou awaiting_plan_validation).

    Tri : conversations en attente d'input EN TÊTE, puis récence (saved_at||started_at).

    Filtre les sessions purgées/archivées (purge.load_deleted). Exclut par défaut les
    conversations de test (``include_tests=False``) → l'utilisateur n'a plus à les
    nettoyer manuellement.

    ``cache`` : index de méta déjà chargé par l'appelant (cf. list_sessions). Fourni,
    il est enrichi sur place et NI relu NI sauvegardé ici — c'est l'appelant qui le
    sauve une seule fois. Absent, la fonction gère elle-même son chargement et sa
    sauvegarde (les appelants existants n'ont rien à changer)."""
    from . import category, purge

    owns_cache = cache is None
    if cache is None:
        cache = _load_cache()
    deleted = purge.load_deleted()
    agents = []
    for agent in runner.list_agents():
        agent_key = f"agent/{agent.agent_id}"
        # Archivé ET fini → caché. Archivé mais VIVANT (il tourne ou il attend une
        # réponse) → gardé : la vivacité prime (cf. sessions/visibility.py).
        if visibility.hidden_by_archive(agent, deleted):
            continue
        cat = category.classify_agent(agent)
        if cat == category.CATEGORY_TEST and not include_tests:
            continue
        meta = _session_meta(Path(agent.session_path), cache)
        status = agent_status(agent)
        agents.append({
            "key": f"agent/{agent.agent_id}",
            "title": (agent.prompt or "").strip().split("\n")[0][:90] or agent.agent_id,
            "model": agent.model or meta["model"],
            "cwd": agent.cwd or "",
            "started_at": agent.started_at,
            "saved_at": meta["saved_at"],
            "turn_count": meta["turn_count"],
            "status": status,
            # Archivé MAIS gardé parce que vivant : le front l'étiquette « archivé »
            # (gris) au lieu de faire croire qu'il a été rangé pour de bon.
            "archived": agent_key in deleted,
            "close_reason": meta.get("close_reason", ""),
            "has_recap": meta.get("has_recap", False),
            "profile": agent.profile or "",
            "typology": agent.profile or "",
            "category": cat,
            "need_input": status.get("state") in _NEED_INPUT_STATES,
        })
    # need_input d'abord (True > False), puis récence décroissante.
    agents.sort(
        key=lambda item: (
            item.get("need_input", False),
            item.get("saved_at") or item["started_at"],
        ),
        reverse=True,
    )
    if owns_cache:
        _save_cache(cache)
    return agents


def list_sessions(include_tests: bool = False) -> dict:
    """Agents web (avec statut live) + sessions CLI des derniers jours.

    ``include_tests`` propagé à list_agent_sessions (défaut : tests exclus).

    L'index de méta est chargé et sauvegardé UNE SEULE FOIS pour tout l'appel : il est
    passé à list_agent_sessions, qui l'enrichit sans le relire ni le réécrire (ce chemin
    est parcouru à chaque poll du front, et le JSON complet fait plusieurs Mo)."""
    from . import purge

    cache = _load_cache()
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
