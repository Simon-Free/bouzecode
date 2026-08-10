# [desc] Tests de la machine à états réduite au crash + invariants du merge git réel déclenché à la main. [/desc]
"""Ce que le workflow fait ENCORE, et surtout ce qu'il ne fait plus.

Un travail livré ne déclenche plus rien : ni tests, ni validateur, ni merge. Ce qui
reste est le filet anti-perte : un agent mort sans clôture est signalé, et son WIP est
commité avant qu'on ne le déclare planté. Le merge, lui, ne part que si on le demande.

No unittest.mock — recorders + pytest.monkeypatch + vrai git sur un dépôt temporaire."""
from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from bouzecode.web_v2.services.work import integration, reaper, wake, workflow, worktrees


@pytest.fixture()
def rec(monkeypatch):
    """Espionne les seuls effets encore possibles : merge (manuel) et réveil du parent."""
    calls: dict[str, list] = {"merge": [], "wake": []}
    monkeypatch.setattr(integration, "integrate_ticket",
                        lambda s, t, d="": (calls["merge"].append((s, t["id"], d)) or {"ok": True}))
    monkeypatch.setattr(wake, "process_wakes", lambda: calls["wake"].append(True) or [])
    return calls


def _tk(runs, wt_state="provisioned", wt_path="/wt"):
    meta = None if wt_state is None else {"state": wt_state, "worktree": wt_path}
    return {"id": "t1", "title": "T", "prompt": "do", "worktree": meta, "runs": runs}


# ── ce qui ne s'enchaîne plus ─────────────────────────────────────────────────

def test_delivered_work_triggers_nothing_but_is_put_in_safety():
    """Un travail livré n'enchaîne toujours rien — ni test-gate, ni validateur, ni merge.

    La seule chose qu'il déclenche est la RÉCOLTE de son worktree : commiter le travail
    sur la branche de l'agent ne décide de rien, mais sans elle une livraison propre
    laissait tout en non-commité, prêt à disparaître avec le worktree (cf. delivery.py)."""
    assert workflow.TRANSITIONS == [
        workflow.Transition("work_done", "is_crash", "report_crash", "crashed"),
        workflow.Transition("validating", "is_crash", "report_crash", "crashed"),
        workflow.Transition("work_done", "delivery_unharvested", "harvest_delivery",
                            "delivered"),
    ]


def test_finished_coder_advance_is_a_noop(rec):
    """Le codeur a fini proprement : plus aucune suite automatique n'est déclenchée."""
    tk = _tk([{"agent_id": "a", "kind": "work", "completed": True}])
    assert workflow.advance("proj", tk) is None
    assert rec["merge"] == [] and rec["wake"] == []


def test_green_verdict_no_longer_merges_by_itself(rec):
    """Un verdict OK ne merge plus tout seul : l'intégration se demande explicitement."""
    tk = _tk([{"agent_id": "v", "kind": "validate", "verdict": "OK"},
              {"agent_id": "a", "kind": "work"}])
    assert workflow.advance("proj", tk) is None
    assert rec["merge"] == []


def test_red_verdict_no_longer_relaunches_the_coder(rec):
    """Un verdict KO ne relance plus le codeur : c'est au manager de le redispatcher."""
    tk = _tk([{"agent_id": "v", "kind": "validate", "verdict": "KO"},
              {"agent_id": "a", "kind": "work"}])
    assert workflow.advance("proj", tk) is None
    assert rec["merge"] == []


# ── derive_state ──────────────────────────────────────────────────────────────

def test_derive_state():
    assert workflow.derive_state(_tk([{"agent_id": "a", "kind": "work"}])) == "work_done"
    assert workflow.derive_state(_tk([{"agent_id": "v", "kind": "validate", "verdict": "OK"},
                                      {"agent_id": "a", "kind": "work"}])) == "validating"
    # Un validate SANS verdict reste 'validating' : sans chaîne, le verdict ne gouverne plus rien.
    assert workflow.derive_state(_tk([{"agent_id": "v", "kind": "validate", "verdict": None},
                                      {"agent_id": "a", "kind": "work"}])) == "validating"
    assert workflow.derive_state(_tk([], wt_state="cleaned")) == "done"
    assert workflow.derive_state(_tk([])) == "idle"
    # un AUTRE run actif → busy ; l'agent qui vient de finir est traité comme terminé.
    busy = _tk([{"agent_id": "a", "kind": "work", "state": "running"}])
    assert workflow.derive_state(busy) == "busy"
    assert workflow.derive_state(busy, done_agent="a") == "work_done"


def test_dead_run_without_flag_still_reported_as_crash():
    """Un run réellement mort (ni clos, ni verdict) reste détectable comme un plantage."""
    t = _tk([{"agent_id": "a", "kind": "work", "completed": None, "verdict": None, "pid_alive": False}])
    assert workflow.derive_state(t) == "work_done"
    assert workflow._is_crash(t) is True


def test_crashed_flag_terminal_when_no_live_run():
    """Un plantage déjà signalé est un état terminal : on ne le re-signale pas."""
    t = _tk([{"agent_id": "a", "kind": "work", "completed": None, "verdict": None, "pid_alive": False}])
    t["crashed"] = True
    assert workflow.derive_state(t) == "crashed"


def test_merge_bloque_reste_parke(rec):
    """Un merge parké (arbre principal sale) n'est plus re-tenté tout seul : il attend."""
    tk = _tk([{"agent_id": "a", "kind": "work"}], wt_state="needs_attention")
    assert workflow.derive_state(tk) == "needs_attention"
    assert workflow.advance("proj", tk) is None
    assert reaper.terminal_outcome(tk) == "needs_attention"
    assert reaper.reap_ticket("proj", tk) is False  # worktree CONSERVÉ, réintégrable


# ── crash : la garantie à ne pas perdre ───────────────────────────────────────

@pytest.fixture()
def crash_rec(monkeypatch):
    """Enregistre update_ticket (persistance du flag crashed) + process_wakes."""
    from bouzecode.web_v2.services.work import tickets as tsvc
    calls: dict[str, list] = {"updated": [], "wake": [], "merge": []}
    monkeypatch.setattr(tsvc, "update_ticket", lambda s, t: calls["updated"].append(t["id"]))
    monkeypatch.setattr(wake, "process_wakes", lambda: calls["wake"].append(True) or [])
    monkeypatch.setattr(integration, "integrate_ticket",
                        lambda s, t, d="": calls["merge"].append(t["id"]) or {"ok": True})
    return calls


def test_is_crash_predicate_pure():
    """Seul un process mort SANS clôture ni verdict compte comme un plantage."""
    assert workflow._is_crash(_tk([{"agent_id": "a", "kind": "work", "pid_alive": False}]))
    assert not workflow._is_crash(
        _tk([{"agent_id": "a", "kind": "work", "pid_alive": False, "completed": True}]))
    assert not workflow._is_crash(_tk([{"agent_id": "a", "kind": "work", "pid_alive": True}]))
    assert not workflow._is_crash(_tk([{"agent_id": "a", "kind": "work"}]))
    assert not workflow._is_crash(
        _tk([{"agent_id": "v", "kind": "validate", "pid_alive": False, "verdict": "OK"}]))


def test_crash_work_done_reports_and_wakes(crash_rec):
    """Un codeur planté est signalé sur son ticket et son manager est réveillé."""
    tk = _tk([{"agent_id": "a", "kind": "work", "pid_alive": False}])
    nxt = workflow.advance("proj", tk)
    assert nxt == "crashed"
    assert tk["crashed"] is True
    assert crash_rec["updated"] == ["t1"] and crash_rec["wake"] == [True]
    assert crash_rec["merge"] == []  # un crash ne merge JAMAIS
    assert "pid_alive" not in tk["runs"][0]  # champ transitoire non persisté


def test_crash_validating_never_merges(crash_rec):
    """Un validateur planté est signalé lui aussi, et ne déclenche aucun merge."""
    tk = _tk([{"agent_id": "v", "kind": "validate", "pid_alive": False},
              {"agent_id": "a", "kind": "work", "completed": True}])
    assert workflow.advance("proj", tk) == "crashed"
    assert crash_rec["merge"] == []


def test_completed_run_is_not_a_crash(crash_rec):
    """Un agent qui a rendu sa copie avant de mourir n'est pas déclaré planté."""
    tk = _tk([{"agent_id": "a", "kind": "work", "pid_alive": False, "completed": True}])
    assert workflow.advance("proj", tk) is None
    assert not tk.get("crashed")


def test_crash_is_idempotent(crash_rec):
    """Signaler deux fois le même plantage ne produit ni doublon ni second réveil."""
    tk = _tk([{"agent_id": "a", "kind": "work", "pid_alive": False}])
    tk["crashed"] = True
    assert workflow.derive_state(tk) == "crashed"
    assert workflow.advance("proj", tk) is None
    assert crash_rec["updated"] == [] and crash_rec["wake"] == []


def test_crashed_ticket_is_terminal():
    """Un ticket planté est terminal : le manager peut être réveillé dessus."""
    tk = _tk([{"agent_id": "a", "kind": "work", "pid_alive": False}])
    tk["crashed"] = True
    assert workflow.is_terminal(tk) is True


def _dead_project(monkeypatch, tk):
    from bouzecode.web_v2.services.work import fleet, projects, tickets as tsvc
    monkeypatch.setattr(projects, "list_projects", lambda: [{"slug": "proj"}])
    monkeypatch.setattr(tsvc, "list_tickets", lambda slug, refresh=False, done_agent="": [tk])
    # Agent RÉEL (et non un stub anonyme) : le tick rafraîchit l'état du run avant de
    # réconcilier, et `store.agent_status` lit de vrais champs. `returncode` posé → "finished".
    dead = wake.runner.Agent(agent_id="dead", prompt="p", model="m", cwd="", pid=4_000_000,
                             started_at="2026-07-27T10:00:00", returncode=-1)
    monkeypatch.setattr(wake.runner, "load_agent", lambda aid: dead if aid == "dead" else None)
    monkeypatch.setattr(wake.runner, "is_running", lambda agent: False)  # process mort
    # Le tick balaie aussi le warm-pool (geste GLOBAL, hors sujet ici) : sans ce stub il
    # tuerait de vrais process warm de la machine, `AGENTS_DIR` n'étant pas isolé.
    monkeypatch.setattr(fleet, "sweep_warm_pool", lambda: [])


def test_watchdog_transient_death_is_debounced(crash_rec, monkeypatch):
    """Une disparition fugace du process ne fait pas déclarer l'agent planté."""
    tk = _tk([{"agent_id": "dead", "kind": "work"}])
    _dead_project(monkeypatch, tk)
    wake.tick()                                    # 1re observation morte
    assert not tk.get("crashed") and not tk.get("reaped")
    assert tk["runs"][0]["dead_ticks"] == 1


def test_watchdog_confirmed_death_marks_crashed(crash_rec, monkeypatch):
    """Un agent vraiment mort finit signalé, et son worktree est conservé pour la reprise."""
    tk = _tk([{"agent_id": "dead", "kind": "work"}])
    _dead_project(monkeypatch, tk)
    for _ in range(wake._CRASH_DEAD_TICKS):
        wake.tick()
    assert tk.get("crashed") is True
    assert tk.get("reaped") is None      # worktree CONSERVÉ (reprenable), pas fauché
    assert "t1" in crash_rec["updated"]


def test_stamp_liveness_debounce_and_reset(monkeypatch):
    """Deux morts consécutives condamnent ; revoir l'agent vivant remet le compteur à zéro."""
    from bouzecode.web_v2.services.work import tickets as tsvc
    monkeypatch.setattr(tsvc, "update_ticket", lambda s, t: None)
    monkeypatch.setattr(wake.runner, "load_agent", lambda aid: object())
    tk = _tk([{"agent_id": "a", "kind": "work"}])

    monkeypatch.setattr(wake.runner, "is_running", lambda agent: False)
    wake._stamp_liveness("proj", tk)
    assert tk["runs"][0]["dead_ticks"] == 1 and tk["runs"][0]["pid_alive"] is True   # debounce
    wake._stamp_liveness("proj", tk)
    assert tk["runs"][0]["dead_ticks"] == 2 and tk["runs"][0]["pid_alive"] is False  # confirmé

    monkeypatch.setattr(wake.runner, "is_running", lambda agent: True)
    wake._stamp_liveness("proj", tk)
    assert tk["runs"][0]["dead_ticks"] == 0 and tk["runs"][0]["pid_alive"] is True   # reset


def test_reconcile_replays_lost_completion(monkeypatch):
    """Un agent qui a fini pendant un redémarrage serveur n'est pas pris pour un planté."""
    tk = _tk([{"agent_id": "done", "kind": "work"}])
    fake = type("A", (), {"session_path": "/s"})()
    monkeypatch.setattr(wake.runner, "load_agent", lambda aid: fake)
    monkeypatch.setattr(wake.runner, "is_running", lambda agent: False)  # process mort
    monkeypatch.setattr(wake.store, "load_session_json", lambda p: {"close_reason": "final_answer"})
    marked: list[str] = []
    monkeypatch.setattr(wake.tickets_svc, "mark_run_completed", lambda s, t, aid: marked.append(aid))
    wake._reconcile_graceful_close("proj", tk)
    assert marked == ["done"]


def test_reconcile_leaves_true_crash_alone(monkeypatch):
    """Un agent mort sans avoir rien rendu reste un plantage, jamais une livraison."""
    tk = _tk([{"agent_id": "dead", "kind": "work"}])
    fake = type("A", (), {"session_path": "/s"})()
    monkeypatch.setattr(wake.runner, "load_agent", lambda aid: fake)
    monkeypatch.setattr(wake.runner, "is_running", lambda agent: False)
    monkeypatch.setattr(wake.store, "load_session_json", lambda p: {"close_reason": ""})
    marked: list[str] = []
    monkeypatch.setattr(wake.tickets_svc, "mark_run_completed", lambda s, t, aid: marked.append(aid))
    wake._reconcile_graceful_close("proj", tk)
    assert marked == []


# ── merge git réel, demandé explicitement ─────────────────────────────────────

def _git(repo: Path, *args: str) -> str:
    res = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


@pytest.fixture()
def develop_repo(tmp_path: Path) -> Path:
    # Unique repo dir name: WORKTREES_DIR is keyed by repo dir NAME, so a shared
    # "repo" name would race/purge sibling tests under `-n auto`.
    name = f"wfrepo_{uuid.uuid4().hex[:8]}"
    shutil.rmtree(worktrees.WORKTREES_DIR / name, ignore_errors=True)
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "branch", "-M", "main")   # main stays checked out (develop NOT checked out)
    _git(repo, "branch", "develop")
    return repo


def test_merge_produces_real_commit_and_cleans(develop_repo: Path):
    """Intégrer un ticket pose un vrai commit sur develop, nettoie, et ne rejoue pas."""
    meta = worktrees.provision(str(develop_repo), "t-mw", base_branch="develop", with_venv=False)
    assert meta["ok"]
    # l'agent laisse du travail NON COMMITÉ dans le worktree — le harvest doit le committer.
    (Path(meta["worktree"]) / "feat.py").write_text("x = 1\n", encoding="utf-8")
    ticket = {"id": "t-mw", "title": "Feat", "prompt": "p", "worktree": meta,
              "runs": [{"agent_id": "coder1", "kind": "work", "verdict": None}]}

    dev_before = _git(develop_repo, "rev-parse", "develop")
    log_before = _git(develop_repo, "rev-list", "--count", "develop")

    result = integration.integrate_ticket("proj", ticket, done_agent="coder1")
    assert result == {"ok": True, "state": "integrated"}

    dev_after = _git(develop_repo, "rev-parse", "develop")
    assert dev_after != dev_before, "develop HEAD must advance (real commit, not just applied diffs)"
    assert int(_git(develop_repo, "rev-list", "--count", "develop")) > int(log_before)
    assert "feat.py" in _git(develop_repo, "ls-tree", "--name-only", "develop")
    assert not Path(meta["worktree"]).exists()
    assert ticket["worktree"]["state"] == "cleaned"

    result2 = integration.integrate_ticket("proj", ticket, done_agent="coder1")
    assert result2["ok"] is False
    assert _git(develop_repo, "rev-parse", "develop") == dev_after


def test_harvest_on_crash_commits_wip(develop_repo: Path, monkeypatch):
    """Le travail non commité d'un agent planté est sauvé sur sa branche, jamais perdu."""
    from bouzecode.web_v2.services.work import tickets as tsvc
    monkeypatch.setattr(tsvc, "update_ticket", lambda s, t: None)
    monkeypatch.setattr(wake, "process_wakes", lambda: [])
    meta = worktrees.provision(str(develop_repo), "t-hcr", base_branch="develop", with_venv=False)
    assert meta["ok"]
    (Path(meta["worktree"]) / "wip.py").write_text("x = 1\n", encoding="utf-8")
    ticket = {"id": "t-hcr", "title": "WIP", "prompt": "p", "worktree": meta,
              "runs": [{"agent_id": "coder1", "kind": "work"}]}
    branch = meta["branch"]
    count_before = int(_git(develop_repo, "rev-list", "--count", branch))

    workflow._act_report_crash("proj", ticket, "coder1")

    assert ticket["crashed"] is True
    assert int(_git(develop_repo, "rev-list", "--count", branch)) == count_before + 1
    assert "wip.py" in _git(develop_repo, "ls-tree", "--name-only", branch)
