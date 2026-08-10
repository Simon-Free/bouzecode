"""Fix 3 — _reconcile_graceful_close retire le faux flag 'crashed'.

Cas réel 86c37f5a : un manager clos gracieusement (close_reason=final_answer) mais dont le
watchdog avait posé crashed pendant la fenêtre process-mort/stamp. La réconciliation marque
le run completed ET doit retirer ce faux crash — sinon le ticket resterait 'planté'.
Fakes purs + monkeypatch des répertoires (aucun unittest.mock, aucun git, aucun LLM).
"""
import json
from pathlib import Path

from bouzecode.web_v2.services.work import wake
from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.services.work import _persistence
from bouzecode.web_v2.runtime import runner


def test_reconcile_gracieux_retire_le_faux_crashed(tmp_path, monkeypatch):
    slug = "proj"
    agent_id = "gracefuldead042"

    monkeypatch.setattr(runner, "AGENTS_DIR", tmp_path)
    monkeypatch.setattr(_persistence, "TICKETS_DIR", tmp_path)
    monkeypatch.setattr(tickets_svc, "TICKETS_DIR", tmp_path)
    monkeypatch.setattr(runner, "load_agent", lambda aid: None)

    session = tmp_path / f"{agent_id}.session.json"
    session.write_text(
        json.dumps({"messages": [{"role": "assistant", "content": "VERDICT: OK"}],
                    "close_reason": "final_answer"}),
        encoding="utf-8",
    )

    # Ticket faussement 'planté' par le watchdog, run non completed / sans verdict.
    ticket = {"id": "t1", "crashed": True, "runs": [{"agent_id": agent_id}]}
    _persistence._save(slug, [ticket])

    wake._reconcile_graceful_close(slug, ticket)

    # Le run est réconcilié ET le faux crash est retiré → plus affiché 'planté'.
    assert ticket["runs"][0].get("completed") is True
    assert ticket.get("crashed") in (None, False)
    persisted = _persistence._load(slug)[0]
    assert persisted.get("crashed") in (None, False)
    assert tickets_svc.derive_status(persisted) != "planté"


def _make_dead_agent(tmp_path, monkeypatch, agent_id, close_reason, ipc_state):
    """Fabrique un agent au pid MORT + sa session disque, et neutralise psutil/IPC.

    reconcile_dead_agents lit AGENTS_DIR.glob('*.json') → _agent_from_dict →
    psutil.pid_exists(pid) → get_ipc_state(agent). On simule un pid mort
    (pid_exists→False) et on contrôle l'état IPC renvoyé."""
    monkeypatch.setattr(runner, "AGENTS_DIR", tmp_path)
    monkeypatch.setattr(runner.psutil, "pid_exists", lambda pid: False)
    monkeypatch.setattr(runner, "get_ipc_state", lambda agent: ipc_state)

    session = tmp_path / f"{agent_id}.session.json"
    session.write_text(json.dumps({"close_reason": close_reason}), encoding="utf-8")

    (tmp_path / f"{agent_id}.json").write_text(
        json.dumps({
            "agent_id": agent_id,
            "prompt": "p",
            "model": "m",
            "cwd": str(tmp_path),
            "pid": 999999,
            "started_at": "2026-01-01T00:00:00Z",
            "session_path": str(session),
            "returncode": None,
        }),
        encoding="utf-8",
    )
    return tmp_path / f"{agent_id}.json"


def test_reconcile_deferred_close_non_crashed(tmp_path, monkeypatch):
    """Un agent clos sur final_answer_deferred (clôture GRACIEUSE) dont l'IPC n'est
    PAS 'finished' au boot NE doit PAS être stampé crashed : le chemin BOOT doit,
    comme le chemin CHAUD, dériver le rc du close_reason disque (via
    _returncode_from_session) → rc=0, hors crashed_ids. Sans le fix il ressortait -1
    (bandeau 'interrompu (crash ou redémarrage). Reprendre ?')."""
    agent_id = "deferreddead01"
    path = _make_dead_agent(tmp_path, monkeypatch, agent_id,
                            close_reason="final_answer_deferred", ipc_state={})

    crashed = runner.reconcile_dead_agents()

    assert agent_id not in crashed
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted.get("returncode") == 0


def test_reconcile_true_crash_reste_crashed(tmp_path, monkeypatch):
    """Garde-fou : une VRAIE mort non-gracieuse (close_reason vide, IPC non finished)
    reste crashed (rc=-1, dans crashed_ids). Le fix ne masque pas les vrais crashs."""
    agent_id = "truecrashdead1"
    path = _make_dead_agent(tmp_path, monkeypatch, agent_id,
                            close_reason="", ipc_state={})

    crashed = runner.reconcile_dead_agents()

    assert agent_id in crashed
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted.get("returncode") == -1


def test_reconcile_awaiting_input_non_crashed(tmp_path, monkeypatch):
    """Garde-fou : un agent en attente utilisateur (IPC awaiting_input) garde rc=0 et
    reste hors crashed_ids — comportement préservé par le fix."""
    agent_id = "awaitingdead01"
    path = _make_dead_agent(tmp_path, monkeypatch, agent_id,
                            close_reason="", ipc_state={"status": "awaiting_input"})

    crashed = runner.reconcile_dead_agents()

    assert agent_id not in crashed
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted.get("returncode") == 0
