"""Une clôture GRACIEUSE n'est jamais lue comme un plantage.

Cas réel 86c37f5a : un manager clos gracieusement (close_reason=final_answer) avait été déclaré
planté par le watchdog pendant la fenêtre process-mort/stamp. Lot L2 : le watchdog ne conclut
qu'après `MORTS_AVANT_CRASH` constats de mort et lit alors la clôture sur disque — même pour une
fiche DÉCHARGÉE (agent absent du parc, session restée) : le ticket passe `delivered`.
Le chemin BOOT (`runner.reconcile_dead_agents`) est couvert par les tests suivants.
Fakes purs + monkeypatch des répertoires (aucun unittest.mock, aucun git, aucun LLM).
"""
import json

import pytest

from bouzecode.web_v2.runtime.runner import agent_etat, agent_fiche, agent_registre, agent_vivacite
from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.services.work.fsm import etats
from bouzecode.web_v2.tests.aides_tickets import constater_tout, en_cours


def test_reconcile_gracieux_ne_plante_pas_un_agent_decharge():
    slug = "proj"
    agent_id = "gracefuldead042"
    ticket = en_cours(slug, agent_id, typology="manager")
    agent_fiche.AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    (agent_fiche.AGENTS_DIR / f"{agent_id}.session.json").write_text(
        json.dumps({"messages": [{"role": "assistant", "content": "VERDICT: OK"}],
                    "close_reason": "final_answer", "final_answer": "VERDICT: OK"}),
        encoding="utf-8",
    )  # fiche d'agent absente : seul le parc garde la session

    constater_tout()

    persisted = tickets_svc.get_ticket(slug, ticket["id"])
    assert persisted["state"] == etats.DELIVERED
    assert persisted["runs"][0].get("completed") is True
    assert tickets_svc.derive_status(persisted) != "planté"


def _make_dead_agent(tmp_path, monkeypatch, agent_id, close_reason, ipc_state):
    """Fabrique un agent au pid MORT + sa session disque, et neutralise psutil/IPC.

    reconcile_dead_agents lit AGENTS_DIR.glob('*.json') → _agent_from_dict →
    psutil.pid_exists(pid) → get_ipc_state(agent). On simule un pid mort
    (pid_exists→False) et on contrôle l'état IPC renvoyé."""
    monkeypatch.setattr(agent_fiche, "AGENTS_DIR", tmp_path)
    monkeypatch.setattr(agent_vivacite.psutil, "pid_exists", lambda pid: False)
    monkeypatch.setattr(agent_etat, "get_ipc_state", lambda agent: ipc_state)

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

    crashed = agent_registre.reconcile_dead_agents()

    assert agent_id not in crashed
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted.get("returncode") == 0


def test_reconcile_true_crash_reste_crashed(tmp_path, monkeypatch):
    """Garde-fou : une VRAIE mort non-gracieuse (close_reason vide, IPC non finished)
    reste crashed (rc=-1, dans crashed_ids). Le fix ne masque pas les vrais crashs."""
    agent_id = "truecrashdead1"
    path = _make_dead_agent(tmp_path, monkeypatch, agent_id,
                            close_reason="", ipc_state={})

    crashed = agent_registre.reconcile_dead_agents()

    assert agent_id in crashed
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted.get("returncode") == -1


@pytest.mark.parametrize("attente", ["awaiting_input", "awaiting_plan_validation"])
def test_reconcile_un_agent_en_attente_de_l_utilisateur_n_est_pas_plante(tmp_path, monkeypatch, attente):
    """Un agent qui attend une réponse (question OU plan à valider) au moment où le serveur
    redémarre garde rc=0 et reste hors crashed_ids : l'utilisateur lui doit toujours une
    réponse, ce n'est pas un crash."""
    agent_id = "awaitingdead01"
    path = _make_dead_agent(tmp_path, monkeypatch, agent_id,
                            close_reason="", ipc_state={"status": attente})

    crashed = agent_registre.reconcile_dead_agents()

    assert agent_id not in crashed
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted.get("returncode") == 0
