"""Le parc d'agents web pèse 1,8 Go sur le poste et rien ne bornait sa croissance. Sa
récupération se fait EN DEUX TEMPS — ranger (réversible), puis vider (irréversible, daté) —
et jamais sans confirmation explicite.

Ce que ces tests protègent avant tout : qu'un agent VIVANT ne soit JAMAIS touché. Le
2026-07-28, un manager qui tournait a été rangé deux millisecondes après qu'un prédicat a
écrit lui-même le champ dont il tirait sa conclusion.

Aucun mock : de vrais artefacts sur disque, la vraie corbeille, les vraies fonctions.
"""
import json
import os

import pytest

from bouzecode.web_v2.services.sessions import parc, purge


def _write_agent(agents_dir, agent_id, *, started_at, pid, poids=1024, returncode=0):
    """Un agent sur disque avec un log d'un poids donné.

    Un agent qui TOURNE a un pid vivant ET aucun code de sortie (`returncode=None`) : les deux
    ensemble, c'est ce que `runner.is_running` exige."""
    (agents_dir / f"{agent_id}.json").write_text(json.dumps({
        "agent_id": agent_id, "prompt": f"conversation {agent_id}", "model": "m", "cwd": "",
        "pid": pid, "started_at": started_at, "returncode": returncode,
        "session_path": str(agents_dir / f"{agent_id}.session.json"),
        "stdout_path": str(agents_dir / f"{agent_id}.out.log"),
        "ipc_dir": "", "parent": "",
    }), encoding="utf-8")
    (agents_dir / f"{agent_id}.session.json").write_text(
        json.dumps({"messages": [], "turn_count": 2}), encoding="utf-8")
    (agents_dir / f"{agent_id}.out.log").write_text("x" * poids, encoding="utf-8")
    from bouzecode.web_v2.runtime import runner
    runner._list_agents_cache.clear()


@pytest.fixture()
def agents_dir(tmp_path, monkeypatch):
    from bouzecode.web_v2.runtime import runner
    from bouzecode.web_v2.services.sessions import store

    d = tmp_path / "web_agents"
    d.mkdir()
    monkeypatch.setattr(runner, "AGENTS_DIR", d)
    monkeypatch.setattr(purge, "TRASH_DIR", d / "_trash")
    monkeypatch.setattr(purge, "DELETED_PATH", d / "deleted_sessions.json")
    monkeypatch.setattr(store, "CACHE_PATH", d / "index_cache.json")
    store._status_cache.clear()
    yield d
    runner._list_agents_cache.clear()


VIEUX = "2026-01-01T10:00:00Z"
MORT = 999_999_999  # pid libre : l'agent n'existe plus


def test_l_inventaire_dit_le_poids_du_parc_sans_rien_toucher(agents_dir):
    """Premier besoin : savoir ce que ça pèse et ce qui serait récupérable."""
    _write_agent(agents_dir, "aaaaaa", started_at=VIEUX, pid=MORT, poids=4096)

    etat = parc.inventory()

    assert etat["parc_bytes"] > 4096
    assert [row["agent_id"] for row in etat["rangeables"]] == ["aaaaaa"]
    assert (agents_dir / "aaaaaa.out.log").exists()  # rien n'a bougé


def test_un_agent_vivant_n_est_jamais_rangeable(agents_dir):
    """La garde essentielle : un agent dont le process tourne reste intouchable, même vieux."""
    _write_agent(agents_dir, "bbbbbb", started_at=VIEUX, pid=os.getpid(), returncode=None)

    etat = parc.inventory()

    assert etat["rangeables"] == []
    assert etat["vivants"] == 1


def test_un_agent_recent_est_garde_a_portee(agents_dir):
    """Un agent terminé récemment se relance, se relit : on n'y touche pas."""
    from datetime import datetime, timezone
    _write_agent(agents_dir, "cccccc",
                 started_at=datetime.now(timezone.utc).isoformat(), pid=MORT)

    etat = parc.inventory()

    assert etat["rangeables"] == []
    assert etat["recents"] == 1


def test_sans_confirmation_le_rangement_ne_fait_que_simuler(agents_dir):
    """Un module qui déplace 1,8 Go de travail sur simple appel n'a pas sa place ici."""
    _write_agent(agents_dir, "dddddd", started_at=VIEUX, pid=MORT)

    resultat = parc.reclaim()

    assert resultat["simulation"] is True
    assert resultat["candidats"] == ["dddddd"]
    assert (agents_dir / "dddddd.json").exists()


def test_le_rangement_confirme_est_reversible(agents_dir, monkeypatch):
    """Ranger déplace vers la corbeille — et `purge.restore` ramène tout : aucun octet perdu,
    et l'agent redevient joignable."""
    from bouzecode.web_v2.tests.production_isolation import autoriser_la_destruction
    autoriser_la_destruction(monkeypatch)
    _write_agent(agents_dir, "eeeeee", started_at=VIEUX, pid=MORT)

    assert parc.reclaim(confirm=True)["ranges"] == ["eeeeee"]
    assert not (agents_dir / "eeeeee.json").exists()
    assert (purge.TRASH_DIR / "eeeeee" / "eeeeee.json").exists()

    assert purge.restore("agent/eeeeee") is True
    assert (agents_dir / "eeeeee.json").exists()


def test_le_vidage_ne_touche_que_la_corbeille_et_seulement_l_ancienne(agents_dir, monkeypatch):
    """Seul geste irréversible : il ne peut atteindre QUE ce qui a été rangé d'abord, et
    seulement après le délai de sûreté. Un rangement du jour reste hors de portée."""
    from bouzecode.web_v2.tests.production_isolation import autoriser_la_destruction
    autoriser_la_destruction(monkeypatch)
    _write_agent(agents_dir, "ffffff", started_at=VIEUX, pid=MORT)
    parc.reclaim(confirm=True)

    frais = parc.empty_trash(confirm=True)  # rangé à l'instant → délai non écoulé
    assert frais["supprimes"] == []
    assert (purge.TRASH_DIR / "ffffff").exists()

    vieilli = parc.empty_trash(trash_keep_days=0, confirm=True)
    assert vieilli["supprimes"] == ["ffffff"]
    assert not (purge.TRASH_DIR / "ffffff").exists()
