# [desc] Un agent relancé qui travaille s'affiche « En cours », pas « Attend ses sous-agents ». [/desc]
"""Cas vécu le 2026-09-24 (agent 4e3cacec du portail des énigmes) : l'agent principal, relancé
« même agent » après sa réponse finale, TRAVAILLAIT (process vivant, IPC `running`, tour 86),
mais l'arbre le servait `state=finished`, `etat=orchestrating` → « Attend ses sous-agents »,
alors qu'aucun de ses trois sous-agents n'était actif (deux terminés, un arrêté sans finir).

Deux causes : un « finished » mémorisé par `store.agent_status` survivait au process vivant, et
`fleet` déduisait « attend ses enfants » de « fini + vivacité running » au lieu d'une preuve
(un descendant qui travaille ou attend une réponse).

Aucun mock : vrais fichiers d'agents, vraies sessions, vrais fichiers IPC, vrais process python
(« vivants ») ou pids inexistants (« morts »), la vraie route HTTP."""
from __future__ import annotations

import json
import subprocess
import sys
import time

import pytest

from bouzecode.web_v2.runtime.runner import agent_fiche, agent_registre
from bouzecode.web_v2.services.sessions import store
from bouzecode.web_v2.services.work import fleet, fleet_cache

PID_MORT = 4_000_001


@pytest.fixture()
def parc(tmp_path, monkeypatch):
    dossier = tmp_path / "agents"
    dossier.mkdir()
    monkeypatch.setattr(agent_fiche, "AGENTS_DIR", dossier)
    fleet_cache.clear()
    store._status_cache.clear()
    monkeypatch.setattr(fleet, "sweep_warm_pool", lambda: [])
    monkeypatch.setenv("BOUZECODE_WAKE_POLLER", "0")
    process = []
    yield dossier, process
    for proc in process:
        proc.kill()
        proc.wait(timeout=5)


@pytest.fixture()
def client(parc):
    from bouzecode.web_v2.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _vivant(parc, session: str) -> int:
    """Un vrai process python qui porte la session dans sa ligne de commande (comme un agent)."""
    _, process = parc
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)",
                             "--session-file", session])
    process.append(proc)
    return proc.pid


def _agent(parc, agent_id: str, *, parent: str = "", vivant: bool = False,
           ipc: str = "", fini: bool = True, returncode=None) -> None:
    dossier, _ = parc
    session = dossier / f"{agent_id}.session.json"
    donnees = {"messages": [{"role": "user", "content": f"mission {agent_id}"}]}
    if fini:
        donnees.update(close_reason="final_answer", turn_count=3)
    session.write_text(json.dumps(donnees), encoding="utf-8")
    ipc_dir = dossier / f"{agent_id}.ipc"
    ipc_dir.mkdir()
    if ipc:
        (ipc_dir / "state.json").write_text(
            json.dumps({"status": ipc, "updated_at": time.time(), "turn": 4}), encoding="utf-8")
    if ipc == "running":
        #  Le modèle a déjà commencé à répondre : sinon l'état est la phase « le modèle lit ».
        session.with_name(f"{agent_id}.session.partial.json").write_text(
            json.dumps({"text": "je continue le scraper"}), encoding="utf-8")
    pid = _vivant(parc, str(session)) if vivant else PID_MORT
    (dossier / f"{agent_id}.json").write_text(json.dumps({
        "agent_id": agent_id, "prompt": f"mission {agent_id}", "model": "m",
        "cwd": str(dossier), "pid": pid, "returncode": None if vivant else returncode,
        "run_kind": "work", "parent": parent, "started_at": "2026-09-24T08:00:00",
        "session_path": str(session), "ipc_dir": str(ipc_dir),
    }), encoding="utf-8")


def _arbre(client) -> dict[str, dict]:
    agent_fiche._list_agents_cache.clear()
    agent_registre._agent_file_cache.clear()
    fleet_cache.clear()
    noeuds = client.get("/api/agents/tree").get_json()["nodes"]
    return {n["agent_id"]: n for n in noeuds}


def test_un_agent_relance_qui_travaille_est_en_cours(client, parc):
    """Le cas exact : parent relancé qui travaille, 3 enfants dont un arrêté sans finir."""
    _agent(parc, "parentrelance", vivant=True, ipc="running")
    _agent(parc, "enfantfini01", parent="parentrelance", returncode=0)
    _agent(parc, "enfantfini02", parent="parentrelance", returncode=0)
    _agent(parc, "enfantmort03", parent="parentrelance", fini=False, returncode=-15)
    #  Premier passage : son « finished » a été mémorisé (process pas encore vu vivant).
    store._status_cache["parentrelance"] = {"state": "finished"}

    arbre = _arbre(client)

    assert arbre["parentrelance"]["etat"] == "running"
    assert arbre["parentrelance"]["libelle_etat"] == "En cours"
    assert arbre["enfantmort03"]["etat"] == "crashed"
    assert arbre["enfantfini01"]["etat"] == "finished"


def test_un_agent_fini_dont_un_enfant_travaille_attend_ses_sous_agents(client, parc):
    _agent(parc, "managerfini1", returncode=0)
    _agent(parc, "enfantactif1", parent="managerfini1", vivant=True, ipc="running")

    arbre = _arbre(client)

    assert arbre["managerfini1"]["etat"] == "orchestrating"
    assert arbre["managerfini1"]["libelle_etat"] == "Attend ses sous-agents"


def test_un_agent_fini_dont_les_enfants_sont_finis_ou_morts_est_termine(client, parc):
    _agent(parc, "managerfini2", returncode=0)
    _agent(parc, "enfantfini04", parent="managerfini2", returncode=0)
    _agent(parc, "enfantmort05", parent="managerfini2", fini=False, returncode=-15)

    arbre = _arbre(client)

    assert arbre["managerfini2"]["etat"] == "finished"


def test_un_enfant_chaud_mais_oisif_ne_fait_pas_attendre_son_parent(client, parc):
    """Un sous-agent fini qui reste résident (warm pool, IPC `idle`) ne travaille pas."""
    _agent(parc, "managerfini3", returncode=0)
    _agent(parc, "enfantchaud6", parent="managerfini3", vivant=True, ipc="idle")

    arbre = _arbre(client)

    assert arbre["managerfini3"]["etat"] == "finished"


def test_un_enfant_qui_attend_ta_reponse_ne_met_pas_son_parent_en_cours(client, parc):
    """Cas du bac à sable : manager fini (« C'est fait », plus de process), un sous-agent attend
    la réponse de l'utilisateur. Personne ne TRAVAILLE : la page Agents le rangeait « En cours »
    (« Attend ses sous-agents », bouton Arrêter sans process) quand le Bureau et la pastille
    disaient « aucun agent ne travaille ». Le sous-agent est dans « À traiter », le parent fini."""
    _agent(parc, "managerfini4", returncode=0)
    _agent(parc, "enfantquest7", parent="managerfini4", vivant=True, ipc="awaiting_input", fini=False)

    arbre = _arbre(client)

    assert arbre["enfantquest7"]["etat"] == "awaiting_input"
    assert arbre["managerfini4"]["etat"] == "finished"
    assert client.get("/api/nav/counts").get_json()["en_cours"] == 0
