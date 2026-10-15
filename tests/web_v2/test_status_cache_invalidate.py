"""FIX — follow-up sur agent terminé : il re-tourne mais reste affiché "Terminé".

Cause : store._status_cache mémorise l'état 'finished' d'un agent SANS TTL. Quand
l'utilisateur pose une follow-up (POST /api/agents/<id>/messages -> runner.continue_agent
qui RESPAWN le process), le cache n'était jamais purgé. agent_status() court-circuite en
tête sur ce cache -> renvoie 'finished' à vie, même process vivant -> la sidebar classe
l'agent en « Terminés » alors qu'il avance.

Fix : store.invalidate_status(agent_id) purge l'entrée cache, appelé par l'endpoint
/continue après le respawn. Le prochain agent_status() recalcule et voit is_running=True
-> 'running' -> sidebar « En cours ».
"""
from bouzecode.web_v2.services.sessions import store
from bouzecode.web_v2.runtime.runner import agent_etat, agent_vivacite


class _FakeAgent:
    """Mêmes champs que `runner.Agent` : `store.agent_status` passe par `runner.is_warm`,
    qui lit `pid` et `ipc_dir`. Un double amputé de champs que le vrai objet porte toujours
    lève une AttributeError qui ne dit rien du produit."""

    def __init__(self, agent_id="agentcontinue01", returncode=None, session_path="",
                 pid=0, ipc_dir=""):
        self.agent_id = agent_id
        self.returncode = returncode
        self.session_path = session_path
        self.pid = pid
        self.ipc_dir = ipc_dir


def _wire(monkeypatch, *, running, ipc=None):
    monkeypatch.setattr(agent_etat, "refresh_agent_status", lambda a: a)
    monkeypatch.setattr(agent_etat, "get_ipc_state", lambda a: ipc or {})
    monkeypatch.setattr(agent_vivacite, "is_running", lambda a: running)
    store._status_cache.clear()


def test_invalidate_pops_finished_entry(monkeypatch):
    """invalidate_status retire l'entrée cachée ; no-op si absente."""
    store._status_cache.clear()
    store._status_cache["ag1"] = {"state": "finished"}
    store.invalidate_status("ag1")
    assert "ag1" not in store._status_cache
    # no-op sur une clé absente : ne lève pas
    store.invalidate_status("ag1")
    store.invalidate_status("jamais_vu")


def test_finished_recomputed_running_after_invalidate(monkeypatch, tmp_path):
    """Le bug user : agent 'finished' caché, respawné ou relancé chaud (is_running=True).
    Même SANS invalidation explicite, un process vivant n'est jamais servi « terminé »
    (cas vécu 2026-09-24 : agent relancé « même agent » affiché « Attend ses sous-agents »)."""
    _wire(monkeypatch, running=True)
    sess = tmp_path / "cont.session.json"
    sess.write_text("[]", encoding="utf-8")
    agent = _FakeAgent(returncode=None, session_path=str(sess))

    # Simule l'état après un premier run terminé : 'finished' figé dans le cache.
    store._status_cache[agent.agent_id] = {"state": "finished"}
    # Le process est vivant -> recalcul -> 'running' -> « En cours », cache purgé.
    assert store.agent_status(agent)["state"] == "running"
    assert agent.agent_id not in store._status_cache


def test_finished_cache_still_serves_a_dead_agent(monkeypatch, tmp_path):
    """Le cache garde son utilité : un agent réellement fini (process mort) est servi du cache."""
    _wire(monkeypatch, running=False)
    agent = _FakeAgent(returncode=0, session_path=str(tmp_path / "x.session.json"))
    store._status_cache[agent.agent_id] = {"state": "finished", "marque": 1}
    assert store.agent_status(agent).get("marque") == 1
