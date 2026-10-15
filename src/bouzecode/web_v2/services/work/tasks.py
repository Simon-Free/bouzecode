# [desc] Les tâches du Bureau : créer, lister, lier un ticket, journaliser. Même base que les tickets.
"""Aucun nouveau store, aucun nouveau fichier de base : les trois tables vivent dans la base
SQLite des tickets (`_persistence._db_path()`), ouverte par la connexion thread-local existante.
`_db_path()` est dérivé de `TICKETS_DIR` à chaque appel, donc l'isolation des tests s'applique
gratuitement — ne JAMAIS mémoriser le chemin dans une constante de module."""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager

from bouzecode.web_v2.services.horodatage import maintenant_iso

from . import _persistence
from ._store_connection import transaction
from ._task_state import derive_task_state  # noqa: F401 — ré-export pour les appelants

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS tasks (
      id            TEXT PRIMARY KEY,
      title         TEXT NOT NULL,
      intent        TEXT NOT NULL DEFAULT '',
      project_slug  TEXT NOT NULL DEFAULT '',
      owner         TEXT NOT NULL DEFAULT 'agent',
      policy        TEXT NOT NULL DEFAULT 'observer',
      state         TEXT NOT NULL DEFAULT 'a_faire',
      next_step     TEXT NOT NULL DEFAULT '',
      snoozed_until TEXT NOT NULL DEFAULT '',
      note_anchor   TEXT NOT NULL DEFAULT '',
      created_at    TEXT NOT NULL,
      updated_at    TEXT NOT NULL,
      closed_at     TEXT NOT NULL DEFAULT '',
      outcome       TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE IF NOT EXISTS task_tickets (
      task_id TEXT NOT NULL, slug TEXT NOT NULL, ticket_id TEXT NOT NULL,
      role    TEXT NOT NULL DEFAULT 'work',
      PRIMARY KEY (task_id, slug, ticket_id)
    )""",
    """CREATE TABLE IF NOT EXISTS task_events (
      id      INTEGER PRIMARY KEY AUTOINCREMENT,
      task_id TEXT NOT NULL, at TEXT NOT NULL,
      actor   TEXT NOT NULL, kind TEXT NOT NULL, label TEXT NOT NULL,
      why     TEXT NOT NULL DEFAULT '', result TEXT NOT NULL DEFAULT ''
    )""",
)

WRITABLE = ("title", "intent", "project_slug", "owner", "policy",
            "state", "next_step", "snoozed_until", "note_anchor")


def _now() -> str:
    return maintenant_iso()


@contextmanager
def _tx():
    """Transaction sur la base des tickets, schéma des tâches garanti présent.

    Les `CREATE TABLE IF NOT EXISTS` sont rejoués à chaque bloc : c'est une opération sans
    écriture quand les tables existent, et ça évite un drapeau « déjà migré » de process — le
    genre de souvenir qui ment dès que la base change sous les pieds (cf. `_persistence._migrated`)."""
    path = _persistence._db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with transaction(path) as conn:
        for statement in SCHEMA:
            conn.execute(statement)
        yield conn


def _rows(cursor: sqlite3.Cursor) -> list[dict]:
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def create_task(title: str, intent: str = "", project_slug: str = "",
                owner: str = "agent", policy: str = "observer",
                note_anchor: str = "") -> dict:
    """Crée une tâche et l'événement de création. Ne dispatche RIEN (hors lot L0)."""
    task_id = uuid.uuid4().hex[:8]
    now = _now()
    with _tx() as conn:
        conn.execute(
            "INSERT INTO tasks (id, title, intent, project_slug, owner, policy, state,"
            " note_anchor, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (task_id, title.strip(), intent, project_slug, owner, policy,
             "a_faire", note_anchor, now, now),
        )
    add_event(task_id, actor="moi", kind="note", label="tâche créée")
    return get_task(task_id) or {}


def get_task(task_id: str) -> dict | None:
    with _tx() as conn:
        found = _rows(conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)))
    return found[0] if found else None


def count_closed_tasks() -> int:
    """Combien de tâches sont closes — sans en charger AUCUNE.

    C'est ce qui rend le compteur « N tâches closes » gratuit pour le board : un COUNT, pas une
    liste. Les tâches closes ne sont lues que si l'utilisateur clique (`include_closed=True`)."""
    with _tx() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM tasks WHERE closed_at <> ''").fetchone()[0])


def list_tasks(include_closed: bool = False) -> list[dict]:
    query = "SELECT * FROM tasks"
    if not include_closed:
        query += " WHERE closed_at = ''"
    query += " ORDER BY created_at DESC, id DESC"
    with _tx() as conn:
        return _rows(conn.execute(query))


def update_task(task_id: str, **fields) -> dict | None:
    """N'écrit que les colonnes de `WRITABLE`, et REFUSE bruyamment le reste.

    Un champ inconnu lève `ValueError` : l'ignorer en silence, c'est perdre une écriture sans
    que l'appelant l'apprenne. Aucun risque côté HTTP, la route PATCH filtre déjà en amont.
    """
    refused = sorted(key for key in fields if key not in WRITABLE)
    if refused:
        raise ValueError(f"champs non modifiables : {', '.join(refused)}")
    changes = {key: value for key, value in fields.items() if value is not None}
    if not changes:
        return get_task(task_id)
    assignments = ", ".join(f"{key} = ?" for key in changes)
    with _tx() as conn:
        conn.execute(f"UPDATE tasks SET {assignments}, updated_at = ? WHERE id = ?",
                     (*changes.values(), _now(), task_id))
    return get_task(task_id)


def close_task(task_id: str, outcome: str = "fait") -> dict | None:
    now = _now()
    state = "fait" if outcome == "fait" else "abandonnee"
    with _tx() as conn:
        conn.execute(
            "UPDATE tasks SET state = ?, outcome = ?, closed_at = ?, updated_at = ? WHERE id = ?",
            (state, outcome, now, now, task_id),
        )
    add_event(task_id, actor="moi", kind="state", label=f"clôturée : {outcome}")
    return get_task(task_id)


def link_ticket(task_id: str, slug: str, ticket_id: str, role: str = "work") -> None:
    with _tx() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO task_tickets (task_id, slug, ticket_id, role) VALUES (?,?,?,?)",
            (task_id, slug, ticket_id, role),
        )


def links_of(task_id: str) -> list[dict]:
    with _tx() as conn:
        return _rows(conn.execute(
            "SELECT task_id, slug, ticket_id, role FROM task_tickets WHERE task_id = ?", (task_id,)))


def all_links() -> list[dict]:
    """TOUS les liens en UNE requête : le board ne doit pas faire un SELECT par tâche."""
    with _tx() as conn:
        return _rows(conn.execute("SELECT task_id, slug, ticket_id, role FROM task_tickets"))


def add_event(task_id: str, actor: str, kind: str, label: str,
              why: str = "", result: str = "", at: str | None = None) -> None:
    """Ajoute un évènement à la tâche.

    `at` est PARAMÉTRABLE (ISO 8601) : sans lui, aucun test ne peut fabriquer un historique —
    or c'est la FRAÎCHEUR de cet évènement qui décide si une tâche « tourne » encore ou si elle
    est figée. Une règle de fraîcheur qu'on ne peut pas prouver est une règle qui mentira.
    En production l'argument reste omis, donc l'horodatage reste celui du serveur.
    """
    with _tx() as conn:
        conn.execute(
            "INSERT INTO task_events (task_id, at, actor, kind, label, why, result)"
            " VALUES (?,?,?,?,?,?,?)",
            (task_id, at or _now(), actor, kind, label, why, result),
        )


def events_of(task_id: str, limit: int = 20) -> list[dict]:
    with _tx() as conn:
        return _rows(conn.execute(
            "SELECT * FROM task_events WHERE task_id = ? ORDER BY id DESC LIMIT ?",
            (task_id, limit)))


def last_event_by_task() -> dict[str, dict]:
    """Le dernier événement de CHAQUE tâche, en une requête (pour le board)."""
    with _tx() as conn:
        rows = _rows(conn.execute("SELECT * FROM task_events ORDER BY id ASC"))
    return {row["task_id"]: row for row in rows}
