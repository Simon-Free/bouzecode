# [desc] Robustesse du watchdog : prédicats ne throw pas sur tickets legacy malformés ;
# le constat par ticket, tick et _children_by_parent continuent malgré un throw. [/desc]
"""Zéro agent LLM. Prouve deux choses :
1. les prédicats purs (reaper.should_reap / ticket_terminal / work_delivered) renvoient un
   booléen sans lever sur des tickets legacy malformés ;
2. les drivers (constat par ticket, tick, _children_by_parent) LOGguent et CONTINUENT quand
   un ticket ou un projet lève, au lieu d'avorter tout le cycle (le bug d'origine)."""
from bouzecode.web_v2.services.work import constats, reaper, wake
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
    reaper.should_reap,
    wake.ticket_terminal,
    wake.work_delivered,
    wake.ticket_needs_watchdog,
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

def test_le_constat_continue_quand_un_ticket_leve(monkeypatch):
    seen: list[str] = []

    def espion(slug, ticket):
        seen.append(ticket["id"])
        if ticket["id"] == "boom":
            raise RuntimeError("worktree purgé : NotADirectoryError simulée")

    monkeypatch.setattr(constats, "constater", espion)
    monkeypatch.setattr(wake.conflits, "observer_resolution", lambda s, t: False)

    rows = [{"id": "a"}, {"id": "boom"}, {"id": "b"}]
    wake._constater_le_projet("proj", rows)  # ne doit PAS lever
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
