# [desc] Teste que wake._reconcile_api_crash route un run api_error mort vers crash sans lancer le validateur. [/desc]
"""Un codeur tué par une panne provider persistante (close_reason=api_error sur la
session disque, process mort) NE DOIT PAS déclencher le validateur : le reconciler
`wake._reconcile_api_crash` route DIRECTEMENT vers la transition CRASH terminale
(`workflow._act_report_crash`), rendant le ticket VISIBLEMENT `crashed`.

Deux tests espionnaient ici un `integration.spawn_validator` qui n'existe PLUS : la chaîne
automatique travail→validation→merge a été retirée avec l'orchestration p10 (cf. l'en-tête
de `services/work/workflow.py`). L'espion ne prouvait donc plus rien et cassait à
l'installation. La garantie qui compte survit et est vérifiée : le run est signalé CRASHÉ et
n'est PAS marqué `completed` — or `completed` était la seule porte d'entrée d'une validation."""
from __future__ import annotations

from pathlib import Path

from bouzecode.web_v2.services.work import wake, workflow


def _tk(runs):
    return {"id": "t1", "title": "T", "prompt": "do",
            "worktree": {"state": "provisioned", "worktree": "/wt"}, "runs": runs}


def test_work_text_no_tools_routes_crash_not_validate(monkeypatch):
    """Un run WORK clos sur `text_no_tools` (codeur arrêté EN PLEIN MILIEU : tour fini sur
    du texte, sans tool_calls ni FinalAnswer) NE DOIT PAS être validé : le reconciler
    gracieux route vers CRASH (`workflow._act_report_crash`) et ne marque PAS le run
    `completed` — donc rien ne peut se présenter comme une livraison à valider."""
    tk = _tk([{"agent_id": "dead", "kind": "work"}])
    fake = type("A", (), {"session_path": "/s"})()
    monkeypatch.setattr(wake.runner, "load_agent", lambda aid: fake)
    monkeypatch.setattr(wake.runner, "is_running", lambda agent: False)
    monkeypatch.setattr(wake.store, "load_session_json",
                        lambda p: {"close_reason": "text_no_tools"})
    monkeypatch.setattr(wake.web_deferred, "exists", lambda p: False)

    crashed: list[tuple] = []
    completed: list[tuple] = []
    monkeypatch.setattr(workflow, "_act_report_crash",
                        lambda s, t, d: crashed.append((s, t["id"], d)))
    monkeypatch.setattr(wake.tickets_svc, "mark_run_completed",
                        lambda s, t, a: completed.append((s, t["id"], a)))

    wake._reconcile_graceful_close("proj", tk)

    assert crashed == [("proj", "t1", "")]  # WORK abandonné mid-turn → routé crash
    assert completed == []  # PAS marqué completed : rien à présenter comme livraison


def test_validate_text_no_tools_still_graceful(monkeypatch):
    """Non-régression sens inverse : un run VALIDATE clos sur `text_no_tools` est LÉGITIME
    (le verdict du validateur est dans le texte) → reste une clôture gracieuse
    (`mark_run_completed`), JAMAIS routé vers crash."""
    tk = _tk([{"agent_id": "judge", "kind": "validate"}])
    fake = type("A", (), {"session_path": "/s"})()
    monkeypatch.setattr(wake.runner, "load_agent", lambda aid: fake)
    monkeypatch.setattr(wake.runner, "is_running", lambda agent: False)
    monkeypatch.setattr(wake.store, "load_session_json",
                        lambda p: {"close_reason": "text_no_tools"})
    monkeypatch.setattr(wake.web_deferred, "exists", lambda p: False)

    crashed: list[tuple] = []
    completed: list[tuple] = []
    monkeypatch.setattr(workflow, "_act_report_crash",
                        lambda s, t, d: crashed.append((s, t["id"], d)))
    monkeypatch.setattr(wake.tickets_svc, "mark_run_completed",
                        lambda s, t, a: completed.append((s, t["id"], a)))

    wake._reconcile_graceful_close("proj", tk)

    assert crashed == []  # validate + text_no_tools = clôture gracieuse légitime
    assert completed == [("proj", "t1", "judge")]  # marqué completed normalement


def test_api_error_run_routes_to_crash_not_validate(monkeypatch):
    """Une session close sur `api_error` avec son process mort est signalée CRASHÉE, pas livrée."""
    tk = _tk([{"agent_id": "dead", "kind": "work"}])
    fake = type("A", (), {"session_path": "/s"})()
    monkeypatch.setattr(wake.runner, "load_agent", lambda aid: fake)
    monkeypatch.setattr(wake.runner, "is_running", lambda agent: False)
    monkeypatch.setattr(wake.store, "load_session_json",
                        lambda p: {"close_reason": "api_error", "close_detail": "BadRequestError: BedrockException"})

    crashed: list[tuple] = []
    completed: list[tuple] = []
    monkeypatch.setattr(workflow, "_act_report_crash",
                        lambda s, t, d: crashed.append((s, t["id"], d)))
    monkeypatch.setattr(wake.tickets_svc, "mark_run_completed",
                        lambda s, t, a: completed.append((s, t["id"], a)))

    wake._reconcile_api_crash("proj", tk)

    assert crashed == [("proj", "t1", "")]  # routé vers crash
    assert completed == []  # panne provider ≠ livraison


def test_graceful_close_is_not_treated_as_api_crash(monkeypatch):
    """Un run sans close_reason=api_error n'est PAS routé vers crash par ce reconciler."""
    tk = _tk([{"agent_id": "dead", "kind": "work"}])
    fake = type("A", (), {"session_path": "/s"})()
    monkeypatch.setattr(wake.runner, "load_agent", lambda aid: fake)
    monkeypatch.setattr(wake.runner, "is_running", lambda agent: False)
    monkeypatch.setattr(wake.store, "load_session_json", lambda p: {"close_reason": ""})

    crashed: list[tuple] = []
    monkeypatch.setattr(workflow, "_act_report_crash",
                        lambda s, t, d: crashed.append((s, t["id"], d)))

    wake._reconcile_api_crash("proj", tk)

    assert crashed == []  # pas de close_reason api_error → pas de crash report
