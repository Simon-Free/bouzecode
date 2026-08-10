# [desc] Détection et purge sûre des conversations de test — soft-delete d'agents web (_trash) et de sessions (registre) [/desc]
"""Détection + purge sûre des conversations de test.

Deux mécanismes complémentaires cohabitent ici :

1. **Agents web (déplacement d'artefacts)** — un agent web dont le titre OU la
   1re ligne du prompt commence par 'test' (ex: 'test typology', 'test ping').
   Purge = déplacer ses artefacts vers ``AGENTS_DIR/_trash/{id}/`` (JAMAIS rm),
   uniquement si l'agent ne tourne pas. Réversible manuellement.
   API: ``is_test_agent`` / ``list_test_candidates`` / ``purge_agents``.

2. **Sessions (registre externe, sans muter les JSON)** — soft-delete via
   ``~/.bouzecode/web_v2/deleted_sessions.json`` :
       {"<key>": {"deleted_at": "<iso>", "reason": "<str>"}}
   Une session soft-deleted est simplement exclue de ``store.list_sessions()``.
   Réversible via ``restore(key)``.
   API: ``is_test_session`` / ``detect_test_sessions`` / ``purge_test_sessions``
   / ``restore``.

Aucun cas ne supprime réellement une vraie conversation utilisateur.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from bouzecode.web_v2.runtime import runner

from . import store

# --------------------------------------------------------------------------
# 1. Agents web — soft-delete par déplacement des artefacts vers _trash
# --------------------------------------------------------------------------

# Titre/prompt qui commence par 'test' (mot entier), insensible à la casse.
# Couvre 'test typology', 'test ping', 'Test XYZ', 'test-foo', 'test:bar'.
_TEST_RE = re.compile(r"^\s*test\b", re.IGNORECASE)

TRASH_DIR = runner.AGENTS_DIR / "_trash"


def _agent_title(agent: runner.Agent) -> str:
    return (agent.prompt or "").strip().split("\n")[0][:90] or agent.agent_id


def is_test_agent(title: str, prompt: str) -> bool:
    """True si le titre OU la 1re ligne du prompt commence par 'test'."""
    first_prompt_line = (prompt or "").strip().split("\n")[0]
    return bool(_TEST_RE.match(title or "")) or bool(_TEST_RE.match(first_prompt_line))


def _is_running(agent: runner.Agent) -> bool:
    status = runner.refresh_agent_status(agent)
    if isinstance(status, dict):
        return bool(status.get("running"))
    return runner.is_running(agent)


# États qui prouvent qu'un agent n'a PAS fini : il travaille, il démarre, il attend une
# réponse humaine, ou il est chaud et oisif (`idle` : process résident du warm pool).
# Une conversation en pause n'est pas un déchet — c'est son mode normal, et une
# conversation CHAUDE encore moins : elle reprend au premier message.
_ETATS_VIVANTS = ("running", "starting", "awaiting_input", "awaiting_plan_validation", "idle")


def est_vivant(agent: runner.Agent) -> bool:
    """Cet agent est-il vivant ? Seul verdict autorisé à précéder un geste destructeur.

    `_is_running` ne peut PAS servir à cela, et c'est ce qui a détruit du travail réel le
    2026-07-28 : il appelle `refresh_agent_status`, qui ÉCRIT `returncode`/`finished_at`
    sur l'agent, puis interroge `runner.is_running`, qui lit `returncode is None`. Il
    répond donc « pas vivant » sur la foi du champ qu'il vient lui-même d'écrire. Trace
    mesurée sur le manager `0123456789ab` : `finished_at` = 12:25:53.899, artefacts
    déplacés vers `_trash/` à 12:25:53.901 — deux millisecondes plus tard — alors que le
    process tournait encore et écrivait son log à 12:27.

    Trois preuves, de la plus fiable à la moins :
      * `runner.session_process_running` — l'AUTORITÉ OS : un process vivant référence le
        `--session-file` de l'agent. Immunisée au pid recyclé comme aux champs périmés du
        .json, elle ne dépend d'aucun état écrit par qui que ce soit ;
      * le pid tracké, encore vivant et sans returncode (rapide, mais faillible : un pid
        recyclé ment dans le sens PRUDENT — il fait croire l'agent vivant, donc protège) ;
      * l'état déclaré : un agent qui attend une réponse humaine n'est pas un déchet, même
        process éteint. C'est le cas d'usage entier des conversations en pause.
    On ne conclut JAMAIS « mort » depuis `returncode`/`finished_at` seuls."""
    if runner.session_process_running(agent.session_path):
        return True
    if runner.is_running(agent):
        return True
    return store.agent_status(agent).get("state") in _ETATS_VIVANTS


def list_test_candidates() -> list[dict]:
    """Agents web détectés comme conversations de test ET non-running."""
    candidates = []
    for agent in runner.list_agents():
        title = _agent_title(agent)
        if not is_test_agent(title, agent.prompt or ""):
            continue
        if _is_running(agent):
            continue  # jamais un agent qui tourne
        candidates.append({
            "agent_id": agent.agent_id,
            "key": f"agent/{agent.agent_id}",
            "title": title,
            "started_at": agent.started_at,
        })
    candidates.sort(key=lambda c: c.get("started_at") or "", reverse=True)
    return candidates


def _artefacts(agent_id: str) -> list[Path]:
    """Les fichiers/dossiers d'un agent web (id.json, .session.json, .out.log, .ipc/)."""
    base = runner.AGENTS_DIR
    out: list[Path] = []
    for name in (f"{agent_id}.json", f"{agent_id}.session.json",
                 f"{agent_id}.pending.json", f"{agent_id}.deferred.json",
                 f"{agent_id}.out.log"):
        p = base / name
        if p.exists():
            out.append(p)
    ipc = base / f"{agent_id}.ipc"
    if ipc.exists():
        out.append(ipc)
    return out


def purge_agents(agent_ids: list[str]) -> dict:
    """Soft-delete: déplace les artefacts des agents test vers _trash/{id}/.

    Double garde-fou: refuse un agent inconnu, running, ou non détecté comme test
    (au cas où un id arbitraire serait passé). Jamais de suppression réelle.
    """
    purged: list[str] = []
    skipped: list[dict] = []
    for agent_id in agent_ids:
        agent = runner.load_agent(agent_id)
        if agent is None:
            skipped.append({"agent_id": agent_id, "reason": "agent inconnu"})
            continue
        title = _agent_title(agent)
        if not is_test_agent(title, agent.prompt or ""):
            skipped.append({"agent_id": agent_id, "reason": "pas une conversation de test"})
            continue
        if est_vivant(agent):
            skipped.append({"agent_id": agent_id, "reason": "agent vivant"})
            continue
        if not runner.destruction_permitted():
            skipped.append({"agent_id": agent_id, "reason": "destruction interdite hors exploitation"})
            continue
        dest = TRASH_DIR / agent_id
        dest.mkdir(parents=True, exist_ok=True)
        for artefact in _artefacts(agent_id):
            shutil.move(str(artefact), str(dest / artefact.name))
        purged.append(agent_id)

    # Invalider le cache list_agents (TTL 3s) sinon la sidebar ré-affiche les purgés.
    runner._list_agents_cache.clear()
    return {"purged": purged, "skipped": skipped}


def auto_purge_test_agents() -> dict:
    """Purge AUTOMATIQUE des conversations de test non-running (remplace le bouton
    manuel « Nettoyer les tests »). Détecte via list_test_candidates() puis délègue
    à purge_agents (qui re-filtre is_test + non-running). Idempotent."""
    candidates = list_test_candidates()
    ids = [c["agent_id"] for c in candidates]
    if not ids:
        return {"purged": [], "skipped": []}
    return purge_agents(ids)


# --------------------------------------------------------------------------
# 2. Sessions — soft-delete réversible via registre externe (sans muter les JSON)
# --------------------------------------------------------------------------

DELETED_PATH = Path.home() / ".bouzecode" / "web_v2" / "deleted_sessions.json"

# Heuristique CONSERVATRICE : titre commençant par le mot "test" (word-boundary,
# insensible à la casse) ET peu de tours (session éphémère). Les DEUX requis.
_TEST_TITLE = re.compile(r"^\s*test\b", re.IGNORECASE)
_MAX_TEST_TURNS = 3


def is_test_session(title: str, turn_count: int) -> bool:
    """True seulement si titre 'test ...' ET session éphémère (<=3 tours)."""
    if not title:
        return False
    if turn_count > _MAX_TEST_TURNS:
        return False
    return bool(_TEST_TITLE.match(title))


def load_deleted() -> dict:
    if not DELETED_PATH.is_file():
        return {}
    try:
        data = json.loads(DELETED_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_deleted(data: dict) -> None:
    DELETED_PATH.parent.mkdir(parents=True, exist_ok=True)
    DELETED_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def is_deleted(key: str) -> bool:
    return key in load_deleted()


# États qui prouvent qu'un agent n'a PAS fini : il travaille, il démarre, ou il attend
# une réponse humaine. Mêmes états que `workflow._ACTIVE` / `isolation._ACTIVE_STATES`.
_ALIVE_STATES = ("running", "starting", "awaiting_input", "awaiting_plan_validation")


def mark_deleted(key: str, reason: str = "test session purge") -> None:
    data = load_deleted()
    data[key] = {
        "deleted_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
    }
    save_deleted(data)


def restore(key: str) -> bool:
    """Retire une clé du registre ET rapatrie ses artefacts depuis la corbeille. True si
    elle y était.

    `archive_agents` n'écrit QUE le registre, donc l'en retirer suffit pour ses clés. Mais
    `purge_agents` (conversations de test) déplace VRAIMENT les artefacts : sans les
    rapatrier, une conv purgée ne réapparaîtrait jamais dans /api/sessions. Les deux
    chemins passent par ici, d'où le rapatriement — sans effet quand la corbeille est vide."""
    data = load_deleted()
    if key not in data:
        return False
    del data[key]
    save_deleted(data)
    agent_id = key.split("/", 1)[1] if key.startswith("agent/") else key
    src = TRASH_DIR / agent_id
    if src.is_dir():
        runner.AGENTS_DIR.mkdir(parents=True, exist_ok=True)
        for artefact in list(src.iterdir()):
            dest = runner.AGENTS_DIR / artefact.name
            if not dest.exists():
                shutil.move(str(artefact), str(dest))
        if not any(src.iterdir()):
            src.rmdir()
    runner._list_agents_cache.clear()
    return True


def archive_agents(keys: list[str]) -> dict:
    """Archive (soft-delete réversible) des conversations agent fournies.

    Contrairement à ``purge_agents`` (réservé aux tests, déplace les artefacts vers
    la corbeille), l'archivage n'efface RIEN : il inscrit la clé dans le registre
    ``deleted_sessions.json`` (raison "archived"). ``list_agent_sessions`` filtre ce
    registre → la conversation disparaît de la liste mais reste restaurable via
    ``restore(key)``. Fonctionne pour TOUTES les natures (notamment "user").

    Accepte des clés "agent/<id>" ou des id bruts. Retourne {archived, skipped}.
    """
    archived: list[str] = []
    skipped: list[dict] = []
    for raw in keys:
        key = raw if str(raw).startswith("agent/") else f"agent/{raw}"
        agent_id = key.split("/", 1)[1]
        agent = runner.load_agent(agent_id)
        if agent is None:
            skipped.append({"agent_id": agent_id, "reason": "agent inconnu"})
            continue
        # L'archivage NE DÉPLACE RIEN — le registre suffit, et c'est d'ailleurs ce que
        # promet la docstring ci-dessus. Le « soft-delete PHYSIQUE » ajouté ensuite
        # (déplacer les artefacts vers _trash/{id}/) est ce qui a fait disparaître un
        # manager VIVANT le 2026-07-28 : sortir son .json de AGENTS_DIR fait renvoyer None
        # à `load_agent`, donc 404 sur POST /api/agents/<id>/continue, donc absence de
        # l'arbre de flotte et messages de l'interface silencieusement perdus — près de
        # quatre heures injoignable alors qu'il tournait.
        # Il n'achetait rien : `list_agent_sessions` filtre déjà sur le registre, et
        # `hidden_by_archive` décide de la visibilité (un agent vivant reste visible
        # malgré le drapeau). Le déplacement ne coûtait donc QUE de la joignabilité.
        mark_deleted(key, reason="archived")
        archived.append(agent_id)  # id BRUT (cohérent avec skipped[].agent_id, aussi brut)
    runner._list_agents_cache.clear()
    return {"archived": archived, "skipped": skipped}


def stale_need_input_candidates() -> list[dict]:
    """Conversations bloquées en "need input" alors que leur process est MORT.

    Un agent qui a émis AskUserQuestion persiste l'état IPC "awaiting_input" puis
    quitte : si personne ne répond, la conversation reste éternellement en attente
    d'un input qui n'arrivera jamais (orpheline). Ces conversations sont archivables
    en masse (le frontend peut proposer un bouton "Archiver les conversations
    orphelines"). Ne renvoie JAMAIS un agent encore vivant (il attend légitimement).
    """
    from . import store

    candidates: list[dict] = []
    deleted = load_deleted()
    for agent in runner.list_agents():
        key = f"agent/{agent.agent_id}"
        if key in deleted:
            continue
        if _is_running(agent):
            continue  # process vivant : attente légitime, on n'y touche pas
        state = store.agent_status(agent).get("state")
        if state not in ("awaiting_input", "awaiting_plan_validation"):
            continue
        candidates.append({
            "key": key,
            "agent_id": agent.agent_id,
            "title": _agent_title(agent),
            "started_at": agent.started_at,
        })
    candidates.sort(key=lambda c: c.get("started_at") or "", reverse=True)
    return candidates


def _age_hours(started_at: str | None) -> float:
    """Âge en heures depuis started_at (ISO 8601). +inf si non parsable (donc archivable)."""
    if not started_at:
        return float("inf")
    try:
        stamp = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
    except ValueError:
        return float("inf")
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - stamp).total_seconds() / 3600.0


def auto_archive_stale_need_input(max_age_hours: float = 12.0) -> dict:
    """Archive AUTOMATIQUEMENT les conversations 'need input' orphelines (process mort)
    plus vieilles que max_age_hours. Une question posée puis abandonnée depuis >12h ne
    recevra jamais de réponse : on la sort de la section 'Nécessite une réponse'
    (réversible via restore). Les questions récentes (<12h) restent intactes."""
    stale = [c for c in stale_need_input_candidates() if _age_hours(c.get("started_at")) >= max_age_hours]
    if not stale:
        return {"archived": [], "skipped": []}
    return archive_agents([c["key"] for c in stale])


def _iter_rows() -> list[dict]:
    """Toutes les rows (agents + daily) à plat, avec key/title/turn_count."""
    listing = store.list_sessions()
    rows: list[dict] = list(listing.get("agents", []))
    for day in listing.get("days", []):
        rows.extend(day.get("sessions", []))
    return rows


def detect_test_sessions() -> list[dict]:
    """Candidats test (non déjà supprimés) : [{key, title, turn_count}]."""
    deleted = load_deleted()
    candidates = []
    for row in _iter_rows():
        key = row.get("key", "")
        if key in deleted:
            continue
        title = str(row.get("title", ""))
        turn_count = int(row.get("turn_count", 0) or 0)
        if is_test_session(title, turn_count):
            candidates.append({"key": key, "title": title, "turn_count": turn_count})
    return candidates


def purge_test_sessions(dry: bool = True) -> dict:
    """dry=True → renvoie les candidats sans rien toucher.
    dry=False → soft-delete chaque candidat et renvoie les clés purgées.
    """
    candidates = detect_test_sessions()
    if dry:
        return {"dry": True, "candidates": candidates}
    for candidate in candidates:
        mark_deleted(candidate["key"], reason="test session purge")
    return {"dry": False, "purged": candidates}
