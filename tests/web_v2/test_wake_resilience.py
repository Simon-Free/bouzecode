# [desc] Robustesse du hook de complétion : prédicats ne throw pas sur tickets legacy
# malformés ; _run_chain / tick / _children_by_parent continuent malgré un throw. [/desc]
"""Zéro agent LLM. Prouve deux choses :
1. les prédicats purs (reaper.is_terminal / ticket_terminal / work_delivered /
   _is_crash) renvoient un booléen sans lever sur des tickets legacy malformés ;
2. les drivers (_run_chain, tick, _children_by_parent) LOGguent et CONTINUENT quand un
   ticket ou un projet lève, au lieu d'avorter tout le cycle (le bug d'origine)."""
from bouzecode.web_v2.services.work import reaper, wake, workflow
from bouzecode.web_v2.services.work import tickets as tickets_svc


# ── (a) prédicats robustes aux tickets legacy malformés ───────────────────────

LEGACY = [
    {},                                              # ticket vide
    {"id": "1", "runs": []},                         # runs vides, pas de worktree
    {"id": "2", "runs": [{}]},                       # run sans kind ni verdict
    {"id": "3", "runs": [{"kind": "work"}]},         # work sans worktree
    {"id": "4", "runs": "nope"},                     # runs pas une liste
    {"id": "5", "worktree": "notadict", "runs": []}, # worktree pas un dict
    {"id": "6", "worktree": {"state": "provisioned"}, "runs": [{"verdict": "OK"}]},  # run sans kind
    {"id": "7", "worktree": {"state": "provisioned"}, "runs": ["x", {"kind": "work"}]},  # run non-dict
]

PREDICATES = [
    reaper.is_terminal,        # issue terminale (ex-auto_integrate_pending) portée au faucheur
    wake.ticket_terminal,
    wake.work_delivered,
    workflow._is_crash,
]


def test_predicates_never_throw_on_legacy_tickets():
    for ticket in LEGACY:
        for predicate in PREDICATES:
            result = predicate(ticket)
            assert isinstance(result, bool)


def test_derive_status_and_outcome_never_throw_on_legacy_tickets():
    for ticket in LEGACY:
        assert isinstance(tickets_svc.derive_status(ticket), str)
        assert isinstance(wake.ticket_outcome(ticket), str)


# ── (b) drivers résilients : un ticket/projet cassé ne tue pas le cycle ────────

def test_run_chain_continues_when_a_ticket_throws(monkeypatch):
    seen: list[str] = []

    def spy_advance(slug, ticket, *args, **kwargs):
        seen.append(ticket["id"])
        if ticket["id"] == "boom":
            raise RuntimeError("worktree purgé : NotADirectoryError simulée")

    monkeypatch.setattr(wake.workflow, "advance", spy_advance)
    monkeypatch.setattr(wake.reaper, "reap_ticket", lambda s, t: False)

    rows = [{"id": "a"}, {"id": "boom"}, {"id": "b"}]
    wake._run_chain("proj", rows)  # ne doit PAS lever
    assert seen == ["a", "boom", "b"]  # le ticket après le crash est bien traité


def test_tick_continues_when_a_project_throws(monkeypatch):
    monkeypatch.setattr(wake.projects, "list_projects",
                        lambda: [{"slug": "bad"}, {"slug": "good"}])

    processed: list[str] = []

    def fake_list(slug, refresh=False):
        if slug == "bad":
            raise RuntimeError("refresh cassé sur bad")
        processed.append(slug)
        return []

    monkeypatch.setattr(wake.tickets_svc, "list_tickets", fake_list)
    monkeypatch.setattr(wake, "process_wakes", lambda: [])
    # Le tick balaie aussi le warm-pool (geste GLOBAL) : sans ce stub il tuerait de vrais
    # process warm de la machine, `AGENTS_DIR` n'étant pas isolé en test.
    from bouzecode.web_v2.services.work import fleet
    monkeypatch.setattr(fleet, "sweep_warm_pool", lambda: [])

    wake.tick()  # ne doit PAS lever malgré le projet 'bad'
    assert processed == ["good"]  # le projet sain est bien traité après le crash


def test_children_by_parent_skips_broken_project(monkeypatch):
    monkeypatch.setattr(wake.projects, "list_projects",
                        lambda: [{"slug": "bad"}, {"slug": "good"}])

    def fake_list(slug, refresh=False):
        if slug == "bad":
            raise RuntimeError("refresh cassé sur bad")
        return [{"id": "1", "parent": "mgr123456789", "runs": []}]

    monkeypatch.setattr(wake.tickets_svc, "list_tickets", fake_list)

    by_parent = wake._children_by_parent()  # ne doit PAS lever
    assert list(by_parent.keys()) == ["mgr123456789"]  # seul le projet sain a contribué


# ── (c) stamp de vivacité résilient : une écriture ratée ne pollue plus les logs ──

def test_stamp_liveness_swallows_write_error(monkeypatch, caplog):
    """Régression WinError5 : la persistance best-effort de `dead_ticks` peut échouer
    (os.replace ACCESS_DENIED sous lecteurs concurrents). Ce raté NE doit PAS remonter
    jusqu'à _run_chain (qui logguerait la traceback ERROR « ticket ... a échoué »).
    On exige : pas d'exception propagée, et rien en niveau ERROR."""
    # un run sans agent vivant → dead_ticks passe 0→1 → dirty=True → update_ticket appelé
    monkeypatch.setattr(wake.runner, "load_agent", lambda aid: None)
    monkeypatch.setattr(wake.runner, "is_running", lambda a: False)

    def boom(slug, ticket):
        raise OSError(5, "Accès refusé")  # exactement le WinError 5 de prod

    monkeypatch.setattr(wake.tickets_svc, "update_ticket", boom)

    ticket = {"id": "x", "runs": [{"agent_id": "a", "dead_ticks": 0}]}
    with caplog.at_level("DEBUG"):
        wake._stamp_liveness("proj", ticket)  # ne doit PAS lever

    assert not [r for r in caplog.records if r.levelname == "ERROR"], \
        "un stamp de vivacité raté ne doit PAS produire de log ERROR"


def test_run_chain_does_not_log_error_when_liveness_write_fails(monkeypatch, caplog):
    """Bout-en-bout : même si l'écriture de liveness échoue (WinError5), _run_chain doit
    continuer et NE PAS logguer « a échoué » pour ce ticket."""
    monkeypatch.setattr(wake.runner, "load_agent", lambda aid: None)
    monkeypatch.setattr(wake.runner, "is_running", lambda a: False)
    monkeypatch.setattr(wake.tickets_svc, "update_ticket",
                        lambda s, t: (_ for _ in ()).throw(OSError(5, "Accès refusé")))
    monkeypatch.setattr(wake.workflow, "advance", lambda s, t, *a, **k: None)
    monkeypatch.setattr(wake.reaper, "reap_ticket", lambda s, t: False)

    rows = [{"id": "x", "runs": [{"agent_id": "a", "dead_ticks": 0}]}]
    with caplog.at_level("DEBUG"):
        wake._run_chain("proj", rows)  # ne doit PAS lever

    assert not any("a échoué" in r.getMessage() for r in caplog.records), \
        "l'échec best-effort du stamp ne doit pas remonter en 'ticket ... a échoué'"
