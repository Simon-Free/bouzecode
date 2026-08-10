"""FIX 5a (suite) — un run work en 'starting' est ACTIF, donc derive_state != work_done.

Sans le fix, 'starting' n'était pas dans workflow._ACTIVE : un run work fraîchement
lancé (worktree provisionné, process pas confirmé vivant) était vu non-actif →
derive_state = 'work_done' ~5 s après le start → test-gate + spawn_validator sur un
worktree ENCORE VIDE → no_diff verrouillé. Un run 'starting' doit rendre le ticket 'busy'.
"""
from bouzecode.web_v2.services.work import workflow


def _ticket(run_state):
    return {
        "id": "tk01",
        "worktree": {"state": "provisioned"},
        "runs": [
            {"agent_id": "coder01", "kind": "work", "state": run_state,
             "verdict": None},
        ],
    }


def test_starting_run_is_busy_not_workdone():
    """Un run work en 'starting' → derive_state = 'busy' (PAS work_done)."""
    assert workflow.derive_state(_ticket("starting")) == "busy"


def test_running_run_is_busy():
    """Non-régression : un run 'running' reste 'busy'."""
    assert workflow.derive_state(_ticket("running")) == "busy"


def test_finished_run_is_not_busy():
    """Non-régression : un run 'finished' n'est plus 'busy' (le workflow peut avancer)."""
    assert workflow.derive_state(_ticket("finished")) != "busy"


def test_starting_in_active_set():
    """Garde directe : 'starting' fait bien partie de _ACTIVE."""
    assert "starting" in workflow._ACTIVE
