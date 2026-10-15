# [desc] La table `decisions` : un arbitraire qui survit à son agent. Invariants I1-I4 du §4.2.
"""Aucun store neuf : la table vit dans la base SQLite des tickets (`_persistence._db_path()`),
comme `tasks`. Le chemin est ré-dérivé à chaque transaction — ne JAMAIS le mémoriser, c'est ce
qui rend l'isolation des tests gratuite.

Les quatre invariants sont tenus ICI, pas chez l'appelant :
- I1 une décision survit à son agent  -> `make_moot()` marque, n'efface jamais ;
- I2 pas de doublon                   -> `dedup_key` UNIQUE + upsert en UPDATE ;
- I3 un échec de délivrance est visible-> `mark_delivery()` garde le code d'erreur textuel ;
- I4 répondre est idempotent          -> `answer()` rend `already_answered` sans rien toucher.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager

from bouzecode.web_v2.services.horodatage import heure_locale, maintenant_iso

from . import _persistence
from ._store_connection import transaction

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS decisions (
      id             TEXT PRIMARY KEY,
      task_id        TEXT NOT NULL DEFAULT '',
      source         TEXT NOT NULL,
      situation      TEXT NOT NULL DEFAULT '',
      project_slug   TEXT NOT NULL DEFAULT '',
      ticket_id      TEXT NOT NULL DEFAULT '',
      agent_id       TEXT NOT NULL DEFAULT '',
      question       TEXT NOT NULL,
      context        TEXT NOT NULL DEFAULT '',
      options        TEXT NOT NULL DEFAULT '[]',
      allow_freetext INTEGER NOT NULL DEFAULT 1,
      recommended    TEXT NOT NULL DEFAULT '',
      bloque         TEXT NOT NULL DEFAULT '',
      reversible     TEXT NOT NULL DEFAULT '',
      defaut_si_silence TEXT NOT NULL DEFAULT '',
      urgency        INTEGER NOT NULL DEFAULT 2,
      asked_at       TEXT NOT NULL,
      answered_at    TEXT NOT NULL DEFAULT '',
      answer_key     TEXT NOT NULL DEFAULT '',
      answer_text    TEXT NOT NULL DEFAULT '',
      delivery       TEXT NOT NULL DEFAULT 'pending',
      delivery_error TEXT NOT NULL DEFAULT '',
      attempts       INTEGER NOT NULL DEFAULT 0,
      dedup_key      TEXT NOT NULL UNIQUE
    )""",
    "CREATE INDEX IF NOT EXISTS decisions_open ON decisions (answered_at, urgency, asked_at)",
    # Questions d'agents ARRÊTÉS classées sans réponse par l'humain : la clé (agent, date de la
    # question) fait qu'une NOUVELLE question du même agent réapparaît normalement.
    """CREATE TABLE IF NOT EXISTS question_archives (
      agent_id    TEXT NOT NULL,
      asked_at    TEXT NOT NULL DEFAULT '',
      comment     TEXT NOT NULL DEFAULT '',
      archived_at TEXT NOT NULL,
      PRIMARY KEY (agent_id, asked_at)
    )""",
)

# Champs qu'un nouveau tick a le droit de rafraîchir sur une décision déjà connue.
VOLATILE = ("task_id", "source", "project_slug", "agent_id", "question", "context",
            "options", "allow_freetext", "recommended", "urgency",
            "bloque", "reversible", "defaut_si_silence")

# Colonnes ajoutées après coup : une base déjà créée ne les a pas, et SQLite ne sait pas
# faire `ADD COLUMN IF NOT EXISTS` — la migration se fait donc à l'ouverture (voir `_migrate`).
AJOUTS = (("bloque", "TEXT NOT NULL DEFAULT ''"),
          ("reversible", "TEXT NOT NULL DEFAULT ''"),
          ("defaut_si_silence", "TEXT NOT NULL DEFAULT ''"))


def _now() -> str:
    return maintenant_iso()


@contextmanager
def _tx():
    """Transaction sur la base des tickets, schéma des décisions garanti présent.

    Les `CREATE ... IF NOT EXISTS` sont rejoués à chaque bloc : sans écriture quand la table
    existe déjà, et sans drapeau « déjà migré » de process qui mentirait dès que la base change
    sous les pieds."""
    path = _persistence._db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with transaction(path) as conn:
        for statement in SCHEMA:
            conn.execute(statement)
        _migrate(conn)
        yield conn


def _migrate(conn) -> None:
    """Ajoute les colonnes apparues après coup sur une base DÉJÀ créée.

    SQLite ne sait pas faire `ADD COLUMN IF NOT EXISTS` : sans ce rattrapage, la base du
    serveur garderait l'ancienne table et le premier `INSERT` nommant `bloque` casserait.
    On lit les colonnes réelles plutôt que de tenir un drapeau « déjà migré » qui mentirait
    dès que la base change sous les pieds."""
    presentes = {ligne[1] for ligne in conn.execute("PRAGMA table_info(decisions)")}
    for nom, declaration in AJOUTS:
        if nom not in presentes:
            conn.execute(f"ALTER TABLE decisions ADD COLUMN {nom} {declaration}")


def _rows(cursor: sqlite3.Cursor) -> list[dict]:
    columns = [column[0] for column in cursor.description]
    return [_decode(dict(zip(columns, row))) for row in cursor.fetchall()]


def _liste_brute(raw) -> list:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "[]")
        except (TypeError, ValueError):
            return []
    return raw if isinstance(raw, list) else []


def _option(brut) -> dict | None:
    if isinstance(brut, dict):
        cle = str(brut.get("key") or brut.get("label") or "").strip()
        libelle = str(brut.get("label") or cle).strip()
        suite = str(brut.get("consequence") or "").strip()
    else:
        cle = libelle = str(brut).strip()
        suite = ""
    if not (cle or libelle):
        return None
    return {"key": cle or libelle, "label": libelle or cle, "consequence": suite}


def _options(raw) -> list[dict]:
    """Une option porte TOUJOURS `key`, `label` ET `consequence`.

    Le Bureau doit pouvoir afficher « ce qui se passe si je clique ici » sans deviner : un
    libellé nu (ancienne carte en base, ou question posée par un agent) est donc remonté en
    option structurée à conséquence VIDE — visible comme un manque, jamais silencieusement
    perdu."""
    return [o for o in map(_option, _liste_brute(raw)) if o is not None]


def _manque(row: dict) -> list[str]:
    """Ce que l'agent n'a PAS dit, dans l'ordre où ça manque pour décider (I4).

    Une carte incomplète n'est jamais refusée : la refuser ferait DISPARAÎTRE la question
    d'un agent, donc du reste-à-faire. Elle est gardée et signalée."""
    options = row.get("options") or []
    absents: list[str] = []
    if not str(row.get("question") or "").strip():
        absents.append("question")
    if not options and not row.get("allow_freetext"):
        absents.append("options")
    if options and any(not option.get("consequence") for option in options):
        absents.append("consequence")
    if not str(row.get("recommended") or "").strip():
        absents.append("recommended")
    for champ in ("bloque", "reversible", "defaut_si_silence"):
        if not str(row.get(champ) or "").strip():
            absents.append(champ)
    return absents


def _decode(row: dict) -> dict:
    """`options` est stocké en JSON : le lecteur reçoit des options structurées, jamais du
    texte, plus le verdict d'autoportance (`manque` / `complete`)."""
    row["options"] = _options(row.get("options"))
    row["allow_freetext"] = bool(row.get("allow_freetext", 1))
    for champ in ("bloque", "reversible", "defaut_si_silence"):
        row[champ] = str(row.get(champ) or "")
    row["manque"] = _manque(row)
    row["complete"] = not row["manque"]
    return row


def dedup_key(situation: str, ticket_id: str = "", agent_id: str = "",
              asked_at: str = "", bucket: str | None = None) -> str:
    """Identité d'une décision (I2). `bucket` par défaut = la MINUTE de `asked_at` : une
    question d'agent porte un `asked_at` stable, donc le même bucket à chaque tick.
    Les situations dérivées d'un état (uncommitted, launch_failed…) passent `bucket=""` :
    leur `asked_at` bougerait à chaque tick et ferait un doublon par tick.

    La minute est lue en heure LOCALE quelle que soit la forme écrite : les clés déjà en base
    ont été calculées sur des `asked_at` locaux ; un `asked_at` désormais écrit en UTC doit
    retomber sur la même clé, sinon chaque question ouverte renaîtrait en doublon."""
    if bucket is None:
        bucket = heure_locale(asked_at, "%Y-%m-%dT%H:%M") or (asked_at or "")[:16]
    return "|".join((situation or "", ticket_id or "", agent_id or "", bucket))


def upsert(source: str, situation: str, question: str, *, asked_at: str = "",
           task_id: str = "", project_slug: str = "", ticket_id: str = "",
           agent_id: str = "", context: str = "", options: list | None = None,
           allow_freetext: bool = True, recommended: str = "",
           bloque: str = "", reversible: str = "", defaut_si_silence: str = "",
           urgency: int = 2, bucket: str | None = None) -> dict:
    """Écrit la décision, ou rafraîchit celle qui porte la même `dedup_key` (I2).

    Une décision DÉJÀ RÉPONDUE n'est jamais réécrite par un tick (clause WHERE). Une décision
    `moot` dont la question revient (agent ressuscité) repasse `pending`."""
    asked_at = asked_at or _now()
    key = dedup_key(situation, ticket_id, agent_id, asked_at, bucket)
    values = {
        "id": uuid.uuid4().hex[:12], "task_id": task_id, "source": source,
        "situation": situation, "project_slug": project_slug, "ticket_id": ticket_id,
        "agent_id": agent_id, "question": question, "context": context,
        "options": json.dumps(_options(options), ensure_ascii=False),
        "allow_freetext": 1 if allow_freetext else 0, "recommended": recommended,
        "bloque": bloque, "reversible": reversible,
        "defaut_si_silence": defaut_si_silence,
        "urgency": int(urgency), "asked_at": asked_at, "dedup_key": key,
    }
    columns = ", ".join(values)
    placeholders = ", ".join(f":{name}" for name in values)
    refresh = ", ".join(f"{name} = excluded.{name}" for name in VOLATILE)
    with _tx() as conn:
        conn.execute(
            f"INSERT INTO decisions ({columns}) VALUES ({placeholders}) "
            f"ON CONFLICT(dedup_key) DO UPDATE SET {refresh}, "
            "delivery = CASE WHEN decisions.delivery = 'moot' THEN 'pending' "
            "ELSE decisions.delivery END, "
            "delivery_error = CASE WHEN decisions.delivery = 'moot' THEN '' "
            "ELSE decisions.delivery_error END "
            "WHERE decisions.answered_at = ''",
            values,
        )
        found = _rows(conn.execute("SELECT * FROM decisions WHERE dedup_key = ?", (key,)))
    row = found[0] if found else _decode(dict(values))
    row["created"] = row.get("id") == values["id"]
    return row


def get(decision_id: str) -> dict | None:
    with _tx() as conn:
        found = _rows(conn.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,)))
    return found[0] if found else None


def open_decisions(limit: int = 200) -> list[dict]:
    """Ce qui attend un arbitrage : non répondu et non caduc, urgence puis ancienneté (§5)."""
    with _tx() as conn:
        return _rows(conn.execute(
            "SELECT * FROM decisions WHERE answered_at = '' AND delivery != 'moot' "
            "ORDER BY urgency ASC, asked_at ASC LIMIT ?", (limit,)))


def failed_deliveries(limit: int = 50) -> list[dict]:
    """I3 : répondu mais jamais délivré — ça reste VISIBLE, et rejouable."""
    with _tx() as conn:
        return _rows(conn.execute(
            "SELECT * FROM decisions WHERE delivery = 'failed' "
            "ORDER BY answered_at ASC LIMIT ?", (limit,)))


def pending_for_retry(max_attempts: int = 5, limit: int = 20) -> list[dict]:
    """Réponses écrites, délivrance encore en attente : à rejouer au tick."""
    with _tx() as conn:
        return _rows(conn.execute(
            "SELECT * FROM decisions WHERE answered_at != '' AND delivery = 'pending' "
            "AND attempts < ? ORDER BY answered_at ASC LIMIT ?", (max_attempts, limit)))


def count_open_by_task() -> dict[str, int]:
    """Une seule requête pour tout le board : {task_id: nb décisions ouvertes}."""
    with _tx() as conn:
        rows = conn.execute(
            "SELECT task_id, COUNT(*) FROM decisions WHERE answered_at = '' "
            "AND delivery != 'moot' AND task_id != '' GROUP BY task_id").fetchall()
    return {row[0]: int(row[1]) for row in rows}


def answer(decision_id: str, answer_key: str = "", answer_text: str = "") -> dict:
    """I4 : écrit la réponse UNE fois. Une seconde réponse rend `already_answered` et ne
    touche rien — c'est ce qui empêche deux POST de relancer deux tours d'agent.

    La réponse est écrite AVANT toute tentative de délivrance : l'ordre inverse perd la
    réponse quand la délivrance échoue."""
    with _tx() as conn:
        found = _rows(conn.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,)))
        if not found:
            return {"status": "not_found", "decision": None}
        if found[0]["answered_at"]:
            return {"status": "already_answered", "decision": found[0]}
        conn.execute(
            "UPDATE decisions SET answered_at = ?, answer_key = ?, answer_text = ?, "
            "delivery = 'pending', delivery_error = '' WHERE id = ?",
            (_now(), answer_key, answer_text, decision_id))
        fresh = _rows(conn.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,)))
    return {"status": "ok", "decision": fresh[0]}


def mark_delivery(decision_id: str, state: str, error: str = "",
                  bump_attempt: bool = False) -> dict | None:
    """I3 : `error` est le code rendu par `messaging` (agent_missing / not_delivered /
    running), conservé TEXTUELLEMENT — c'est la preuve montrée à l'utilisateur."""
    with _tx() as conn:
        conn.execute(
            "UPDATE decisions SET delivery = ?, delivery_error = ?, "
            "attempts = attempts + ? WHERE id = ?",
            (state, error, 1 if bump_attempt else 0, decision_id))
        found = _rows(conn.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,)))
    return found[0] if found else None


def make_moot(decision_id: str, trace: str) -> dict | None:
    """I1 : la mort de l'agent ne SUPPRIME pas la question, elle la rend caduque avec sa trace."""
    return mark_delivery(decision_id, "moot", trace)


def archive_question(agent_id: str, asked_at: str, comment: str = "") -> dict:
    """Classe SANS réponse la question en attente d'un agent arrêté (geste humain).

    La question sort de « À traiter » (filtre de `awaiting`), et les cartes de décision encore
    ouvertes de cet agent deviennent `moot` avec le commentaire en trace : rien n'est supprimé,
    aucun agent n'a à consommer de réponse. Idempotent (un double-clic rafraîchit le commentaire)."""
    now = _now()
    trace = "classée sans réponse depuis le Bureau" + (f" : {comment}" if comment else "")
    with _tx() as conn:
        conn.execute(
            "INSERT INTO question_archives (agent_id, asked_at, comment, archived_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(agent_id, asked_at) DO UPDATE SET "
            "comment = excluded.comment, archived_at = excluded.archived_at",
            (agent_id, asked_at or "", comment or "", now))
        conn.execute(
            "UPDATE decisions SET delivery = 'moot', delivery_error = ? "
            "WHERE agent_id = ? AND answered_at = '' AND delivery != 'moot'",
            (trace, agent_id))
    return {"agent_id": agent_id, "asked_at": asked_at or "", "comment": comment or "",
            "archived_at": now}


def archived_questions() -> set[tuple[str, str]]:
    """Les (agent_id, asked_at) classés sans réponse."""
    with _tx() as conn:
        return {(str(agent_id), str(asked_at)) for agent_id, asked_at in conn.execute(
            "SELECT agent_id, asked_at FROM question_archives")}


def close_other_duplicates(situation: str, ticket_id: str, agent_id: str,
                           keep_key: str, trace: str) -> int:
    """Ferme les SOSIES d'une décision : même (situation, ticket_id, agent_id), clé
    d'identité DIFFÉRENTE de `keep_key`. Rend le nombre de cartes fermées.

    Pourquoi : la clé d'une question d'agent a longtemps porté la MINUTE de `asked_at`
    (cf. `dedup_key`). Quand cette minute bougeait d'un tick à l'autre, chaque tick
    créait une carte de plus — le board a montré la même question 2 fois pendant des
    jours. Stabiliser la clé ne suffit pas : les lignes déjà écrites gardent leurs
    vieilles clés, il faut donc les fermer explicitement. `delivery='moot'` suffit,
    `open_decisions` l'exclut déjà."""
    with _tx() as conn:
        cursor = conn.execute(
            "UPDATE decisions SET delivery = 'moot', delivery_error = ? "
            "WHERE situation = ? AND ticket_id = ? AND agent_id = ? "
            "AND dedup_key != ? AND answered_at = '' AND delivery != 'moot'",
            (trace, situation, ticket_id, agent_id, keep_key))
        return int(cursor.rowcount or 0)


def make_moot_where(situation: str, ticket_id: str, trace: str) -> int:
    """Même geste, en lot : toutes les décisions ouvertes d'un ticket pour une situation."""
    with _tx() as conn:
        cursor = conn.execute(
            "UPDATE decisions SET delivery = 'moot', delivery_error = ? "
            "WHERE situation = ? AND ticket_id = ? AND answered_at = '' "
            "AND delivery != 'moot'", (trace, situation, ticket_id))
        return int(cursor.rowcount or 0)
