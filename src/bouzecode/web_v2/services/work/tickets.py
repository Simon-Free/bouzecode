# [desc] Façade métier ticket : CRUD + runs/verdicts/statut, ré-exportant _persistence (SQLite) et _prompts. [/desc]
"""Un ticket = {id, title, prompt, created_at, done, comments[], runs[]}.
Run = {agent_id, kind: work|validate_tests|validate_refacto, model, started_at, verdict}.
Le verdict d'une validation est parsé depuis le dernier message assistant (VERDICT: OK|KO).

Façade : la couche SQLite vit dans `_persistence.py`, les prompts validateur dans
`_prompts.py`. Ce module garde le CRUD métier + runs/verdicts/statut et ré-exporte les
deux sous-modules pour que les appelants continuent d'utiliser `tickets.<symbole>`."""
from __future__ import annotations

import re
import threading
import uuid
from pathlib import Path

from ...runtime import runner
from ..sessions import store
from ._persistence import (  # noqa: F401 — ré-export façade
    TICKETS_DIR,
    _connect,
    _db_path,
    _ensure_migrated,
    _load,
    _load_one,
    _mutate,
    _now,
    _save,
    _save_unlocked,
    _tickets_lock,
    _upsert_one,
    all_tickets,
    launching_tickets,
    parent_agent_ids,
)
from ._prompts import (  # noqa: F401 — ré-export façade
    VALIDATORS,
    build_validator_prompt,
    coder_report,
    extract_final_answer,
)
from ._status import derive_status  # noqa: F401 — ré-export façade

# Cache des verdicts par agent_id. Un run terminé (state=="finished") portant un verdict est
# IMMUABLE : son verdict ne changera plus. On memoize agent_id -> verdict pour éviter de
# re-lire ~200 fichiers agent depuis le disque à CHAQUE overview (lenteur du 1er accès froid).
# Lecture seule, donc aucune collision avec le tick wake (pas de _save).
_verdict_cache: dict[str, str] = {}
_verdict_cache_lock = threading.Lock()

_VERDICT_RE = re.compile(r"VERDICT\s*:\s*(OK|KO)", re.IGNORECASE)
# Blocs de raisonnement : un validateur y PÈSE des hypothèses (« … sinon VERDICT: KO ») qui ne
# sont PAS un verdict rendu. On les retire du texte AVANT de chercher la ligne VERDICT.
_THINKING_RE = re.compile(r"<thinking>.*?</thinking>", re.DOTALL | re.IGNORECASE)


def create_ticket(slug: str, title: str, prompt: str) -> dict:
    ticket = {
        "id": uuid.uuid4().hex[:8], "title": title.strip(), "prompt": prompt.strip(),
        "created_at": _now(), "done": False, "comments": [], "runs": [],
    }
    with _tickets_lock, _connect() as conn:  # INSERT d'une ligne : seq auto → apparaît en tête
        _ensure_migrated(conn, slug)
        _upsert_one(conn, slug, ticket)
    return ticket


def get_ticket(slug: str, ticket_id: str) -> dict | None:
    """LE ticket demandé (archivé compris), ou None s'il n'existe pas. Lit UNE ligne."""
    return _load_one(slug, ticket_id)


def archive_ticket(slug: str, ticket_id: str) -> dict | None:
    """Archivage MANUEL et RÉVERSIBLE d'un ticket (action explicite du user). Marque
    `archived` SANS jamais retirer le ticket du store : c'est le SEUL retrait volontaire du
    board. `list_tickets` masque les archivés par défaut ; `unarchive_ticket` les ramène.
    Renvoie le ticket muté, ou None s'il est inconnu."""
    return _mutate(slug, ticket_id,
                   lambda t: t.update({"archived": True, "archived_at": _now()}))


def unarchive_ticket(slug: str, ticket_id: str) -> dict | None:
    """Annule l'archivage : le ticket revient sur le board actif. None si inconnu."""
    def _apply(t: dict) -> None:
        t.pop("archived", None)
        t.pop("archived_at", None)
    return _mutate(slug, ticket_id, _apply)


def ticket_summary(ticket: dict, parents_with_children: set[str] | None = None,
                   liveness_state: str = "") -> dict:
    """Light shape: no prompt, no comment text, add comments_count.
    `parents_with_children` et `liveness_state` sont transmis tels quels à `derive_status`
    (cf. `parent_agent_ids`, `liveness.classify_ticket`)."""
    runs_light = []
    for r in ticket.get("runs", []):
        runs_light.append({
            k: v for k, v in r.items()
            if k in ("agent_id", "kind", "model", "state", "verdict", "question")
        })
    summary = {
        "id": ticket["id"],
        "title": ticket["title"],
        "status": derive_status(ticket, parents_with_children, liveness_state),
        "done": ticket.get("done", False),
        "created_at": ticket["created_at"],
        "comments_count": len(ticket.get("comments", [])),
        "runs": runs_light,
    }
    if "typology" in ticket:
        summary["typology"] = ticket["typology"]
    if ticket.get("ephemeral"):
        summary["ephemeral"] = True
    if ticket.get("launching"):
        summary["launching"] = True
    return summary


def update_ticket(slug: str, ticket: dict) -> None:
    """Remplace le ticket par son id, ATOMIQUEMENT (UPSERT d'une seule ligne). Écrit le ticket
    appelant tel quel : pour une modif read-modify d'un champ, préférer `_mutate` qui relit d'abord
    la version fraîche en base (évite d'écraser des màj concurrentes du MÊME ticket)."""
    if not ticket.get("id"):
        return
    with _tickets_lock, _connect() as conn:
        _ensure_migrated(conn, slug)
        _upsert_one(conn, slug, ticket)


def set_launching(slug: str, ticket: dict) -> None:
    """Marque le ticket comme EN COURS DE LANCEMENT (worktree+spawn en fond, pas encore de run).
    Rend le ticket visible/actif côté board entre la création et le spawn effectif (sinon il
    apparaîtrait sans run = 'à faire'/mort). Le drapeau est retiré par add_run (succès) ou par
    _launch_bg (échec).

    Une NOUVELLE tentative efface l'échec de lancement précédent (`launch_failed`) : sinon le
    board afficherait « lancement échoué » sur un ticket dont la relance est en vol, et le
    réveil du parent le compterait comme terminal alors qu'il redémarre."""
    def _apply(t: dict) -> None:
        t["launching"] = True
        t.pop("launch_failed", None)
    _mutate(slug, ticket["id"], _apply)
    ticket["launching"] = True
    ticket.pop("launch_failed", None)


def add_run(slug: str, ticket: dict, agent_id: str, kind: str, model: str,
            typology: str = "") -> None:
    run = {
        "agent_id": agent_id, "kind": kind, "model": model,
        "started_at": _now(), "verdict": None, "typology": typology,
    }
    def _apply(t: dict) -> None:
        t.setdefault("runs", []).insert(0, run)
        # Un nouveau run RÉ-ACTIVE le ticket : purge les drapeaux terminaux STALE d'un cycle
        # précédent (crashed/reaped). Sinon derive_state resterait 'crashed' à vie (faux crash
        # transitoire du watchdog) et le reaper faucherait un ticket pourtant en plein retravail.
        t.pop("crashed", None)
        t.pop("reaped", None)
        t.pop("launching", None)  # le vrai run remplace l'état 'launching' transitoire
        t.pop("launch_failed", None)  # un agent a démarré : l'échec de lancement est périmé
        # L'agent tourne : les phases de préparation (worktree, venv, spawn) n'ont plus de
        # sens et leur laisser la place afficherait « démarrage de l'agent » sur un agent
        # démarré. Import LOCAL : `launch_phase` importe ce module (façade des tickets).
        from .launch_phase import clear_phase
        clear_phase(t)
    _mutate(slug, ticket["id"], _apply)
    ticket.setdefault("runs", []).insert(0, run)  # garder l'objet appelant cohérent
    ticket.pop("crashed", None)
    ticket.pop("reaped", None)
    ticket.pop("launching", None)
    ticket.pop("launch_failed", None)
    from .launch_phase import clear_phase
    clear_phase(ticket)


# Posé sur un ticket ENFANT ré-instruit par son manager (`messaging.send_to_ticket_agent`),
# retiré par `mark_run_completed` : tant qu'il est là, l'enfant DOIT une réponse et n'est pas
# une issue pour `wake.ticket_terminal` — sinon le manager qui attend cette réponse se fait
# clôturer pendant que l'enfant redémarre.
AWAITING_REPLY_KEY = "awaiting_reply"


def mark_awaiting_reply(slug: str, ticket: dict) -> None:
    """L'enfant vient d'être RÉ-INSTRUIT : il doit une réponse jusqu'à sa prochaine clôture."""
    _mutate(slug, ticket["id"], lambda t: t.__setitem__(AWAITING_REPLY_KEY, True))
    ticket[AWAITING_REPLY_KEY] = True


def mark_run_completed(slug: str, ticket: dict, agent_id: str) -> None:
    """Marque le(s) run(s) de `agent_id` comme `completed` et COMPTE LE TOUR (`turns`).
    Appelé quand la clôture gracieuse d'un run est traitée (endpoint /completed / hook
    on_completion). Sert au watchdog à distinguer un run terminé proprement d'un CRASH
    (process mort sans ce marqueur). Read-modify-write atomique sur la version fraîche.

    `turns` : nombre de tours que ce run a CLOS. `completed` est un booléen, donc il ne
    rebouge plus quand un agent ré-instruit (`continue_agent`, MÊME run) reclôt un tour de
    plus — c'est précisément ce qui rendait `wake.children_signature` aveugle au retravail
    d'un enfant et condamnait son manager à dormir. Ce compteur est LA différence observable
    entre « rien n'a bougé » et « l'enfant a re-livré ». Écriture : une par clôture de tour,
    au moment où le ticket était déjà réécrit — aucun tick supplémentaire ne l'incrémente."""
    def _apply(t: dict) -> bool:
        changed = t.pop(AWAITING_REPLY_KEY, None) is not None  # le tour clos EST la réponse
        for run in t.get("runs") or []:
            if isinstance(run, dict) and run.get("agent_id") == agent_id:
                run["completed"] = True
                run["turns"] = int(run.get("turns") or 0) + 1
                changed = True
        return changed  # False → _mutate ne réécrit pas (aucun run de cet agent)
    _mutate(slug, ticket["id"], _apply)
    ticket.pop(AWAITING_REPLY_KEY, None)
    for run in ticket.get("runs") or []:  # miroir sur l'objet appelant
        if isinstance(run, dict) and run.get("agent_id") == agent_id:
            run["completed"] = True
            run["turns"] = int(run.get("turns") or 0) + 1


def add_comment(slug: str, ticket: dict, text: str, sent: bool) -> None:
    comment = {"at": _now(), "text": text, "sent": sent}
    _mutate(slug, ticket["id"], lambda t: t.setdefault("comments", []).append(comment))
    ticket.setdefault("comments", []).append(comment)


def _delivered_texts(message: dict):
    """Textes LIVRÉS d'un message (thinking retiré) pouvant porter la ligne VERDICT : contenu
    assistant HORS <thinking>, answer d'un tool_call FinalAnswer, ou tool_result FinalAnswer."""
    if message.get("role") == "assistant":
        if isinstance(message.get("content"), str):
            yield _THINKING_RE.sub("", message["content"])
        for call in message.get("tool_calls") or []:
            if call.get("name") == "FinalAnswer":
                yield str((call.get("input") or {}).get("answer", ""))
    elif message.get("role") == "tool" and message.get("name") == "FinalAnswer":
        if isinstance(message.get("content"), str):
            yield message["content"]


def _find_verdict(agent: runner.Agent) -> str | None:
    """Verdict d'une validation — parsé depuis le texte LIVRÉ (thinking exclu).

    IMPORTANT (bug du KO fantôme) : on ne prend PLUS le dernier VERDICT du texte brut, car il
    inclut le THINKING où un validateur pèse des hypothèses (« … sinon VERDICT: KO »). Un
    validateur COUPÉ avant de livrer, dont l'unique « VERDICT: KO » vivait dans un <thinking>,
    produisait un KO FANTÔME → rework à objections vides qui bloquait le coder. On retire les
    blocs <thinking> puis on remonte les messages : le 1er VERDICT livré (le plus récent) gagne.
    """
    session_path = Path(agent.session_path)
    if not session_path.is_file():
        return None
    # Fast NEGATIVE only : si le tail (64 Ko de fin) ne contient AUCUN token VERDICT, inutile
    # de parser la session complète (cas majoritaire). On ne LIT PAS le verdict du tail brut.
    try:
        file_size = session_path.stat().st_size
        if file_size > 0:
            with open(session_path, "rb") as f:
                f.seek(max(0, file_size - 65_536))
                tail = f.read().decode("utf-8", errors="replace")
            if not _VERDICT_RE.search(tail):
                return None
    except OSError:
        pass
    # Parse SAIN : verdict dans le texte livré (thinking déjà retiré par _delivered_texts).
    data = store.load_session_json(session_path) or {}
    for message in reversed(data.get("messages", [])):
        for text in _delivered_texts(message):
            match = _VERDICT_RE.search(text)
            if match:
                return match.group(1).upper()
    return None


def _attach_run_state(run: dict, done_agent: str = "", agents_index: dict | None = None) -> None:
    agent_id = run["agent_id"]
    # agents_index : {agent_id: Agent} déjà chargé en 1 seul list_agents par l'appelant
    # (compteurs home). Lookup mémoire au lieu d'un load_agent disque PAR run (~500 runs
    # → 15s à froid). Fallback load_agent pour les autres appelants (page projet).
    agent = agents_index.get(agent_id) if agents_index is not None else runner.load_agent(agent_id)
    run["state"] = store.agent_status(agent)["state"] if agent else "disparu"
    # The agent whose on_completion hook is driving the chain is treated as
    # finished even though its process hasn't exited yet — so its verdict is
    # parsed and the workflow can advance on the SAME turn it closed.
    if done_agent and run["agent_id"] == done_agent:
        run["state"] = "finished"
    run["key"] = f"agent/{run['agent_id']}"


# Typologies dont l'agent termine par une ligne VERDICT: OK|KO (en plus des runs
# de validation kind=validate*). Permet de remonter le verdict d'un ticket de review.
_VERDICT_TYPOLOGIES = {"review", "parity-review", "validateur", "manager"}


def _run_carries_verdict(run: dict) -> bool:
    """Un run terminé peut porter une ligne VERDICT s'il s'agit d'une validation
    (kind validate*) ou d'un run dont la typologie en produit une (review, parité,
    validateur). Évite de tail-lire les sessions de dev classiques à chaque refresh."""
    if run.get("verdict") is not None:
        return False
    return str(run.get("kind", "")).startswith("validate") or run.get("typology") in _VERDICT_TYPOLOGIES


def _apply_parsed_verdicts(ticket: dict, verdicts: dict[str, str]) -> bool:
    """Reporte {agent_id: verdict} sur la version FRAÎCHE du ticket, et RIEN d'autre.
    Renvoie False quand rien n'a bougé — `_mutate` n'écrit alors pas la ligne."""
    changed = False
    for run in ticket.get("runs") or []:
        if not isinstance(run, dict):
            continue
        verdict = verdicts.get(run.get("agent_id") or "")
        if verdict and run.get("verdict") != verdict:
            run["verdict"] = verdict
            changed = True
    return changed


def refresh_verdicts(slug: str, tickets: list[dict], done_agent: str = "", persist: bool = True,
                     agents_index: dict | None = None) -> None:
    """Complète l'état live des runs et parse les verdicts des runs terminés qui en portent un.
    `done_agent` : l'agent dont le hook pilote la chaîne, traité comme terminé.
    `persist=False` : rafraîchit EN MÉMOIRE sans réécrire le store — pour les chemins de LECTURE
    (compteurs home) qui, en écrivant à chaque poll, entraient en collision avec le tick wake
    (course os.replace WinError + lock) et bloquaient /api/projects pendant des dizaines de s.
    La persistance des verdicts reste faite par les chemins autoritatifs (hook completed).

    PERSISTANCE CIBLÉE (fix du lost-update silencieux du 2026-07-27) : `tickets` est un
    instantané chargé AVANT le rafraîchissement. L'ancienne version réécrivait cette liste
    ENTIÈRE dès qu'UN verdict changeait ; toute mutation faite entre-temps par un autre
    écrivain (agent CLI, autre requête) était réécrasée par l'instantané périmé, sans erreur
    ni trace. On n'écrit donc plus que les tickets dont un verdict a réellement changé, et
    uniquement via `_mutate` — read-modify-write ATOMIQUE d'UNE ligne, qui relit la version
    fraîche et n'y pose QUE le champ `verdict`. Effet de bord bienvenu : l'état live des runs
    (`state`/`key`/`pid_alive`) n'a plus besoin d'être strippé, il n'est jamais écrit."""
    parsed: dict[str, dict[str, str]] = {}  # ticket_id -> {agent_id: verdict}
    for ticket in tickets:
        for run in ticket["runs"]:
            _attach_run_state(run, done_agent, agents_index)
            if _run_carries_verdict(run) and run["state"] == "finished":
                agent_id = run["agent_id"]
                with _verdict_cache_lock:
                    verdict = _verdict_cache.get(agent_id)
                if verdict is None:
                    agent = (agents_index.get(agent_id) if agents_index is not None
                             else runner.load_agent(agent_id))
                    verdict = _find_verdict(agent) if agent else None
                    if verdict:
                        with _verdict_cache_lock:
                            _verdict_cache[agent_id] = verdict
                if verdict:
                    run["verdict"] = verdict
                    parsed.setdefault(ticket["id"], {})[agent_id] = verdict
    if not persist:
        return
    for ticket_id, verdicts in parsed.items():
        _mutate(slug, ticket_id, lambda fresh, found=verdicts: _apply_parsed_verdicts(fresh, found))


def list_tickets(slug: str, refresh: bool = False, done_agent: str = "",
                 persist: bool = True, include_archived: bool = False,
                 agents_index: dict | None = None) -> list[dict]:
    tickets = _load(slug)
    # Chemin LECTURE PURE (compteurs home : not persist AND not include_archived) : on filtre
    # les archivés AVANT le refresh — on ne les renvoie pas ET on ne persiste pas, donc scanner
    # leurs runs (load_agent/session par run) serait 100% gâché. Gros gain : ~⅓ des runs sont
    # archivés. Les autres chemins gardent le refresh sur la liste COMPLÈTE : persist=True doit
    # réécrire les archivés (archiver ne supprime jamais du store), et include_archived les rend.
    if not include_archived and not persist:
        tickets = [t for t in tickets if not t.get("archived")]
    if refresh:
        refresh_verdicts(slug, tickets, done_agent, persist=persist, agents_index=agents_index)
    if not include_archived:
        tickets = [t for t in tickets if not t.get("archived")]
    return tickets


