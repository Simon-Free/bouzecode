"""GET /api/sessions : contrat rendu + propriétés de performance, sans chrono.

Dispositif repris de tests/web_v2/test_session_overview.py : tmp_path + monkeypatch des
chemins de module (DAILY_DIR, CACHE_PATH) et `runner.list_agents`.
Les fiches d'agent sont DÉRIVÉES d'une vraie fiche ~/.bouzecode/web_agents/<id>.json
(mêmes champs et mêmes valeurs : parent="dispatcher:manual", returncode=-1,
run_kind="work", ticket_slug="bouzecode").
"""
import json

import pytest

from bouzecode.web_v2.services.sessions import (
    listing_cache,
    meta_index,
    purge,
    status_cache,
    store,
)
from bouzecode.web_v2.runtime.runner import agent_etat, agent_fiche, agent_registre

AGENTS = (("aaa111aaa111", "2026-06-12T09:00:00Z"), ("bbb222bbb222", "2026-06-12T11:00:00Z"))


class Compteur:
    """Enveloppe comptante d'une fonction PUBLIQUE : elle délègue au vrai code."""

    def __init__(self, fonction):
        self._fonction = fonction
        self.appels = 0

    def __call__(self, *args, **kwargs):
        self.appels += 1
        return self._fonction(*args, **kwargs)


def _session_data(first_message: str, saved_at: str) -> dict:
    return {
        "first_message": first_message,
        "model": "sonnet",
        "turn_count": 3,
        "saved_at": saved_at,
        "close_reason": "final_answer",
        "messages": [
            {"role": "user", "content": first_message},
            {"role": "assistant", "content": "ok"},
        ],
        "recap": {"symptoms": "lenteur du listing"},
    }


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """Un ~/.bouzecode de test peuplé sur disque : 1 journée CLI + 2 agents finis."""
    daily = tmp_path / "daily"
    (daily / "2026-06-12").mkdir(parents=True)
    (daily / "2026-06-12" / "session_a.json").write_text(
        json.dumps(_session_data("Premiere question", "2026-06-12T10:00:00Z")), encoding="utf-8"
    )
    agents_dir = tmp_path / "web_agents"
    agents_dir.mkdir()
    agents = []
    for index, (agent_id, saved_at) in enumerate(AGENTS):
        session_path = agents_dir / f"{agent_id}.session.json"
        session_path.write_text(
            json.dumps(_session_data(f"Session de {agent_id}", saved_at)), encoding="utf-8"
        )
        agents.append(
            agent_fiche.Agent(
                agent_id=agent_id,
                prompt=f"Consigne donnee a {agent_id}",
                model="",
                cwd=str(tmp_path / "depot"),
                pid=23116 + index,
                started_at="2026-09-29T08:12:34.786176Z",
                finished_at="2026-09-29T08:13:43.221845Z",
                returncode=-1,
                stdout_path=str(agents_dir / f"{agent_id}.out.log"),
                session_path=str(session_path),
                ipc_dir=str(agents_dir / f"{agent_id}.ipc"),
                parent="dispatcher:manual",
                ticket_slug="bouzecode",
                ticket_id="908cac94",
                run_kind="work",
                profile="",
            )
        )
    monkeypatch.setattr(store, "DAILY_DIR", daily)
    monkeypatch.setattr(store, "CACHE_PATH", tmp_path / "index_cache.json")
    # Le fichier des statuts terminaux est dérivé de `store.CACHE_PATH` : rien à rediriger,
    # il suffit d'oublier ce qu'un test voisin aurait gardé en mémoire.
    status_cache.reset()
    monkeypatch.setattr(purge, "DELETED_PATH", tmp_path / "deleted.json", raising=False)
    monkeypatch.setattr(agent_registre, "list_agents", lambda: list(agents))
    _vider_memoires()
    yield tmp_path
    _vider_memoires()


def _vider_memoires() -> None:
    """Simule un process neuf : seuls les fichiers de cache subsistent."""
    meta_index.clear_memo()
    status_cache.reset()
    listing_cache.reset()
    for agent_id, _ in AGENTS:
        store.invalidate_status(agent_id)


def test_contrat_api_sessions(home):
    from bouzecode.web_v2.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        reponse = client.get("/api/sessions")
    assert reponse.status_code == 200
    data = reponse.get_json()

    agents = data["agents"]
    # Tri : attente d'abord, puis récence (saved_at) — bbb222 a sauvegardé à 11h.
    assert [a["key"] for a in agents] == ["agent/bbb222bbb222", "agent/aaa111aaa111"]
    attendus = {
        "key", "title", "model", "cwd", "started_at", "saved_at", "turn_count", "status",
        "archived", "close_reason", "has_recap", "profile", "category", "need_input",
        "ticket_id", "ticket_slug",
    }
    for agent in agents:
        assert attendus <= set(agent)
        assert agent["turn_count"] == 3
        assert agent["close_reason"] == "final_answer"
        assert agent["has_recap"] is True
        assert agent["need_input"] is False
        assert agent["ticket_id"] == "908cac94"

    jour = data["days"][0]
    assert jour["date"] == "2026-06-12"
    ligne = jour["sessions"][0]
    assert ligne["key"] == "daily/2026-06-12/session_a.json"
    assert ligne["title"] == "Premiere question"
    assert ligne["turn_count"] == 3
    assert ligne["saved_at"] == "2026-06-12T10:00:00Z"


def test_aucun_decodage_complet_quand_index_chaud(home, monkeypatch):
    """Une session déjà indexée n'est JAMAIS redécodée : 0 appel à load_session_json."""
    store.list_sessions()
    _vider_memoires()  # process neuf : seul l'index sur disque reste

    compteur = Compteur(store.load_session_json)
    monkeypatch.setattr(store, "load_session_json", compteur)
    resultat = store.list_sessions()

    assert compteur.appels == 0
    assert len(resultat["agents"]) == 2
    assert resultat["agents"][0]["turn_count"] == 3


def test_statut_agent_fini_relu_sans_etat_ipc(home, monkeypatch):
    """Statut d'un agent TERMINÉ servi depuis le disque : 0 lecture d'état IPC."""
    store.list_sessions()
    _vider_memoires()

    compteur = Compteur(agent_etat.get_ipc_state)
    monkeypatch.setattr(agent_etat, "get_ipc_state", compteur)
    agents = store.list_agent_sessions()

    assert compteur.appels == 0
    assert [a["status"]["state"] for a in agents] == ["finished", "finished"]


def test_index_non_reecrit_si_inchange(tmp_path):
    chemin = tmp_path / "index.json"
    meta_index.merge_into_file(chemin, {"a": {"mtime": 1.0, "meta": {"first_message": "x"}}})
    empreinte = chemin.stat().st_mtime_ns

    index = meta_index.load_index(chemin)
    meta_index.save_index(chemin, index)
    assert chemin.stat().st_mtime_ns == empreinte  # rien n'a changé : aucune écriture

    index["b"] = {"mtime": 2.0, "meta": {"first_message": "y"}}
    meta_index.save_index(chemin, index)
    assert set(meta_index.load_index(chemin)) == {"a", "b"}
