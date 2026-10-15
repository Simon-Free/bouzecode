"""Le `parent` d'un agent se relit sur sa fiche ; une fiche ancienne sans parent reste valide.

(Le routage par intention qu'éprouvait ce fichier — `dispatch.resolve_routing`, `needs_project` —
a été retiré au lot L6 : un ticket se crée toujours sur un projet EXPLICITE.)"""
from bouzecode.web_v2.runtime.runner import agent_fiche


def test_agent_parent_round_trips():
    """Un parent persisté se relit ; un JSON legacy sans parent reste valide."""
    data = {"agent_id": "abc", "prompt": "p", "model": "m", "cwd": "c",
            "pid": 1, "started_at": "t", "parent": "dispatcher:manual"}
    agent = agent_fiche._agent_from_dict(data)
    assert agent.parent == "dispatcher:manual"

    legacy = {k: v for k, v in data.items() if k != "parent"}
    assert agent_fiche._agent_from_dict(legacy).parent == ""
