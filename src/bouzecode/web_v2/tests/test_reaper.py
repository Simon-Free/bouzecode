# [desc] Tests du cycle de vie des tickets : faucheur (GC) des bacs à sable + ticket éphémère (test). [/desc]
"""Le reaper ne réclame le worktree QUE quand le travail est fini pour de bon (mergé/éphémère)
ou à l'ARCHIVAGE explicite (`reap_archived`, branche gardée). Un ticket crashed/failed reste
REPRENABLE → worktree ET branche CONSERVÉS (régression : un restart serveur crash-reapait un
agent resumable). NE touche pas un ticket non-terminal ni un run busy ; idempotent. Le ticket
ÉPHÉMÈRE suit toute la chaîne mais NE COMMIT PAS sur develop et s'auto-nettoie, tout en
produisant un verdict. Prédicats purs testés sans git ; effets sur vrai git temp.

Pas d'unittest.mock — vrai git sur dépôts jetables + pytest.monkeypatch/fakes."""
from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

import pytest

from bouzecode.web_v2.services.work import (
    dispatch, integration, reaper, tickets, wake, workflow, worktrees,
)


def _git(cwd, *args) -> str:
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


def _make_repo(tmp_path: Path) -> Path:
    """Dépôt jetable avec branche develop (main reste checkout, develop NON checkout)."""
    repo = tmp_path / f"reaprepo_{uuid.uuid4().hex[:8]}"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "branch", "-M", "main")
    _git(repo, "branch", "develop")
    return repo


def _branch_exists(repo: Path, branch: str) -> bool:
    out = subprocess.run(["git", "-C", str(repo), "branch", "--list", branch],
                         capture_output=True, text=True).stdout
    return bool(out.strip())


@pytest.fixture()
def hermetic(tmp_path, monkeypatch):
    """Isole WORKTREES_DIR + TICKETS_DIR sous tmp (parallélisable)."""
    monkeypatch.setattr(worktrees, "WORKTREES_DIR", tmp_path / "wts")
    return tmp_path


# ── Prédicats purs (sans git) ─────────────────────────────────────────────────

def _tk(runs, wt_state="provisioned", **extra):
    meta = {"state": wt_state, "worktree": "/wt", "branch": "agent/t1",
            "repo_root": "/r", "base": "develop"}
    return {"id": "t1", "title": "T", "prompt": "p", "worktree": meta, "runs": runs, **extra}


def test_terminal_outcome_classifies_each_end_state():
    assert reaper.terminal_outcome(_tk([], wt_state="cleaned")) == "integrated"
    assert reaper.terminal_outcome(_tk([], wt_state="integrated")) == "integrated"
    assert reaper.terminal_outcome(_tk([{"agent_id": "a", "kind": "work"}], crashed=True)) == "crashed"
    failed = _tk([{"agent_id": "v", "kind": "validate", "verdict": "KO"}]
                 + [{"agent_id": "a", "kind": "work"}] * 3, wt_state="committed")
    assert reaper.terminal_outcome(failed) == "failed"


def test_non_terminal_ticket_has_no_outcome_and_is_not_reaped():
    """Un ticket dont le codeur a livré sans verdict peut encore avancer : rien n'est fauché.

    Le test pinnait aussi « KO sous le plafond → pas encore terminal ». Ce plafond
    (`_MAX_WORK_PASSES`) a été supprimé avec la boucle de rework automatique : un verdict KO
    est désormais une issue directe, que le manager relance ou non. La distinction n'existe
    plus, et `test_terminal_outcome_classifies_each_end_state` couvre le KO terminal."""
    work_done = _tk([{"agent_id": "a", "kind": "work"}])
    assert reaper.terminal_outcome(work_done) is None
    assert reaper.is_terminal(work_done) is False
    assert reaper.should_reap(work_done) is False


def test_should_delete_branch_policy():
    assert reaper.should_delete_branch("integrated", False) is True   # mergé → sûr
    assert reaper.should_delete_branch("failed", True) is True        # éphémère → jetable
    assert reaper.should_delete_branch("failed", False) is False      # post-mortem → garder
    assert reaper.should_delete_branch("crashed", False) is False


def test_already_reaped_is_not_reaped_again():
    assert reaper.should_reap(_tk([], wt_state="cleaned", reaped=True)) is False


# ── Reaper effectif (vrai git) ────────────────────────────────────────────────

def _provision_ticket(repo: Path, tid: str, runs, wt_state, **extra) -> dict:
    meta = worktrees.provision(str(repo), tid, base_branch="develop", with_venv=False)
    assert meta["ok"]
    meta["state"] = wt_state
    ticket = {"id": tid, "title": "T", "prompt": "p", "worktree": meta, "runs": runs, **extra}
    tickets.update_ticket("proj", ticket)  # persiste (reap_ticket update_ticket dessus)
    tickets._save("proj", [ticket])
    return ticket


def test_reap_failed_keeps_worktree_and_branch(hermetic):
    """NOUVELLE POLITIQUE : un ticket failed (KO au plafond) reste REPRENABLE — le GC ne fauche
    NI son worktree NI sa branche. Le worktree n'est réclamé qu'au merge ou à l'archivage."""
    repo = _make_repo(hermetic)
    runs = [{"agent_id": "v", "kind": "validate", "verdict": "KO"}] + \
           [{"agent_id": "a", "kind": "work"}] * 3
    ticket = _provision_ticket(repo, "t-fail", runs, "committed")
    wt = ticket["worktree"]["worktree"]
    assert reaper.terminal_outcome(ticket) == "failed"

    assert reaper.reap_ticket("proj", ticket) is False   # NE fauche pas
    assert Path(wt).is_dir()                             # worktree CONSERVÉ (reprenable)
    assert _branch_exists(repo, "agent/t-fail")         # branche conservée
    assert "reaped" not in ticket


def test_reap_crashed_keeps_worktree_and_branch(hermetic):
    """Un crash est souvent une mort de process transitoire (restart serveur) : le ticket reste
    REPRENABLE. Le GC conserve worktree ET branche (régression cause racine worktree readme_sync)."""
    repo = _make_repo(hermetic)
    ticket = _provision_ticket(repo, "t-crash", [{"agent_id": "a", "kind": "work"}],
                               "provisioned", crashed=True)
    wt = ticket["worktree"]["worktree"]
    assert reaper.terminal_outcome(ticket) == "crashed"
    assert reaper.reap_ticket("proj", ticket) is False
    assert Path(wt).is_dir()                             # worktree CONSERVÉ
    assert _branch_exists(repo, "agent/t-crash")        # branche conservée
    assert "reaped" not in ticket


def test_reap_archived_removes_worktree_keeps_branch(hermetic):
    """Archivage explicite : réclame le worktree (disque), CONSERVE la branche (commits sûrs).
    C'est la voie qui nettoie enfin le worktree d'un crashed/failed conservé par le GC."""
    repo = _make_repo(hermetic)
    ticket = _provision_ticket(repo, "t-arch", [{"agent_id": "a", "kind": "work"}],
                               "provisioned", crashed=True)
    wt = ticket["worktree"]["worktree"]
    assert reaper.reap_archived("proj", ticket) is True
    assert not Path(wt).exists()                        # worktree réclamé
    assert _branch_exists(repo, "agent/t-arch")         # branche GARDÉE (récupérable)
    assert ticket["reaped"] is True


def test_reap_archived_skips_busy(hermetic, monkeypatch):
    """On ne fauche jamais le worktree d'un ticket dont un run tourne encore, même à l'archivage."""
    repo = _make_repo(hermetic)
    ticket = _provision_ticket(repo, "t-busy", [{"agent_id": "a", "kind": "work"}], "provisioned")
    wt = ticket["worktree"]["worktree"]
    monkeypatch.setattr(reaper.workflow, "derive_state", lambda t: "busy")
    assert reaper.reap_archived("proj", ticket) is False
    assert Path(wt).is_dir()                             # intact


def test_reap_project_reaps_all_ticket_worktrees_keeps_branches(hermetic):
    """Suppression d'un projet → réclame le worktree de CHACUN de ses tickets (branches gardées).
    Ferme la boucle des worktrees orphelins laissés quand un projet est retiré."""
    repo = _make_repo(hermetic)
    t1 = _provision_ticket(repo, "p-a", [{"agent_id": "a", "kind": "work"}], "provisioned")
    t2 = _provision_ticket(repo, "p-b", [{"agent_id": "b", "kind": "work"}], "provisioned")
    tickets._save("proj", [t1, t2])   # les deux tickets dans le même projet
    wt1, wt2 = t1["worktree"]["worktree"], t2["worktree"]["worktree"]

    reaped = reaper.reap_project("proj")
    assert set(reaped) == {"p-a", "p-b"}
    assert not Path(wt1).exists() and not Path(wt2).exists()          # worktrees réclamés
    assert _branch_exists(repo, "agent/p-a") and _branch_exists(repo, "agent/p-b")  # branches gardées


def test_reap_project_skips_busy_ticket(hermetic, monkeypatch):
    """Un ticket du projet dont un run tourne encore n'est PAS fauché (garde-fou busy)."""
    repo = _make_repo(hermetic)
    t = _provision_ticket(repo, "p-live", [{"agent_id": "a", "kind": "work"}], "provisioned")
    tickets._save("proj", [t])
    monkeypatch.setattr(reaper.workflow, "derive_state", lambda tk: "busy")
    assert reaper.reap_project("proj") == []             # rien fauché
    assert Path(t["worktree"]["worktree"]).is_dir()      # worktree intact


def test_reap_integrated_removes_worktree_and_branch(hermetic):
    repo = _make_repo(hermetic)
    ticket = _provision_ticket(repo, "t-int", [{"agent_id": "a", "kind": "work"}], "integrated")
    wt = ticket["worktree"]["worktree"]
    assert reaper.reap_ticket("proj", ticket) is True
    assert not Path(wt).exists()
    assert not _branch_exists(repo, "agent/t-int")     # mergé → branche supprimée


def test_reaper_ignores_non_terminal_ticket(hermetic):
    repo = _make_repo(hermetic)
    ticket = _provision_ticket(repo, "t-wip", [{"agent_id": "a", "kind": "work"}], "provisioned")
    wt = ticket["worktree"]["worktree"]
    assert reaper.reap_ticket("proj", ticket) is False
    assert Path(wt).is_dir()                            # intact
    assert _branch_exists(repo, "agent/t-wip")
    assert "reaped" not in ticket


def test_reap_is_idempotent(hermetic):
    repo = _make_repo(hermetic)
    ticket = _provision_ticket(repo, "t-idem", [{"agent_id": "a", "kind": "work"}], "integrated")
    wt = ticket["worktree"]["worktree"]
    assert reaper.reap_ticket("proj", ticket) is True   # integrated → fauché
    assert not Path(wt).exists()
    head_after = _git(repo, "rev-parse", "develop")
    assert reaper.reap_ticket("proj", ticket) is False  # 2e reap = no-op
    assert _git(repo, "rev-parse", "develop") == head_after


# ── Ticket éphémère : chaîne complète, jamais de merge develop, auto-reap ──────

def test_ephemeral_ok_shunts_merge_reaps_and_keeps_verdict(hermetic, monkeypatch):
    """Clore un éphémère validé OK ne touche pas develop, jette son bac à sable, et garde
    le verdict lisible.

    Le test passait par `workflow.advance`, qui finalisait l'éphémère au sein de la chaîne
    automatique travail→validation→merge — chaîne retirée avec l'orchestration p10. La
    clôture est désormais un geste EXPLICITE (`POST /integrate` → `finalize_ephemeral`) : on
    la joue donc là où elle vit, et toutes les garanties d'origine sont vérifiées telles
    quelles, idempotence comprise."""
    monkeypatch.setattr(wake, "process_wakes", lambda: [])  # pas de réveil réel en test
    repo = _make_repo(hermetic)
    runs = [{"agent_id": "v", "kind": "validate", "verdict": "OK"},
            {"agent_id": "coder", "kind": "work"}]
    ticket = _provision_ticket(repo, "t-eph", runs, "provisioned", ephemeral=True)
    wt = ticket["worktree"]["worktree"]
    dev_before = _git(repo, "rev-parse", "develop")

    assert integration.finalize_ephemeral("proj", ticket)["ok"] is True

    assert _git(repo, "rev-parse", "develop") == dev_before   # develop INCHANGÉ (jamais mergé)
    assert not Path(wt).exists()                              # worktree auto-fauché
    assert not _branch_exists(repo, "agent/t-eph")           # branche jetable supprimée
    assert ticket["reaped"] is True and ticket["done"] is True
    assert workflow.derive_state(ticket) == "done"           # ticket terminal
    assert integration.latest_verdict(ticket) == "OK"        # verdict quand même produit

    # idempotence : reclore ne recrée ni ne recommit rien
    assert integration.finalize_ephemeral("proj", ticket)["ok"] is True
    assert _git(repo, "rev-parse", "develop") == dev_before
    assert not Path(wt).exists()


def test_ephemeral_ko_at_cap_is_failed_not_merged(hermetic):
    """Éphémère KO plafonné → issue failed (jamais de merge), reste terminal."""
    runs = [{"agent_id": "v", "kind": "validate", "verdict": "KO"}] + \
           [{"agent_id": "a", "kind": "work"}] * 3
    ticket = _tk(runs, wt_state="committed", ephemeral=True)
    assert reaper.terminal_outcome(ticket) == "failed"


# ── Dispatch : flag éphémère persisté + isolation forcée ──────────────────────

def test_dispatch_ephemeral_persists_flag_and_forces_isolation(hermetic, monkeypatch):
    repo = _make_repo(hermetic)
    proj = {"slug": "proj", "name": "P", "path": str(repo)}
    monkeypatch.setattr(dispatch.projects, "list_projects", lambda: [proj])
    monkeypatch.setattr(dispatch.projects, "find", lambda slug: proj if slug == "proj" else None)
    monkeypatch.setattr(dispatch, "get_typology", lambda name, path=None: None)

    class _FakeAgent:
        agent_id = "fake123"

    monkeypatch.setattr(dispatch.runner, "create_agent", lambda *a, **k: _FakeAgent())
    monkeypatch.setattr(worktrees, "setup_venv_async", lambda *a, **k: None)  # pas de uv en test

    result = dispatch.dispatch("teste la chaîne", project_slug="proj",
                               typology="default", ephemeral=True)
    assert result["routed"] is True
    saved = tickets.get_ticket("proj", result["ticket_id"])
    assert saved["ephemeral"] is True
    assert isinstance(saved.get("worktree"), dict)           # isolation FORCÉE
    assert Path(saved["worktree"]["worktree"]).is_dir()

# `test_dispatch_run_validator_flag_persists` vivait ici. Il pinnait une case UI « lancer un
# validateur après le travail » dont plus RIEN ne subsiste : ni le paramètre `run_validator`
# de `dispatch.dispatch` (il levait un TypeError), ni le champ sur le ticket, ni le lancement
# automatique qu'il pilotait — tous retirés avec la chaîne d'orchestration p10. Un validateur
# se lance désormais à la demande ; c'est `test_ticket_validate_parent.py` qui le couvre.
