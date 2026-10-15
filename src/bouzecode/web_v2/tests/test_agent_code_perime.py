# [desc] Un agent qui tourne sur un code antérieur au HEAD du dépôt est signalé : sha de démarrage enregistré dans sa session, servi par /blocks avec le drapeau code_stale. [/desc]
"""Le 21/09, des agents lancés le 09/09 tournaient toujours sur leur code d'origine : bugs
« déjà corrigés » encore visibles, et leur session annonçait pourtant le NOUVEAU commit
(`bouzecode_commit` est relu sur le disque à chaque run). La session enregistre désormais
le commit que le process a CHARGÉ (`bouzecode_boot_commit`), et l'interface le compare au
HEAD courant du dépôt."""
from __future__ import annotations

import json

import pytest

from bouzecode.web_v2.services.sessions import store

HEAD = "f" * 40


@pytest.fixture()
def client_pour(tmp_path, monkeypatch):
    def _client(session: dict):
        session_file = tmp_path / "session.json"
        session_file.write_text(json.dumps(session), encoding="utf-8")
        ref = store.SessionRef(key="agent-x", kind="daily", path=session_file)
        monkeypatch.setattr(store, "resolve", lambda key: ref)
        from bouzecode.web_v2 import version
        monkeypatch.setattr(version, "current_head_sha", lambda: HEAD)
        from bouzecode.web_v2.app import create_app
        app = create_app()
        app.config["TESTING"] = True
        return app.test_client()
    return _client


def _meta(client):
    resp = client.get("/api/sessions/agent-x/blocks")
    assert resp.status_code == 200
    return resp.get_json()["meta"]


def test_agent_demarre_sur_un_commit_anterieur_est_signale(client_pour):
    meta = _meta(client_pour({"messages": [], "bouzecode_boot_commit": "a" * 40,
                              "bouzecode_commit": HEAD[:8]}))
    assert meta["code_boot_sha"] == "a" * 40
    assert meta["code_head_sha"] == HEAD
    assert meta["code_stale"] is True


def test_agent_a_jour_n_est_pas_signale(client_pour):
    meta = _meta(client_pour({"messages": [], "bouzecode_boot_commit": HEAD}))
    assert meta["code_stale"] is False


def test_session_ancienne_sans_sha_de_demarrage_n_est_pas_signalee(client_pour):
    """Pas de fausse alerte sur les sessions écrites avant ce champ."""
    meta = _meta(client_pour({"messages": [], "bouzecode_commit": "1234abcd"}))
    assert meta["code_stale"] is False


def test_la_boucle_enregistre_le_commit_charge_dans_la_session():
    from bouzecode.backend.agent.state import AgentState
    from bouzecode.backend.agent import loop
    from bouzecode.backend.core.code_version import BOOT
    from bouzecode.backend.commands.session import session as sess
    state = AgentState()
    loop._stamp_code_version(state)
    assert state.bouzecode_boot_commit == BOOT.boot_sha
    assert sess._build_session_data(state)["bouzecode_boot_commit"] == BOOT.boot_sha
