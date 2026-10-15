"""Ce que l'utilisateur lit sur une conversation de la liste des agents (`/api/agents/tree`).

Une conversation qu'il a lancée s'annonce par SON SUJET — la première ligne non vide de sa
demande, tronquée à 60 caractères — et jamais par « Agent » partout ni par le nom d'un profil
de projet. Un agent structurel (merge…) s'annonce par son rôle. Aucune heure n'est cuite
dans le libellé (le front la dérive de `started_at`). Chaque nœud dit aussi sa nature (`kind`),
qui empêche le front de promouvoir un agent structurel orphelin en racine.

Joué par la route HTTP réelle sur de VRAIS artefacts d'agent (aucun appel de fonction interne).
"""
import json

import pytest

LONG = "x" * 100


def _write_agent(agents_dir, agent_id, prompt, run_kind="work", profile="", parent=""):
    data = {
        "agent_id": agent_id, "prompt": prompt, "model": "claude-sonnet", "cwd": "",
        "pid": 999_999_999, "started_at": "2026-07-06T10:39:00Z", "returncode": 0,
        "session_path": str(agents_dir / f"{agent_id}.session.json"),
        "stdout_path": str(agents_dir / f"{agent_id}.out.log"), "ipc_dir": "",
        "parent": parent, "run_kind": run_kind, "profile": profile,
    }
    (agents_dir / f"{agent_id}.json").write_text(json.dumps(data), encoding="utf-8")
    (agents_dir / f"{agent_id}.session.json").write_text(json.dumps({"messages": []}),
                                                         encoding="utf-8")
    (agents_dir / f"{agent_id}.out.log").write_text("log", encoding="utf-8")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from bouzecode.web_v2.app import create_app
    from bouzecode.web_v2.runtime.runner import agent_fiche
    from bouzecode.web_v2.services.sessions import purge
    from bouzecode.web_v2.services.work import fleet

    d = tmp_path / "web_agents"
    d.mkdir()
    monkeypatch.setattr(agent_fiche, "AGENTS_DIR", d)
    monkeypatch.setattr(purge, "TRASH_DIR", d / "_trash")
    monkeypatch.setattr(purge, "DELETED_PATH", d / "deleted_sessions.json")
    _write_agent(d, "sujet01", "Corrige le bug X", profile="coder")
    _write_agent(d, "profil01", "Refais le dashboard", profile="demodb-powerbi-refacto")
    _write_agent(d, "vide0001", "", profile="coder")
    _write_agent(d, "multi001", "\n  \nPremière vraie ligne\nDeuxième")
    _write_agent(d, "long0001", LONG)
    _write_agent(d, "valid001", "Résous le conflit…", run_kind="merge",
                 profile="coder", parent="sujet01")
    _write_agent(d, "nokind01", "Sans nature", run_kind=None)
    agent_fiche._list_agents_cache.clear()
    fleet.clear_tree_cache()
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
    fleet.clear_tree_cache()


def _noeud(client, agent_id):
    nodes = client.get("/api/agents/tree").get_json()["nodes"]
    return next(n for n in nodes if n["agent_id"] == agent_id)


def test_une_conversation_s_annonce_par_son_sujet_pas_par_son_profil(client):
    assert _noeud(client, "sujet01")["title"] == "Corrige le bug X"
    assert _noeud(client, "profil01")["title"] == "Refais le dashboard"


def test_une_demande_vide_donne_le_libelle_neutre(client):
    assert _noeud(client, "vide0001")["title"] == "Agent"


def test_le_sujet_est_la_premiere_ligne_non_vide(client):
    assert _noeud(client, "multi001")["title"] == "Première vraie ligne"
    assert _noeud(client, "multi001")["title_full"].startswith("Première vraie ligne")


def test_un_sujet_trop_long_est_tronque_a_60_caracteres(client):
    assert _noeud(client, "long0001")["title"] == "x" * 60
    assert _noeud(client, "long0001")["title_full"] == LONG


def test_un_agent_structurel_s_annonce_par_son_role_et_sa_nature(client):
    noeud = _noeud(client, "valid001")
    assert noeud["title"] == "Merge"
    assert noeud["kind"] == "merge"


def test_chaque_noeud_dit_sa_nature(client):
    assert _noeud(client, "sujet01")["kind"] == "work"
    assert _noeud(client, "nokind01")["kind"] == ""


def test_aucune_heure_n_est_cuite_dans_le_libelle(client):
    for agent_id in ("sujet01", "valid001", "vide0001"):
        noeud = _noeud(client, agent_id)
        assert "10:39" not in noeud["title"]
        assert noeud["started_at"] == "2026-07-06T10:39:00Z"
