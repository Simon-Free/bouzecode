# [desc] Tests vérifiant que le serveur estampille l'IPC avant kill/escalade interrupt et rollback si AccessDenied [/desc]
"""Fausse alerte « MORT SANS CLOTURE » : un agent ne peut pas ecrire « je suis mort ».

Quand le serveur TUE le process (`/kill`, ou l'escalade de `/interrupt`), l'agent meurt
avant d'avoir pu corriger `state.json` : l'IPC reste fige sur `running` avec un pid perime.
Tout observateur croise alors « IPC dit running » + « process absent » et conclut a une mort
en plein tour — alors que c'est l'etat transitoire d'une relance NORMALE (mesure du
2026-08-25 : 4 alertes, 4 faux positifs).

Le serveur SAIT qu'il va tuer : il estampille donc l'etat AVANT la mise a mort. Et si l'OS
REFUSE de tuer (`AccessDenied`), il REMET l'etat precedent — sinon on cree le mensonge
inverse, pire : un agent marque mort qui tourne toujours, invisible pour la supervision.

Aucun `unittest.mock` ici : le tueur est injecte par le point d'injection deja utilise par
les tests voisins (`runner.kill_agent`), et l'ecriture/relecture IPC reste REELLE.
"""
from __future__ import annotations

from bouzecode.web_v2.services.work import interruption
from types import SimpleNamespace

import pytest

from bouzecode.web_v2.runtime import ipc

ETAT_AVANT = {"status": ipc.STATUS_RUNNING, "pid": 42516, "turn": 7}


@pytest.fixture()
def paths(tmp_path):
    """IPC d'un agent qui se croit (et se dit) en plein tour."""
    p = ipc.from_dir(str(tmp_path / "ipc"))
    ipc.write_state(p, ETAT_AVANT["status"], pid=ETAT_AVANT["pid"], turn=ETAT_AVANT["turn"])
    assert ipc.read_state(p)["status"] == ipc.STATUS_RUNNING
    return p


@pytest.fixture()
def client(paths, monkeypatch):
    from bouzecode.web_v2.app import create_app
    from bouzecode.web_v2.runtime.runner import agent_fiche

    agent = SimpleNamespace(agent_id="abc123", ipc_dir=str(paths.root), pid=ETAT_AVANT["pid"],
                            returncode=None, ticket_slug="", ticket_id="", session_path="")
    monkeypatch.setattr(agent_fiche, "load_agent",
                        lambda agent_id: agent if agent_id == "abc123" else None)
    monkeypatch.setattr(interruption.time, "sleep", lambda *_a, **_k: None)
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as flask_client:
        yield flask_client


def _tueur(monkeypatch, *, refuse: bool):
    """Injecte un tueur qui reussit, ou un tueur que l'OS REFUSE (AccessDenied)."""
    from bouzecode.web_v2.runtime.runner import agent_arret

    appels: list = []

    def kill_agent(agent):
        appels.append(ipc.read_state(ipc.from_dir(agent.ipc_dir)))
        if refuse:
            return {"signalled": False, "twins": 0, "error": "AccessDenied (pid=42516)"}
        return {"signalled": True, "twins": 0, "error": ""}

    monkeypatch.setattr(agent_arret, "kill_agent", kill_agent)
    return appels


def _coince(monkeypatch, valeur: bool):
    """Agent COINCE hors point d'interruption (True) ou qui a cede (False)."""
    from bouzecode.web_v2.runtime.runner import agent_chaud, agent_vivacite

    monkeypatch.setattr(agent_chaud, "is_mid_turn", lambda _a: valeur)
    monkeypatch.setattr(agent_vivacite, "is_running", lambda _a: valeur)


# ── ce que voit l'observateur APRES une mise a mort reussie ───────────────────

def test_apres_un_kill_l_ipc_ne_dit_plus_running(client, paths, monkeypatch):
    """`/kill` : l'etat estampille dit la verite, plus jamais `running`."""
    _tueur(monkeypatch, refuse=False)

    reponse = client.post("/api/agents/abc123/stop")

    assert reponse.status_code == 202 and reponse.get_json()["ok"] is True
    etat = ipc.read_state(paths)
    assert etat["status"] != ipc.STATUS_RUNNING
    assert etat["status"] == ipc.STATUS_KILLED_BY_SERVER


def test_apres_l_escalade_d_un_interrupt_l_ipc_ne_dit_plus_running(client, paths, monkeypatch):
    """Escalade de `/interrupt` (elle a TUE) : meme exigence, origine distincte."""
    _coince(monkeypatch, True)
    _tueur(monkeypatch, refuse=False)

    reponse = client.post("/api/agents/abc123/interruptions")

    assert reponse.get_json() == {"ok": True, "agent_id": "abc123", "escalated": True}
    etat = ipc.read_state(paths)
    assert etat["status"] != ipc.STATUS_RUNNING
    assert etat["status"] == ipc.STATUS_INTERRUPTED_BY_SERVER


def test_l_estampille_est_posee_AVANT_la_mise_a_mort(client, monkeypatch):
    """L'ordre est le coeur du correctif : si on estampillait apres, le process serait
    deja mort et la fenetre de contradiction resterait ouverte."""
    vu = _tueur(monkeypatch, refuse=False)

    client.post("/api/agents/abc123/stop")

    assert vu and vu[0]["status"] == ipc.STATUS_KILLED_BY_SERVER


# ── non-regression : l'interruption DOUCE ne touche a rien ────────────────────

def test_une_interruption_douce_laisse_l_etat_inchange(client, paths, monkeypatch):
    """Elle n'a PAS tue : rien a estampiller, l'agent reste maitre de son etat."""
    _coince(monkeypatch, False)
    _tueur(monkeypatch, refuse=False)

    reponse = client.post("/api/agents/abc123/interruptions")

    assert reponse.get_json() == {"ok": True, "agent_id": "abc123", "escalated": False}
    etat = ipc.read_state(paths)
    assert etat["status"] == ETAT_AVANT["status"]
    assert etat["pid"] == ETAT_AVANT["pid"] and etat["turn"] == ETAT_AVANT["turn"]


# ── le test qui compte le plus : ROLLBACK sur refus de l'OS ───────────────────

def test_un_kill_refuse_remet_l_etat_d_avant(client, paths, monkeypatch):
    """L'OS refuse : l'agent TOURNE TOUJOURS. Le marquer mort le rendrait invisible."""
    _tueur(monkeypatch, refuse=True)

    reponse = client.post("/api/agents/abc123/stop")

    corps = reponse.get_json()
    assert reponse.status_code == 502 and corps["error"]["code"] == "arret_refuse"
    assert "AccessDenied" in corps["error"]["message"]
    etat = ipc.read_state(paths)
    assert etat["status"] == ETAT_AVANT["status"], "etat non restaure : agent mort-vivant"
    assert etat["pid"] == ETAT_AVANT["pid"] and etat["turn"] == ETAT_AVANT["turn"]


def test_une_escalade_refusee_remet_l_etat_d_avant(client, paths, monkeypatch):
    """Meme rollback sur la branche d'escalade de `/interrupt`."""
    _coince(monkeypatch, True)
    _tueur(monkeypatch, refuse=True)

    reponse = client.post("/api/agents/abc123/interruptions")

    corps = reponse.get_json()
    assert reponse.status_code == 502 and corps["error"]["code"] == "arret_refuse"
    assert corps["error"]["details"]["escalated"] is True
    etat = ipc.read_state(paths)
    assert etat["status"] == ETAT_AVANT["status"]
    assert etat["pid"] == ETAT_AVANT["pid"] and etat["turn"] == ETAT_AVANT["turn"]


def test_un_kill_refuse_sans_etat_prealable_ne_laisse_pas_d_estampille(tmp_path, monkeypatch):
    """Rollback quand il n'y avait AUCUN state.json : on ne doit pas en laisser un qui
    annonce une mort qui n'a pas eu lieu."""
    from bouzecode.web_v2.app import create_app
    from bouzecode.web_v2.runtime.runner import agent_fiche

    vierge = ipc.from_dir(str(tmp_path / "vide"))
    assert not vierge.state.exists()
    agent = SimpleNamespace(agent_id="abc123", ipc_dir=str(vierge.root), pid=42516,
                            returncode=None, ticket_slug="", ticket_id="", session_path="")
    monkeypatch.setattr(agent_fiche, "load_agent", lambda _i: agent)
    monkeypatch.setattr(interruption.time, "sleep", lambda *_a, **_k: None)
    _tueur(monkeypatch, refuse=True)
    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as flask_client:
        flask_client.post("/api/agents/abc123/stop")

    etat = ipc.read_state(vierge)
    assert etat["status"] not in (ipc.STATUS_KILLED_BY_SERVER, ipc.STATUS_INTERRUPTED_BY_SERVER)


# ── les deux origines restent distinguables ──────────────────────────────────

def test_les_deux_origines_sont_distinguables(client, paths, monkeypatch):
    """Un observateur doit pouvoir dire QUI a tue et POURQUOI (kill explicite vs relance)."""
    _tueur(monkeypatch, refuse=False)
    client.post("/api/agents/abc123/stop")
    apres_kill = ipc.read_state(paths)

    ipc.write_state(paths, ETAT_AVANT["status"], pid=ETAT_AVANT["pid"])
    _coince(monkeypatch, True)
    client.post("/api/agents/abc123/interruptions")
    apres_interrupt = ipc.read_state(paths)

    assert apres_kill["status"] != apres_interrupt["status"]
    assert apres_kill.get("killed_by") == "server"
    assert apres_interrupt.get("killed_by") == "server"
