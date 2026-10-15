# [desc] Pastilles de navigation = ce que montrent la boîte « À traiter » et la page Agents, même juste après un changement d'état d'agent sans écriture de tâche. [/desc]
"""Le vérificateur d'invariants des E2E signalait à chaque passe complète :

* `nav a_moi=8 ≠ boîte 9` — la pastille avait SA propre mémoire (`nav_counts`, servie périmée
  jusqu'à 120 s et rafraîchie en fond), posée PAR-DESSUS celle de la boîte : une boîte
  recalculée à l'instant et une pastille servie depuis sa copie d'avant divergeaient ;
* `nav en_cours=0 ≠ agents affichés au travail [...]` — la pastille comptait sur une AUTRE page
  d'arbre (l'arbre complet, entrée de cache distincte) que celle servie à la page Agents, puis
  gardait ce compte dans sa mémoire, dont la clé (génération des écritures de TÂCHES) ne bouge
  pas quand un agent change d'état.

Aucun mock de calcul : vrais fichiers d'agents, vrais process « vivants », vraies routes HTTP.
Seule l'horloge de la mémoire du Bureau est pilotée (pas d'attente réelle)."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time

import pytest

from bouzecode.web_v2.runtime.runner import agent_fiche, agent_registre
from bouzecode.web_v2.services.sessions import store
from bouzecode.web_v2.services.work import fleet, fleet_cache, inbox, taches_vue


class _Horloge:
    def __init__(self):
        self.t = 1000.0

    def monotonic(self):
        return self.t

    def avancer(self, secondes):
        self.t += secondes


@pytest.fixture()
def horloge(monkeypatch):
    h = _Horloge()
    monkeypatch.setattr(taches_vue, "CACHE_TTL", 3.0)
    monkeypatch.setattr(taches_vue, "time", h)
    taches_vue.invalider()
    yield h
    taches_vue.invalider()


def _attendre_les_recalculs_en_fond(delai: float = 5.0) -> None:
    """Un recalcul lancé en fond par un test ne doit pas écrire après lui."""
    for fil in [t for t in threading.enumerate()
                if t.name.startswith(("taches_vue-", "cache-refresh", "pastilles-"))]:
        fil.join(timeout=delai)


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
    _attendre_les_recalculs_en_fond()
    fleet_cache.attendre_puis_vider()
    for proc in process:
        proc.kill()
        proc.wait(timeout=5)


@pytest.fixture()
def client(parc, horloge):
    from bouzecode.web_v2.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _agent_vivant(parc, agent_id: str, ipc: str) -> None:
    dossier, process = parc
    session = dossier / f"{agent_id}.session.json"
    session.write_text(json.dumps({"messages": [{"role": "user", "content": f"mission {agent_id}"}]}),
                       encoding="utf-8")
    (dossier / f"{agent_id}.ipc").mkdir()
    _ipc(parc, agent_id, ipc)
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)",
                             "--session-file", str(session)])
    process.append(proc)
    (dossier / f"{agent_id}.json").write_text(json.dumps({
        "agent_id": agent_id, "prompt": f"mission {agent_id}", "model": "m",
        "cwd": str(dossier), "pid": proc.pid, "returncode": None,
        "run_kind": "work", "parent": "", "started_at": "2026-09-24T08:00:00",
        "session_path": str(session), "ipc_dir": str(dossier / f"{agent_id}.ipc"),
    }), encoding="utf-8")


def _ipc(parc, agent_id: str, statut: str) -> None:
    """Change l'état d'un agent comme le fait son process (fichier IPC) : AUCUNE écriture de
    tâche, donc aucune génération des tâches qui bouge."""
    dossier, _ = parc
    donnees = {"status": statut, "updated_at": time.time(), "turn": 4}
    if statut.startswith("awaiting"):
        donnees["question"] = "On continue ?"
    (dossier / f"{agent_id}.ipc" / "state.json").write_text(json.dumps(donnees), encoding="utf-8")
    if statut == "running":
        (dossier / f"{agent_id}.session.partial.json").write_text(
            json.dumps({"text": "je travaille"}), encoding="utf-8")
    agent_fiche._list_agents_cache.clear()
    agent_registre._agent_file_cache.clear()
    store._status_cache.clear()


def _page_agents(client) -> dict[str, dict]:
    """Ce que montre la page Agents (même route, même pagination que `list.js`), recalculé à
    l'instant : les pages mémorisées sont jetées, SANS périmer le parc (`expire_all` changerait
    la génération à lui seul) ni vider le registre des états montrés."""
    with fleet_cache._registry_lock:
        fleet_cache._entries.clear()
    noeuds = client.get("/api/agents/tree?offset=0&limit=40").get_json()["nodes"]
    return {n["agent_id"]: n for n in noeuds}


def test_pastille_en_cours_suit_la_page_agents_apres_un_changement_d_etat(client, parc):
    _agent_vivant(parc, "agentpastil1", "running")
    assert _page_agents(client)["agentpastil1"]["etat"] == "running"
    assert client.get("/api/nav/counts").get_json()["en_cours"] == 1

    #  L'agent pose une question : son process l'écrit, aucune tâche ne change.
    _ipc(parc, "agentpastil1", "awaiting_input")
    assert _page_agents(client)["agentpastil1"]["etat"] == "awaiting_input"

    assert client.get("/api/nav/counts").get_json()["en_cours"] == 0


def test_pastille_a_moi_invalidee_par_un_changement_d_etat_d_agent(client, parc):
    """La question apparaît dans la boîte ET dans la pastille sans attendre la péremption."""
    _agent_vivant(parc, "agentpastil2", "running")
    _page_agents(client)
    avant = client.get("/api/nav/counts").get_json()["a_moi"]
    assert client.get("/api/inbox").get_json()["compte"] == avant

    _ipc(parc, "agentpastil2", "awaiting_input")
    _page_agents(client)  # la page Agents montre la question : l'état d'agent a changé

    boite = client.get("/api/inbox").get_json()
    assert [c["agent_id"] for c in boite["items"] if c["type"] == "question"] == ["agentpastil2"]
    assert client.get("/api/nav/counts").get_json()["a_moi"] == boite["compte"] == avant + 1


def test_pastille_a_moi_egale_la_boite_recalculee(client, parc, horloge):
    """La boîte vient d'être recalculée (sa mémoire de 3 s était passée) : la pastille lue
    juste après montre le MÊME compte, pas celui de sa propre copie d'il y a 5 s."""
    _agent_vivant(parc, "agentpastil3", "running")
    avant = client.get("/api/nav/counts").get_json()["a_moi"]

    horloge.avancer(5)
    _ipc(parc, "agentpastil3", "awaiting_input")
    boite = client.get("/api/inbox").get_json()
    assert boite["compte"] == avant + 1

    assert client.get("/api/nav/counts").get_json()["a_moi"] == boite["compte"]


def test_pastilles_en_regime_etabli_ne_recalculent_rien_pendant_la_requete(client, parc, horloge,
                                                                           monkeypatch):
    """Le gain de 40defecf est gardé : passé la mémoire, sans changement, la pastille répond
    sans reconstruire ni la boîte ni l'arbre pendant la requête (recalcul en fond)."""
    monkeypatch.setattr(fleet_cache, "TTL_SECONDS", 0.0)  # toute page d'arbre est déjà périmée
    _agent_vivant(parc, "agentpastil4", "running")
    _page_agents(client)
    client.get("/api/nav/counts")
    _attendre_les_recalculs_en_fond()
    horloge.avancer(5)

    lache = threading.Event()
    appels = []

    def bloquant(nom, vrai):
        def f(*a, **k):
            appels.append((nom, threading.current_thread().name))
            lache.wait(5)
            return vrai(*a, **k)
        return f

    monkeypatch.setattr(inbox, "_construire", bloquant("boite", inbox._construire))
    monkeypatch.setattr(fleet, "_agent_tree_uncached", bloquant("arbre", fleet._agent_tree_uncached))
    try:
        t0 = time.perf_counter()
        comptes = client.get("/api/nav/counts").get_json()
        duree = time.perf_counter() - t0
    finally:
        lache.set()
    assert comptes["en_cours"] == 1
    assert duree < 1.0, f"pastilles recalculées pendant la requête ({duree:.2f} s) : {appels}"
