# [desc] Tickets par projet: création à la volée, runs (travail/validations), commentaires, verdicts. [/desc]
"""Un ticket = {id, title, prompt, created_at, done, comments[], runs[]}.
Run = {agent_id, kind: work|validate_tests|validate_refacto, model, started_at, verdict}.
Le verdict d'une validation est parsé depuis le dernier message assistant (VERDICT: OK|KO)."""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

from ....web import runner
from ..sessions import store

_tickets_lock = threading.Lock()

TICKETS_DIR = Path.home() / ".bouzecode" / "web_v2" / "tickets"
_VERDICT_RE = re.compile(r"VERDICT\s*:\s*(OK|KO)", re.IGNORECASE)

VALIDATORS = {
    "tests": (
        "Tu es un agent de validation CI. Lance la suite de tests pertinente du projet "
        "(pytest -n auto pour du Python) et analyse les échecs éventuels liés au ticket "
        "ci-dessous. Ne corrige rien.\n"
        "ENVIRONNEMENT : utilise le venv du projet, JAMAIS le Python système — depuis la "
        "racine du projet : & .venv\\Scripts\\python.exe -m pytest ... -v. Si des options "
        "pytest de la config ne sont pas installées (ex: --reruns), ajoute "
        "--override-ini=\"addopts=\".\n\nTicket : {title}\n{prompt}\n\n"
        "Termine ta réponse par une ligne contenant exactement 'VERDICT: OK' si les tests "
        "sont verts, sinon 'VERDICT: KO' avec la liste des échecs juste avant. Émets toujours "
        "cette ligne, même si les tests n'ont pas pu tourner (environnement cassé → VERDICT: KO)."
    ),
    "refacto": (
        "Tu es un agent de validation qualité. Passe en revue les fichiers touchés par le "
        "ticket ci-dessous (git status/diff ou fichiers récents). Règles : fichiers < 200 "
        "lignes, ≤ 5 fichiers par dossier, noms descriptifs, pas de try/except inutile, pas "
        "d'abstraction prématurée. Ne corrige rien.\n\nTicket : {title}\n{prompt}\n\n"
        "Termine ta réponse par une ligne contenant exactement 'VERDICT: OK' ou 'VERDICT: KO' "
        "avec les violations juste avant."
    ),
}


def _path(slug: str) -> Path:
    return TICKETS_DIR / f"{slug}.json"


def _load(slug: str) -> list[dict]:
    with _tickets_lock:
        if not _path(slug).is_file():
            return []
        tickets = json.loads(_path(slug).read_text(encoding="utf-8"))
        return tickets if isinstance(tickets, list) else []


def _save(slug: str, tickets: list[dict]) -> None:
    with _tickets_lock:
        TICKETS_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path = _path(slug).with_suffix(".tmp")
        tmp_path.write_text(json.dumps(tickets, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(_path(slug))


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def create_ticket(slug: str, title: str, prompt: str) -> dict:
    ticket = {
        "id": uuid.uuid4().hex[:8], "title": title.strip(), "prompt": prompt.strip(),
        "created_at": _now(), "done": False, "comments": [], "runs": [],
    }
    tickets = _load(slug)
    tickets.insert(0, ticket)
    _save(slug, tickets)
    return ticket


def get_ticket(slug: str, ticket_id: str) -> dict | None:
    return next((t for t in _load(slug) if t["id"] == ticket_id), None)


def update_ticket(slug: str, ticket: dict) -> None:
    tickets = [ticket if t["id"] == ticket["id"] else t for t in _load(slug)]
    _save(slug, tickets)


def add_run(slug: str, ticket: dict, agent_id: str, kind: str, model: str) -> None:
    ticket["runs"].insert(0, {
        "agent_id": agent_id, "kind": kind, "model": model,
        "started_at": _now(), "verdict": None,
    })
    update_ticket(slug, ticket)


def add_comment(slug: str, ticket: dict, text: str, sent: bool) -> None:
    ticket["comments"].append({"at": _now(), "text": text, "sent": sent})
    update_ticket(slug, ticket)


def _verdict_texts(message: dict):
    """Textes d'un message pouvant porter la ligne VERDICT : contenu assistant,
    answer d'un tool_call FinalAnswer, ou tool_result FinalAnswer."""
    if message.get("role") == "assistant":
        if isinstance(message.get("content"), str):
            yield message["content"]
        for call in message.get("tool_calls") or []:
            if call.get("name") == "FinalAnswer":
                yield str((call.get("input") or {}).get("answer", ""))
    elif message.get("role") == "tool" and message.get("name") == "FinalAnswer":
        if isinstance(message.get("content"), str):
            yield message["content"]


def _find_verdict(agent: runner.Agent) -> str | None:
    """Remonte la session jusqu'à une ligne VERDICT : le dernier tour peut être
    un tour d'enforcement sans contenu utile, et le verdict peut être livré via
    le tool FinalAnswer plutôt qu'en texte assistant.

    Optimization: read only the last 64 KB of the session file first (the verdict
    is always near the end). Falls back to full parse only if tail search fails.
    """
    session_path = Path(agent.session_path)
    if not session_path.is_file():
        return None
    # Try tail-read first (fast path)
    _TAIL_SIZE = 65_536
    try:
        file_size = session_path.stat().st_size
        if file_size > 0:
            with open(session_path, "rb") as f:
                offset = max(0, file_size - _TAIL_SIZE)
                f.seek(offset)
                tail = f.read().decode("utf-8", errors="replace")
            match = _VERDICT_RE.search(tail)
            if match:
                return match.group(1).upper()
            # If file was fully read (small file), no point in fallback
            if offset == 0:
                return None
    except OSError:
        pass
    # Fallback: full structured parse
    data = store.load_session_json(session_path) or {}
    for message in reversed(data.get("messages", [])):
        for text in _verdict_texts(message):
            match = _VERDICT_RE.search(text)
            if match:
                return match.group(1).upper()
    return None


def _attach_run_state(run: dict) -> None:
    agent = runner.load_agent(run["agent_id"])
    run["state"] = store.agent_status(agent)["state"] if agent else "disparu"
    run["key"] = f"agent/{run['agent_id']}"


def refresh_verdicts(slug: str, tickets: list[dict]) -> None:
    """Complète l'état live des runs et parse les verdicts des validations terminées."""
    changed = False
    for ticket in tickets:
        for run in ticket["runs"]:
            _attach_run_state(run)
            needs_verdict = run["kind"].startswith("validate") and run.get("verdict") is None
            if needs_verdict and run["state"] == "finished":
                agent = runner.load_agent(run["agent_id"])
                verdict = _find_verdict(agent) if agent else None
                if verdict:
                    run["verdict"] = verdict
                    changed = True
    if changed:
        stripped = [
            {**t, "runs": [{k: v for k, v in r.items() if k not in ("state", "key")}
                           for r in t["runs"]]}
            for t in tickets
        ]
        _save(slug, stripped)


def list_tickets(slug: str, refresh: bool = False) -> list[dict]:
    tickets = _load(slug)
    if refresh:
        refresh_verdicts(slug, tickets)
    return tickets


def derive_status(ticket: dict) -> str:
    if ticket.get("done"):
        return "terminé"
    runs = ticket["runs"]
    if any(run.get("state") in ("running", "awaiting_input") for run in runs):
        return "en cours"
    verdicts = [r.get("verdict") for r in runs if r["kind"].startswith("validate")]
    if verdicts and all(v == "OK" for v in verdicts):
        return "validé"
    if any(run["kind"] == "work" for run in runs):
        return "à relire"
    return "à faire"
