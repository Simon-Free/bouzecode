# [desc] Signalements NON BLOQUANTS des agents (outil Signaler) : store SQLite, lecture pour l'inbox / Flotte, acquittement, digest pour les ancetres au prochain reveil. [/desc]
"""Un agent, a n'importe quelle profondeur, fait remonter un probleme SANS s'arreter.

`AskUserQuestion` met le tour en pause : c'est pour un agent BLOQUE. `Signaler` est l'autre
moitie : « l'humain doit le savoir, mais je continue ». Le signalement est persiste ici (base
des tickets, table `signalements`) avec l'agent, sa chaine de parents, sa profondeur, son
ticket et sa tache ; il apparait dans « A traiter » (`inbox_signalements`), dans l'outil
`Flotte` de l'assistant, et chaque ANCETRE le recoit une fois dans le digest de son prochain
reveil (`digest_pour`). L'humain l'acquitte (`POST /api/signalements/<id>/acquitter`).
"""
from __future__ import annotations

import json
import uuid

from bouzecode.web_v2.services.horodatage import maintenant_iso

from . import _persistence
from ._store_connection import transaction

GRAVITES = ("info", "alerte", "bloquant")
#: Urgence dans « A traiter » (0 = le plus urgent, cf. `inbox.URGENCE`).
URGENCE = {"bloquant": 0, "alerte": 1, "info": 2}

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS signalements ("
    " id TEXT PRIMARY KEY, created_at TEXT NOT NULL, gravite TEXT NOT NULL,"
    " titre TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', action_attendue TEXT NOT NULL"
    " DEFAULT '', agent_id TEXT NOT NULL DEFAULT '', ticket_slug TEXT NOT NULL DEFAULT '',"
    " ticket_id TEXT NOT NULL DEFAULT '', parents TEXT NOT NULL DEFAULT '[]',"
    " acquitte_at TEXT NOT NULL DEFAULT '')",
    "CREATE TABLE IF NOT EXISTS signalement_notifications ("
    " signalement_id TEXT NOT NULL, parent_id TEXT NOT NULL, at TEXT NOT NULL,"
    " PRIMARY KEY (signalement_id, parent_id))",
)


def _maintenant() -> str:
    return maintenant_iso()


def _tx():
    chemin = _persistence._db_path()
    chemin.parent.mkdir(parents=True, exist_ok=True)
    return transaction(chemin)


def _lignes(requete: str, valeurs: tuple = ()) -> list[dict]:
    with _tx() as conn:
        for instruction in _SCHEMA:
            conn.execute(instruction)
        curseur = conn.execute(requete, valeurs)
        colonnes = [c[0] for c in curseur.description]
        return [_vue(dict(zip(colonnes, ligne))) for ligne in curseur.fetchall()]


def _vue(ligne: dict) -> dict:
    ligne["parents"] = json.loads(ligne.get("parents") or "[]")
    ligne["profondeur"] = len(ligne["parents"])
    return ligne


def _invalider_les_vues() -> None:
    from . import taches_vue
    taches_vue.invalider()


def creer(gravite: str, titre: str, detail: str = "", action_attendue: str = "",
          agent_id: str = "", parents: list[str] | None = None, ticket_slug: str = "",
          ticket_id: str = "") -> dict:
    """Enregistre un signalement ; `ValueError` sur une gravite inconnue ou un titre vide."""
    gravite = str(gravite or "").strip().lower()
    if gravite not in GRAVITES:
        raise ValueError(f"gravite inconnue : {gravite!r} (attendu : {', '.join(GRAVITES)})")
    if not str(titre or "").strip():
        raise ValueError("titre vide : dis en une ligne ce que l'humain doit savoir")
    ident = uuid.uuid4().hex[:10]
    with _tx() as conn:
        for instruction in _SCHEMA:
            conn.execute(instruction)
        conn.execute(
            "INSERT INTO signalements (id, created_at, gravite, titre, detail, action_attendue,"
            " agent_id, ticket_slug, ticket_id, parents) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ident, _maintenant(), gravite, str(titre).strip(), str(detail or ""),
             str(action_attendue or ""), agent_id, ticket_slug, ticket_id,
             json.dumps(list(parents or []))))
    _invalider_les_vues()
    return get(ident)


def get(ident: str) -> dict | None:
    lignes = _lignes("SELECT * FROM signalements WHERE id = ?", (ident,))
    return lignes[0] if lignes else None


def ouverts() -> list[dict]:
    """Les signalements non acquittes, du plus recent au plus ancien."""
    return _lignes("SELECT * FROM signalements WHERE acquitte_at = '' ORDER BY created_at DESC")


def de_la_lignee(ancetre: str) -> list[dict]:
    """Signalements ouverts emis par un descendant (a toute profondeur) de `ancetre`."""
    return [s for s in ouverts() if ancetre and ancetre in s["parents"]]


def acquitter(ident: str) -> dict | None:
    if get(ident) is None:
        return None
    with _tx() as conn:
        conn.execute("UPDATE signalements SET acquitte_at = ? WHERE id = ? AND acquitte_at = ''",
                     (_maintenant(), ident))
    _invalider_les_vues()
    return get(ident)


def _deja_notifies(parent_id: str) -> set[str]:
    with _tx() as conn:
        for instruction in _SCHEMA:
            conn.execute(instruction)
        return {r[0] for r in conn.execute(
            "SELECT signalement_id FROM signalement_notifications WHERE parent_id = ?",
            (parent_id,)).fetchall()}


def digest_pour(parent_id: str) -> str:
    """Les signalements de sa lignee que ce parent n'a pas encore recus, en texte a ajouter a
    son message de reveil ; notes comme recus. "" s'il n'y en a aucun."""
    deja = _deja_notifies(parent_id)
    nouveaux = [s for s in de_la_lignee(parent_id) if s["id"] not in deja]
    if not nouveaux:
        return ""
    with _tx() as conn:
        conn.executemany("INSERT OR IGNORE INTO signalement_notifications VALUES (?, ?, ?)",
                         [(s["id"], parent_id, _maintenant()) for s in nouveaux])
    lignes = ["", "Signalements de ta lignee (non bloquants, deja visibles par l'humain) :"]
    for s in nouveaux:
        action = f" — attendu : {s['action_attendue']}" if s["action_attendue"] else ""
        lignes.append(f"- [{s['gravite']}] {s['titre']} (agent {s['agent_id']}, profondeur "
                      f"{s['profondeur']}, ticket {s['ticket_id'] or '-'}){action}")
    lignes.append("Tiens-en compte ; si tu peux le regler toi-meme, fais-le.")
    return "\n".join(lignes)
