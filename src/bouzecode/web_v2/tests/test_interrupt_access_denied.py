# [desc] Un refus de l'OS sur UN process ne doit pas emporter le serveur ni les autres agents. [/desc]
"""Cas vécu du 28/07 : trois `POST /api/agents/<id>/interruptions` d'affilée, puis serveur mort.

    File ".../psutil/__init__.py", line 1330, in terminate
        self._proc.kill()
    psutil.AccessDenied: (pid=42516)

Sous Windows, `AccessDenied` sur un pid est un cas COURANT (process en train de mourir,
pid recyclé, process d'une autre session) : c'est un RÉSULTAT possible de la demande de
terminaison, pas une panne. Non attrapé, il remontait par `terminate_agent_process` et
`reap_session_processes` — donc aussi par `refresh_agent_status`, appelé sur CHAQUE
`list_agents()`, c.-à-d. sur presque toutes les routes.

Il ne doit pas non plus être avalé : l'échec reste inscrit sur l'agent et remonte dans la
réponse de l'endpoint.

Les process cibles sont fabriqués ICI et tués ICI ; le refus de l'OS est joué par un
double de process qui lève la VRAIE exception psutil (aucun process réel n'est protégé
sur cette machine, et aucun test n'a le droit d'aller en chercher un)."""
from __future__ import annotations

from bouzecode.web_v2.services.work import interruption
import subprocess
import sys
import time
from types import SimpleNamespace

import psutil
import pytest

from bouzecode.web_v2.runtime.runner import (
    agent_arret,
    agent_etat,
    agent_fiche,
    agent_processus,
    agent_reprise,
    agent_vivacite,
)
from bouzecode.web_v2.tests.production_isolation import autoriser_la_destruction


class ProcessQuiRefuse:
    """Double d'un `psutil.Process` dont l'OS refuse la terminaison (ACL Windows)."""

    def __init__(self, pid: int = 42516):
        self.pid = pid

    def is_running(self) -> bool:
        return True

    def status(self) -> str:
        return psutil.STATUS_RUNNING

    def terminate(self) -> None:
        raise psutil.AccessDenied(pid=self.pid)


@pytest.fixture()
def process_jetable():
    """Process python À NOUS, tué en fin de test quoi qu'il arrive."""
    lances: list[subprocess.Popen] = []

    def lancer(marqueur: str) -> subprocess.Popen:
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", marqueur])
        fin = time.time() + 5
        while time.time() < fin and not psutil.Process(proc.pid).cmdline():
            time.sleep(0.05)
        lances.append(proc)
        return proc

    yield lancer
    for proc in lances:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)


def _agent(pid: int, session_path: str = "") -> agent_fiche.Agent:
    return agent_fiche.Agent(agent_id="cible01", prompt="p", model="", cwd="", pid=pid,
                        started_at="2026-07-28T10:00:00Z", session_path=session_path)


# ── le refus est un résultat, jamais une panne ───────────────────────────────

def test_un_refus_de_l_os_ne_leve_pas(monkeypatch):
    """`AccessDenied` sur le process d'un agent → False, et rien ne remonte."""
    autoriser_la_destruction(monkeypatch)
    agent = _agent(42516)

    assert agent_arret.signal_termination(ProcessQuiRefuse(), agent) is False


def test_le_refus_reste_visible_sur_l_agent(monkeypatch):
    """Pas de silence : le motif du refus est inscrit sur l'agent (donc servi par l'API)."""
    autoriser_la_destruction(monkeypatch)
    agent = _agent(42516)

    agent_arret.signal_termination(ProcessQuiRefuse(), agent)

    assert "AccessDenied" in agent.termination_error and "42516" in agent.termination_error


def test_une_terminaison_reussie_efface_le_motif(monkeypatch, process_jetable):
    """Contre-preuve : le champ ne colle pas à un agent qu'on a fini par arrêter."""
    autoriser_la_destruction(monkeypatch)
    vivant = process_jetable("temoin-succes")
    agent = _agent(vivant.pid)
    agent.termination_error = "AccessDenied (pid=42516)"

    assert agent_arret.signal_termination(psutil.Process(vivant.pid), agent) is True
    assert agent.termination_error == ""
    assert vivant.wait(timeout=5) is not None


def test_le_balayage_des_jumeaux_continue_apres_un_refus(monkeypatch, process_jetable):
    """`reap_session_processes` : un process intouchable ne doit pas priver les autres
    de leur terminaison ni faire 500 la route qui l'appelle."""
    autoriser_la_destruction(monkeypatch)
    jumeau = process_jetable("session-jumelle")
    monkeypatch.setattr(agent_processus, "_procs_for_session",
                        lambda _s: iter([ProcessQuiRefuse(), psutil.Process(jumeau.pid)]))

    termines = agent_arret.reap_session_processes("peu-importe")

    assert termines == 1, "le refus a compté comme une terminaison"
    assert jumeau.wait(timeout=5) is not None


def test_le_rafraichissement_de_statut_ne_tente_plus_aucune_terminaison(monkeypatch, tmp_path):
    """Le chemin qui tuait le serveur : `refresh_agent_status` est appelé par CHAQUE
    `list_agents()`. Un agent vivant dont l'IPC dit « fini » y déclenchait une terminaison ;
    refusée, elle faisait 500 toutes les routes qui listent des agents. Depuis la spec
    ticketing (B1, constat C2) une LECTURE ne tue plus rien : le process, reprenable à chaud,
    reste vivant et non terminé — son éviction relève du pool chaud."""
    autoriser_la_destruction(monkeypatch)
    agent = _agent(42516, session_path=str(tmp_path / "cible01.session.json"))
    monkeypatch.setattr(agent_etat, "get_ipc_state", lambda _a: {"status": "finished"})
    monkeypatch.setattr(agent_processus, "_pid_still_belongs_to", lambda _a: True)
    monkeypatch.setattr(agent_vivacite.psutil, "pid_exists", lambda _pid: True)
    monkeypatch.setattr(agent_vivacite.psutil, "Process", lambda _pid: ProcessQuiRefuse())
    monkeypatch.setattr(agent_fiche, "_save", lambda _a: None)
    monkeypatch.setattr(agent_reprise, "_maybe_drain_deferred", lambda a: a)

    rafraichi = agent_etat.refresh_agent_status(agent)

    assert rafraichi.returncode is None, "une lecture ne marque pas fini un process vivant"


# ── l'endpoint dit la vérité ─────────────────────────────────────────────────

@pytest.fixture()
def client(tmp_path, monkeypatch):
    from bouzecode.web_v2.app import create_app

    ipc_dir = tmp_path / "ipc"
    ipc_dir.mkdir()
    agent = SimpleNamespace(agent_id="abc123", ipc_dir=str(ipc_dir), pid=42516,
                            returncode=None, ticket_slug="", ticket_id="")
    monkeypatch.setattr(agent_fiche, "load_agent",
                        lambda agent_id: agent if agent_id == "abc123" else None)
    monkeypatch.setattr(agent_vivacite, "is_running", lambda _a: True)
    monkeypatch.setattr(interruption.time, "sleep", lambda *_a, **_k: None)
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as flask_client:
        yield flask_client


def test_un_refus_ne_fait_pas_tomber_l_endpoint(client, monkeypatch):
    """L'agent est coincé ET intouchable : l'endpoint répond 502 `arret_refuse` (refus d'un
    système tiers, spec ticketing §9), jamais 500 ni 200 `ok: false`."""

    monkeypatch.setattr(agent_arret, "kill_agent",
                        lambda _a: {"signalled": False, "error": "AccessDenied (pid=42516)"})

    reponse = client.post("/api/agents/abc123/interruptions")

    assert reponse.status_code == 502
    corps = reponse.get_json()
    assert corps["error"]["code"] == "arret_refuse"
    assert "AccessDenied" in corps["error"]["message"]


def test_la_documentation_avoue_l_escalade():
    """`…/interruptions` N'EST PAS purement doux : après une courte grâce il tue le process.
    La description servie par l'API doit le dire — un utilisateur ne peut pas arbitrer
    entre …/interruptions et …/stop sur une description fausse."""
    from bouzecode.web_v2.schema.application import schema_des_routes

    texte = schema_des_routes()["endpoints"]["POST /api/agents/<agent_id>/interruptions"].lower()

    assert "escalade" in texte or "tue" in texte
    assert "le process reste vivant" not in texte
