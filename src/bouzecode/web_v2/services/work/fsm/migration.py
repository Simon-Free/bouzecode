# [desc] Migration du store au lot L2, idempotente et sûre à deux serveurs : runs du JSON → table `runs`, drapeaux → `state` + `state_reason`, anciens champs gardés sous `legacy`. [/desc]
"""Une base d'avant le lot L2 porte ses runs DANS le JSON de chaque ticket et son état dans une
dizaine de drapeaux. Cette migration, jouée au boot (`migrations.migrer_le_store`) :

  1. sort les runs du JSON vers la table `runs` (un `agent_id` répété dans un même ticket
     garde son occurrence la plus récente ; un `agent_id` déjà pris par un autre ticket reste
     dans `legacy.runs` : rien n'est perdu) ;
  2. calcule `state` / `state_reason` par la table `correspondance.etat_initial`, affinée par
     `affiner` pour un run resté ouvert (le boot y lit le vrai process) ;
  3. range les anciens drapeaux sous `legacy` (aucune donnée supprimée), convertit
     `worktree.state` retiré en `worktree.retire_at`, et la demande d'arrêt en événement ;
  4. journalise un événement `migration_l2` par ticket.

IDEMPOTENTE (un ticket qui a déjà un `state` et plus de `runs` dans son JSON n'est pas
retouché ; la date de la dernière passe utile est notée dans `store_migrations`) et SÛRE À DEUX
SERVEURS : toute la passe tient dans UNE transaction `BEGIN IMMEDIATE` — le second serveur
attend le verrou d'écriture de SQLite, puis ne trouve plus rien à migrer."""
from __future__ import annotations

import json
import sqlite3
from typing import Callable

from bouzecode.web_v2.services.horodatage import maintenant_iso

from . import correspondance, etats, journal, stockage

NOM = "l2_etat_unique"
#: Anciens drapeaux rangés sous `legacy` (ils ne pilotent plus rien).
DRAPEAUX = ("done", "crashed", "reaped", "launching", "launch_failed", "awaiting_reply",
            "closure_blocked", "closure_forced", "uncommitted", "recolte_bloquee",
            "arret_demande", "closed", "chain_removed_migrated", "gate_failed_cap")
_TRANSITOIRES_DE_RUN = ("state", "key", "pid_alive")

Affineur = Callable[[dict, dict], tuple[str, dict | None] | None]


def _maintenant() -> str:
    return maintenant_iso()


def _runs_dedoublonnes(runs: list) -> list[dict]:
    """Récent en tête ; un agent_id répété ne garde que son occurrence la plus récente."""
    vus, gardes = set(), []
    for run in runs:
        if isinstance(run, dict) and run.get("agent_id") and run["agent_id"] not in vus:
            vus.add(run["agent_id"])
            gardes.append(run)
    return gardes


def _etat_des_runs(state: str, runs: list[dict]) -> list[dict]:
    """Le plus récent run d'un ticket en vol reste ouvert ; tous les autres sont terminés."""
    sortie = []
    for rang, run in enumerate(runs):
        propre = {k: v for k, v in run.items() if k not in _TRANSITOIRES_DE_RUN}
        if rang == 0 and state in (etats.RUNNING, etats.AWAITING_INPUT):
            propre["state"] = state
        else:
            propre["state"] = "ended"
            propre["end"] = {"reason": "migration", "delivered": bool(run.get("completed")),
                             "final_answer": False, "returncode": None}
        propre["seq"] = len(runs) - rang
        sortie.append(propre)
    return sortie


def _worktree(meta, legacy: dict):
    if not isinstance(meta, dict) or "state" not in meta:
        return meta
    meta = dict(meta)
    legacy["worktree_state"] = meta.pop("state")
    if legacy["worktree_state"] in ("cleaned", "removed") and not meta.get("retire_at"):
        meta["retire_at"] = meta.get("integrated_at") or _maintenant()
    if legacy["worktree_state"] in ("integrated", "cleaned"):
        legacy["integration"] = {"merged_at": meta.get("integrated_at") or ""}
    return meta


def _a_affiner(data: dict) -> tuple[dict, dict] | None:
    """(vue, run ouvert) d'un ticket ancien que la correspondance dit en vol, sinon None."""
    runs = _runs_dedoublonnes(data.get("runs") or [])
    if not runs or correspondance.etat_initial({**data, "runs": runs})[0] not in (
            etats.RUNNING, etats.AWAITING_INPUT):
        return None
    return {**data, "runs": runs}, runs[0]


def _migrer_un(conn, slug: str, data: dict, affinage: tuple | None) -> None:
    runs_json = data.pop("runs", None) or []
    runs = _runs_dedoublonnes(runs_json)
    legacy = {k: data.pop(k) for k in DRAPEAUX if k in data}
    for doublon in [r for r in runs_json if isinstance(r, dict) and r not in runs]:
        legacy.setdefault("runs", []).append(doublon)
    state, raison = affinage or correspondance.etat_initial({**data, **legacy, "runs": runs})
    data["worktree"] = _worktree(data.get("worktree"), legacy)
    if legacy.get("integration"):
        data.setdefault("integration", legacy["integration"])
    data.update(state=state, state_reason=raison, **({"legacy": legacy} if legacy else {}))
    for run in _etat_des_runs(state, runs):
        if stockage._proprietaire(conn, run["agent_id"]) is None:
            stockage.inserer(conn, slug, data["id"], run)
        else:
            legacy.setdefault("runs", []).append(run)
    if isinstance(legacy.get("arret_demande"), dict):
        journal.ecrire(conn, slug, data["id"], journal.ARRET_DEMANDE, "migration",
                       legacy["arret_demande"], at=str(legacy["arret_demande"].get("at") or ""))
    conn.execute("UPDATE tickets SET data=?, version=version+1 WHERE slug=? AND id=?",
                 (json.dumps(data, ensure_ascii=False), slug, data["id"]))
    journal.ecrire(conn, slug, data["id"], "migration_l2", "migration",
                   {"vers": state, "raison": raison, "drapeaux": sorted(legacy)})


def _a_migrer(data: dict) -> bool:
    return "runs" in data or data.get("state") not in etats.ETATS


def _a_migrer_dans(conn) -> list[tuple[str, dict]]:
    lignes = conn.execute("SELECT slug, data FROM tickets ORDER BY seq").fetchall()
    return [(slug, data) for slug, data in ((s, json.loads(t)) for s, t in lignes)
            if isinstance(data, dict) and data.get("id") and _a_migrer(data)]


def _affinages(conn, affiner: Affineur) -> dict[tuple, tuple]:
    """Ce que le vrai process dit des runs restés ouverts — lu AVANT de prendre le verrou
    d'écriture : `affiner` peut relire le store, jamais au milieu de la migration."""
    affinages = {}
    for slug, data in _a_migrer_dans(conn):
        cible = _a_affiner(data)
        trouve = affiner(*cible) if cible else None
        if trouve:
            affinages[(slug, data["id"])] = trouve
    conn.commit()
    return affinages


def migrer(conn: sqlite3.Connection, affiner: Affineur | None = None) -> int:
    """Migre toute la base de `conn` (déjà ouverte, schéma assuré). Rend le nombre de tickets
    migrés ; 0 s'il n'y avait plus rien à migrer."""
    conn.commit()
    affinages = _affinages(conn, affiner) if affiner is not None else {}
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS store_migrations (nom TEXT PRIMARY KEY, at TEXT)")
        migres = 0
        for slug, data in _a_migrer_dans(conn):
            _migrer_un(conn, slug, data, affinages.get((slug, data["id"])))
            migres += 1
        if migres:
            conn.execute("INSERT OR REPLACE INTO store_migrations(nom, at) VALUES(?, ?)",
                         (NOM, _maintenant()))
    except BaseException:
        conn.rollback()
        raise
    conn.commit()
    return migres
