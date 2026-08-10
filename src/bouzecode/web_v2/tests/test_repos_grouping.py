"""Regroupement des worktrees par dépôt git (logique pure, key_fn injecté)."""
import os

from bouzecode.web_v2.services.work import repos


def test_group_overview_folds_worktrees_by_repo_key():
    rows = [
        {"path": "/p/wt_f7", "name": "stratinit-wt-f7", "slug": "stratinit-wt-f7",
         "agents_running": 1, "tickets_total": 2},
        {"path": "/p/wt_f8", "name": "stratinit-wt-f8", "slug": "stratinit-wt-f8",
         "agents_running": 0, "tickets_total": 1},
        {"path": "/p/oc", "name": "opencode", "slug": "opencode",
         "agents_running": 2, "tickets_total": 0},
    ]
    keys = {"/p/wt_f7": os.path.join(os.sep, "repo", "strat", ".git"),
            "/p/wt_f8": os.path.join(os.sep, "repo", "strat", ".git"),
            "/p/oc": os.path.join(os.sep, "repo", "oc", ".git")}
    groups = repos.group_overview(rows, key_fn=lambda p: keys[p])
    assert len(groups) == 2
    strat = next(g for g in groups if len(g["worktrees"]) == 2)
    assert strat["name"] == "strat"
    assert strat["agents_running"] == 1      # 1 + 0 agrégé
    assert strat["tickets_total"] == 3       # 2 + 1 agrégé


def test_group_overview_ungrouped_when_no_git():
    rows = [{"path": os.path.join(os.sep, "p", "solo"), "name": "solo", "slug": "solo",
             "tickets_total": 1}]
    groups = repos.group_overview(rows, key_fn=lambda p: None)
    assert len(groups) == 1
    assert groups[0]["name"] == "solo"       # fallback basename du path
    assert groups[0]["tickets_total"] == 1


def test_repo_name_from_common_dir():
    key = os.path.join(os.sep, "x", "myrepo", ".git")
    assert repos.repo_name("/anything", key) == "myrepo"
