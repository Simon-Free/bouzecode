# [desc] Migration du store au lot L2 sur une COPIE fabriquée d'une base ancienne (runs dans le JSON, tous les drapeaux) : états attendus, runs dans leur table, rien de perdu, idempotente, sûre à deux serveurs. [/desc]
from __future__ import annotations

import json
import sqlite3
import threading

import pytest

from bouzecode.web_v2.services.work import _persistence, arret, tickets
from bouzecode.web_v2.services.work.fsm import etats, migration, stockage

SLUG = "p"
_VIEUX = "2020-01-01T00:00:00"


def _run(agent_id: str, **champs) -> dict:
    return {"agent_id": agent_id, "kind": "work", "model": "m", "started_at": _VIEUX,
            "state": "finished", "key": f"agent/{agent_id}", "pid_alive": False, **champs}


#: (id, champs du ticket ancien, état attendu, code de raison attendu)
CAS = [
    ("cree0001", {}, etats.CREATED, None),
    ("lanc0001", {"launching": True}, etats.PROVISIONING, None),
    ("figee001", {"launching": True, "created_at": _VIEUX}, etats.LAUNCH_FAILED,
     "lancement_interrompu"),
    ("echec001", {"launch_failed": {"error": "git KO", "at": _VIEUX}}, etats.LAUNCH_FAILED,
     "lancement_echoue"),
    ("arret001", {"launch_failed": {"error": "arrêté à ta demande pendant la préparation"}},
     etats.STOPPED, "arret_preparation"),
    ("plant001", {"crashed": True, "runs": [_run("ag-plante")]}, etats.STOPPED, "crashed"),
    ("livre001", {"runs": [_run("ag-livre", completed=True, turns=2)]}, etats.DELIVERED, None),
    ("encou001", {"runs": [_run("ag-encours", state="running")]}, etats.RUNNING, None),
    ("reins001", {"awaiting_reply": True, "runs": [_run("ag-reinstruit", completed=True)]},
     etats.RUNNING, None),
    ("fait0001", {"done": True, "closed": {"outcome": "accepted", "reason": "ok"},
                  "runs": [_run("ag-fait", completed=True)]}, etats.CLOSED, "accepte"),
    ("aban0001", {"done": True, "closed": {"outcome": "abandoned"},
                  "runs": [_run("ag-aban")]}, etats.ABANDONED, "abandonne"),
    ("merg0001", {"done": True, "reaped": True, "runs": [_run("ag-merge", completed=True)],
                  "worktree": {"state": "cleaned", "worktree": "/x", "branch": "agent/merg0001",
                               "integrated_at": "2026-01-02T00:00:00"}}, etats.CLOSED, "integre"),
    ("bloq0001", {"runs": [_run("ag-bloque", completed=True)],
                  "worktree": {"state": "needs_attention", "integrate_error": "arbre sale"}},
     etats.DELIVERED, "merge_bloque"),
    ("conf0001", {"runs": [_run("ag-conflit", completed=True)],
                  "worktree": {"state": "conflict", "conflict_files": ["a.py"]}},
     etats.CONFLICT, "conflit"),
    ("reso0001", {"runs": [_run("ag-resolu", completed=True)],
                  "worktree": {"state": "conflict_resolved"}}, etats.CONFLICT, "conflit_resolu"),
    ("peri0001", {"runs": [_run("ag-peril", completed=True)], "uncommitted": ["a.py"],
                  "recolte_bloquee": "index verrouillé"}, etats.DELIVERED,
     "livraison_non_commitee"),
    ("clot0001", {"runs": [_run("ag-manager", completed=True)], "closure_blocked": "e1;e2",
                  "closure_forced": ""}, etats.DELIVERED, "cloture_bloquee"),
    ("stop0001", {"runs": [_run("ag-stop", completed=True)],
                  "arret_demande": {"par": "Fleet kill", "at": "2026-01-03T00:00:00"}},
     etats.DELIVERED, None),
]


def _base_ancienne(chemin) -> None:
    """Une base telle que la laissait le code d'avant L2 : table `tickets(seq, slug, id, data)`
    sans `version`, runs DANS le JSON, et un agent_id répété (le cas réel des reprises)."""
    conn = sqlite3.connect(chemin)
    conn.execute("CREATE TABLE tickets (seq INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT NOT"
                 " NULL, id TEXT NOT NULL, data TEXT NOT NULL, UNIQUE(slug, id))")
    for ident, champs, _etat, _code in CAS:
        ticket = {"id": ident, "title": ident, "prompt": "p", "created_at": "2099-01-01T00:00:00",
                  "done": False, "comments": [{"at": _VIEUX, "text": "ancien", "sent": False}],
                  "runs": [], **champs}
        conn.execute("INSERT INTO tickets(slug, id, data) VALUES(?, ?, ?)",
                     (SLUG, ident, json.dumps(ticket)))
    doublon = {"id": "dupl0001", "title": "d", "prompt": "p", "created_at": _VIEUX,
               "runs": [_run("ag-rep", completed=True, turns=3), _run("ag-rep", turns=1)]}
    conn.execute("INSERT INTO tickets(slug, id, data) VALUES(?, ?, ?)",
                 (SLUG, "dupl0001", json.dumps(doublon)))
    conn.commit()
    conn.close()


@pytest.fixture()
def base(tmp_path, monkeypatch):
    dossier = tmp_path / "store"
    dossier.mkdir()
    _base_ancienne(dossier / "tickets.db")
    monkeypatch.setattr(_persistence, "TICKETS_DIR", dossier)
    return dossier


def _migrer() -> int:
    with _persistence._connect() as conn:
        return migration.migrer(conn)


@pytest.mark.parametrize(("ident", "champs", "etat", "code"), CAS, ids=[c[0] for c in CAS])
def test_chaque_drapeau_donne_l_etat_attendu(base, ident, champs, etat, code):
    _migrer()
    ticket = tickets.get_ticket(SLUG, ident)
    assert ticket["state"] == etat
    assert (ticket["state_reason"] or {}).get("code") == code
    for drapeau in migration.DRAPEAUX:
        assert drapeau not in ticket, f"{drapeau} pilote encore {ident}"
        if drapeau in champs:
            assert ticket["legacy"][drapeau] == champs[drapeau], "rien n'est supprimé"


def test_les_runs_quittent_le_json_pour_leur_table(base):
    _migrer()
    with _persistence._connect() as conn:
        assert all("runs" not in json.loads(d) for (d,) in conn.execute("SELECT data FROM tickets"))
        assert stockage.runs_du_ticket(conn, SLUG, "livre001")[0]["turns"] == 2
    encours = tickets.get_ticket(SLUG, "encou001")["runs"][0]
    assert encours["state"] == "running"
    assert "key" not in encours and "pid_alive" not in encours  # transitoires jamais persistés
    assert tickets.get_ticket(SLUG, "livre001")["runs"][0]["state"] == "ended"


def test_un_agent_repete_garde_son_run_le_plus_recent_et_l_ancien_reste_lisible(base):
    _migrer()
    ticket = tickets.get_ticket(SLUG, "dupl0001")
    assert [(r["agent_id"], r["turns"]) for r in ticket["runs"]] == [("ag-rep", 3)]
    assert ticket["legacy"]["runs"][0]["turns"] == 1


def test_worktree_retire_commentaires_et_arret_demande(base):
    _migrer()
    merge = tickets.get_ticket(SLUG, "merg0001")
    assert "state" not in merge["worktree"] and merge["worktree"]["retire_at"]
    assert merge["integration"]["merged_at"] == "2026-01-02T00:00:00"
    assert merge["legacy"]["worktree_state"] == "cleaned"
    assert merge["comments"][0]["text"] == "ancien"
    assert arret.demande(tickets.get_ticket(SLUG, "stop0001"), SLUG)
    assert not arret.demande(tickets.get_ticket(SLUG, "livre001"), SLUG)


def test_idempotente(base):
    assert _migrer() == len(CAS) + 1
    avant = {i: tickets.get_ticket(SLUG, i) for i, *_ in CAS}
    assert _migrer() == 0
    assert {i: tickets.get_ticket(SLUG, i) for i, *_ in CAS} == avant


def test_sure_a_deux_serveurs(base):
    """Deux migrations simultanées (deux connexions, comme deux serveurs) : chaque ticket est
    migré UNE fois, aucun run n'est inséré deux fois."""
    totaux: list[int] = []
    barriere = threading.Barrier(2)

    def serveur() -> None:
        conn = sqlite3.connect(base / "tickets.db", timeout=30)
        stockage.assurer_le_schema(conn)
        conn.commit()
        barriere.wait(10)
        totaux.append(migration.migrer(conn))
        conn.close()

    fils = [threading.Thread(target=serveur) for _ in range(2)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(30)
    assert sorted(totaux) == [0, len(CAS) + 1]
    with _persistence._connect() as conn:
        migres = conn.execute("SELECT COUNT(*) FROM ticket_events WHERE kind='migration_l2'")
        assert migres.fetchone()[0] == len(CAS) + 1


def test_l_affinage_lit_le_vrai_process(base):
    """Au boot, un run resté ouvert est confronté à son process : mort → `stopped{crashed}`."""
    with _persistence._connect() as conn:
        migration.migrer(conn, lambda vue, run: (etats.STOPPED, {"code": "crashed"}))
    assert tickets.get_ticket(SLUG, "encou001")["state"] == etats.STOPPED
    assert tickets.get_ticket(SLUG, "livre001")["state"] == etats.DELIVERED
