"""FIX — follow-up sur agent terminé : il re-tourne mais reste affiché "Terminé".

Cause : store._status_cache mémorise l'état 'finished' d'un agent SANS TTL. Quand
l'utilisateur pose une follow-up (POST /api/agents/<id>/continue -> runner.continue_agent
qui RESPAWN le process), le cache n'était jamais purgé. agent_status() court-circuite en
tête sur ce cache -> renvoie 'finished' à vie, même process vivant -> la sidebar classe
l'agent en « Terminés » alors qu'il avance.

Fix : store.invalidate_status(agent_id) purge l'entrée cache, appelé par l'endpoint
/continue après le respawn. Le prochain agent_status() recalcule et voit is_running=True
-> 'running' -> sidebar « En cours ».
"""
from bouzecode.web_v2.services.sessions import store


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
    monkeypatch.setattr(store.runner, "refresh_agent_status", lambda a: a)
    monkeypatch.setattr(store.runner, "get_ipc_state", lambda a: ipc or {})
    monkeypatch.setattr(store.runner, "is_running", lambda a: running)
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
    """Le bug user : agent 'finished' caché, respawné (is_running=True). Sans invalidation
    agent_status renvoie 'finished' (cache). Après invalidate_status il recalcule -> 'running'."""
    _wire(monkeypatch, running=True)
    sess = tmp_path / "cont.session.json"
    sess.write_text("[]", encoding="utf-8")
    agent = _FakeAgent(returncode=0, session_path=str(sess))

    # Simule l'état après un premier run terminé : 'finished' figé dans le cache.
    store._status_cache[agent.agent_id] = {"state": "finished"}
    assert store.agent_status(agent)["state"] == "finished"  # cache court-circuite

    # Follow-up : l'endpoint /continue purge le cache.
    store.invalidate_status(agent.agent_id)

    # Le process est vivant (respawn) -> recalcul -> 'running' -> sidebar « En cours ».
    assert store.agent_status(agent)["state"] == "running"
