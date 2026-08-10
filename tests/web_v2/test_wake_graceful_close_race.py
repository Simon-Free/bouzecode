"""Course wake : un run dont la session DISQUE porte un close_reason GRACIEUX mais dont le
PROCESS est mort SANS que POST /completed soit passé (callback perdu, agent déchargé) NE
doit JAMAIS être routé vers CRASH/plante. La clôture gracieuse doit être rejouée
(mark_run_completed) et PRIMER sur la détection crash — pour TOUS les close_reasons
gracieux (final_answer, final_answer_deferred, text_no_tools), pas seulement final_answer.

Zéro unittest.mock : vraie session JSON sur disque + monkeypatch pytest sur les
répertoires (AGENTS_DIR/TICKETS_DIR) et runner.load_agent (agent déchargé = None)."""
import ast
import json
from pathlib import Path

import pytest

from bouzecode.web_v2.services.work import wake, workflow
from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.services.work import _persistence
from bouzecode.web_v2.runtime import runner


def _write_session(path: Path, *, close_reason: str) -> None:
    path.write_text(
        json.dumps({"messages": [{"role": "assistant", "content": "VERDICT: OK"}],
                    "close_reason": close_reason}),
        encoding="utf-8",
    )


def _persisted_run(tmp_path: Path, slug: str) -> dict:
    return _persistence._load(slug)[0]["runs"][0]


@pytest.mark.parametrize("close_reason", sorted(wake.GRACEFUL_CLOSE_REASONS))
def test_graceful_close_wins_over_crash_when_process_dead(tmp_path, monkeypatch, close_reason):
    """Pour CHAQUE close_reason gracieux, un callback /completed perdu est réconcilié
    (run marqué completed) et n'est jamais routé vers 'plante'. Le cas 'final_answer_deferred'
    est le bug réel observé (ticket T6 bloqué 'à relire' malgré un commit prêt)."""
    slug = "proj"
    agent_id = "gracefuldead001"

    # Répertoires isolés dans tmp (session sidecar + tickets).
    monkeypatch.setattr(runner, "AGENTS_DIR", tmp_path)
    monkeypatch.setattr(_persistence, "TICKETS_DIR", tmp_path)
    monkeypatch.setattr(tickets_svc, "TICKETS_DIR", tmp_path)
    # Agent DÉCHARGÉ (nettoyé après mort du process) → load_agent renvoie None.
    monkeypatch.setattr(runner, "load_agent", lambda aid: None)

    # La session DISQUE prouve une clôture gracieuse, callback /completed PERDU.
    _write_session(tmp_path / f"{agent_id}.session.json", close_reason=close_reason)

    # Ticket persisté avec un run NON completed, SANS verdict (le hook n'est jamais passé).
    ticket = {"id": "t1", "runs": [{"agent_id": agent_id}]}
    _persistence._save(slug, [ticket])

    wake._reconcile_graceful_close(slug, ticket)
    wake._stamp_liveness(slug, ticket)

    # Le run est marqué completed sur le DISQUE (persistance via mark_run_completed).
    assert _persisted_run(tmp_path, slug).get("completed") is True, \
        f"clôture gracieuse '{close_reason}' non rejouée"
    # Et la détection crash ne le route JAMAIS vers 'plante'.
    assert workflow._is_crash(ticket) is False


def test_non_graceful_close_is_not_reconciled(tmp_path, monkeypatch):
    """Un close_reason NON gracieux (ex 'partial_stream', 'cancelled') ne doit PAS être
    marqué completed : il n'a pas fini proprement, la voie CRASH reste légitime."""
    slug, agent_id = "proj", "brokendead001"
    monkeypatch.setattr(runner, "AGENTS_DIR", tmp_path)
    monkeypatch.setattr(_persistence, "TICKETS_DIR", tmp_path)
    monkeypatch.setattr(tickets_svc, "TICKETS_DIR", tmp_path)
    monkeypatch.setattr(runner, "load_agent", lambda aid: None)
    _write_session(tmp_path / f"{agent_id}.session.json", close_reason="partial_stream")
    ticket = {"id": "t1", "runs": [{"agent_id": agent_id}]}
    _persistence._save(slug, [ticket])

    wake._reconcile_graceful_close(slug, ticket)

    assert ticket["runs"][0].get("completed") is not True


def test_deferred_close_gated_until_checks_drain(tmp_path, monkeypatch):
    """Un close `final_answer_deferred` dont les checks différés ne sont PAS encore drainés
    (`<session>.deferred.json` encore sur disque) NE doit PAS être marqué completed :
    l'avancer validerait/mergerait avant que le déploiement en file ne tourne. Une fois le
    drain terminé (fichier supprimé), la réconciliation normale reprend."""
    slug, agent_id = "proj", "deferredpending01"
    monkeypatch.setattr(runner, "AGENTS_DIR", tmp_path)
    monkeypatch.setattr(_persistence, "TICKETS_DIR", tmp_path)
    monkeypatch.setattr(tickets_svc, "TICKETS_DIR", tmp_path)
    monkeypatch.setattr(runner, "load_agent", lambda aid: None)
    _write_session(tmp_path / f"{agent_id}.session.json", close_reason="final_answer_deferred")
    # File différée encore pendante sur disque (le drain n'a pas encore réussi).
    deferred_file = tmp_path / f"{agent_id}.session.json.deferred.json"
    deferred_file.write_text(
        json.dumps({"answer": "deploying", "checks": [{"command": "deploy", "timeout": 900}]}),
        encoding="utf-8")
    ticket = {"id": "t1", "runs": [{"agent_id": agent_id}]}
    _persistence._save(slug, [ticket])

    wake._reconcile_graceful_close(slug, ticket)
    assert _persisted_run(tmp_path, slug).get("completed") is not True, \
        "close deferred réconcilié AVANT le drain de ses checks (merge prématuré)"

    # Drain terminé : le fichier disparaît → la réconciliation gracieuse reprend.
    deferred_file.unlink()
    wake._reconcile_graceful_close(slug, ticket)
    assert _persisted_run(tmp_path, slug).get("completed") is True


def test_graceful_reasons_stay_in_sync_with_loop_fire_completion():
    """GARDE ANTI-DIVERGENCE : tout close_reason passé à `_fire_completion` dans
    backend/agent/loop.py DOIT faire avancer le ticket côté reconciler. Sinon un agent qui a
    déclenché `on_completion` — donc fini proprement — reste « à relire » indéfiniment :
    c'est le bug qu'avait causé l'omission de 'final_answer_deferred'.

    Le parse doit tolérer `_fire_completion(state, config, state.close_reason or "x")` : la
    version précédente exigeait un littéral en 3ᵉ position et est devenue AVEUGLE quand la
    boucle s'est mise à honorer le close_reason déjà posé — elle n'y voyait plus qu'une
    raison sur trois. L'égalité stricte a laissé place à une inclusion : les raisons venues
    de loop_turn.py (`ends_turn_tool`…) n'apparaissent pas ici mais avancent aussi. Le
    recouvrement complet est tenu par tests/web_v2/test_close_reasons_table.py."""
    from bouzecode.backend.agent import loop as loop_mod

    tree = ast.parse(Path(loop_mod.__file__).read_text(encoding="utf-8"))
    fired = {
        constante.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "_fire_completion" and len(node.args) >= 3
        for constante in ast.walk(node.args[2])
        if isinstance(constante, ast.Constant) and isinstance(constante.value, str)
    }
    assert fired, "aucun call site _fire_completion trouvé — le parse a-t-il changé ?"
    assert {"final_answer", "final_answer_deferred", "text_no_tools"} <= fired, (
        f"le parse ne voit plus les clôtures gracieuses connues : {sorted(fired)}")
    manquantes = sorted(fired - set(wake.GRACEFUL_CLOSE_REASONS))
    assert not manquantes, (
        f"divergence reconciler/loop : loop.py déclenche on_completion sur {manquantes}, "
        f"que le reconciler ne fait PAS avancer (GRACEFUL_CLOSE_REASONS="
        f"{sorted(wake.GRACEFUL_CLOSE_REASONS)})")
