# [desc] Tests du cycle de vie des tickets : faucheur (GC) des bacs à sable + ticket éphémère (test). [/desc]
"""Le reaper ne réclame le worktree QUE quand le travail est fini pour de bon (mergé/éphémère),
et jamais un arbre sale (le nettoyage d'un ticket non mergé est un geste explicite et gardé :
`nettoyage`, testé dans test_nettoyage_garde.py). Un ticket crashed reste
REPRENABLE → worktree ET branche CONSERVÉS (régression : un restart serveur crash-reapait un
agent resumable). NE touche pas un ticket non-terminal ni un run busy ; idempotent. Le ticket
ÉPHÉMÈRE NE COMMIT PAS sur develop et s'auto-nettoie. Prédicats purs testés sans git ; effets sur vrai git temp.

Pas d'unittest.mock — vrai git sur dépôts jetables + pytest.monkeypatch/fakes."""
from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

import pytest

from bouzecode.web_v2.services.work import (
    integration, projects, reaper, tickets, wake, worktrees,
)
from bouzecode.web_v2.services.work.fsm import etats
from bouzecode.web_v2.runtime.runner import agent_creation


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

def _tk(state, code=None, retire=False, **extra):
    meta = {"worktree": "/wt", "branch": "agent/t1", "repo_root": "/r", "base": "develop"}
    if retire:
        meta["retire_at"] = "2026-10-01T10:00:00"
    return {"id": "t1", "title": "T", "prompt": "p", "worktree": meta, "state": state,
            "state_reason": {"code": code} if code else None,
            "runs": [{"agent_id": "a", "kind": "work"}], **extra}


def test_seul_un_ticket_integre_ou_ephemere_est_fauchable():
    assert reaper.should_reap(_tk(etats.CLOSED, "integre")) is True
    assert reaper.should_reap(_tk(etats.STOPPED, "crashed", ephemeral=True)) is True
    for state, code in ((etats.STOPPED, "crashed"), (etats.DELIVERED, None),
                        (etats.DELIVERED, "merge_bloque"), (etats.CLOSED, "accepte"),
                        (etats.RUNNING, None), (etats.CONFLICT, "conflit")):
        assert reaper.should_reap(_tk(state, code)) is False, (state, code)


def test_should_delete_branch_policy():
    assert reaper.should_delete_branch(_tk(etats.CLOSED, "integre")) is True   # mergé → sûr
    assert reaper.should_delete_branch(_tk(etats.STOPPED, "crashed", ephemeral=True)) is True
    assert reaper.should_delete_branch(_tk(etats.DELIVERED, "merge_bloque")) is False
    assert reaper.should_delete_branch(_tk(etats.STOPPED, "crashed")) is False


def test_already_reaped_is_not_reaped_again():
    assert reaper.should_reap(_tk(etats.CLOSED, "integre", retire=True)) is False


# ── Reaper effectif (vrai git) ────────────────────────────────────────────────

def _provision_ticket(repo: Path, tid: str, state, code=None, **extra) -> dict:
    from bouzecode.web_v2.services.work.provisioning import meta_du_worktree
    from bouzecode.web_v2.tests.aides_tickets import run, semer
    meta = worktrees.provision(str(repo), tid, base_branch="develop", with_venv=False)
    assert meta["ok"]
    return semer("proj", tid, state, code, runs=[run("a")], worktree=meta_du_worktree(meta),
                 **extra)


def test_reap_crashed_keeps_worktree_and_branch(hermetic):
    """Un crash est souvent une mort de process transitoire (restart serveur) : le ticket reste
    REPRENABLE. Le GC conserve worktree ET branche (régression cause racine worktree readme_sync)."""
    repo = _make_repo(hermetic)
    ticket = _provision_ticket(repo, "t-crash", etats.STOPPED, "crashed")
    wt = ticket["worktree"]["worktree"]
    assert reaper.reap_ticket("proj", ticket) is False
    assert Path(wt).is_dir()                             # worktree CONSERVÉ
    assert _branch_exists(repo, "agent/t-crash")        # branche conservée
    assert "retire_at" not in tickets.get_ticket("proj", "t-crash")["worktree"]


def test_reap_integrated_never_destroys_a_dirty_tree(hermetic):
    """C15 / B9 : même mergé, un worktree resté SALE n'est jamais fauché (rien n'est récolté
    d'office, et `worktree remove --force` emporterait ce reste)."""
    repo = _make_repo(hermetic)
    ticket = _provision_ticket(repo, "t-sale", etats.CLOSED, "integre")
    wt = Path(ticket["worktree"]["worktree"])
    (wt / "reste.py").write_text("x = 1\n", encoding="utf-8")
    assert reaper.reap_ticket("proj", ticket) is False
    assert (wt / "reste.py").is_file()


def test_reap_integrated_removes_worktree_and_branch(hermetic):
    repo = _make_repo(hermetic)
    ticket = _provision_ticket(repo, "t-int", etats.CLOSED, "integre")
    wt = ticket["worktree"]["worktree"]
    assert reaper.reap_ticket("proj", ticket) is True
    assert not Path(wt).exists()
    assert not _branch_exists(repo, "agent/t-int")     # mergé → branche supprimée
    assert tickets.get_ticket("proj", "t-int")["worktree"]["retire_at"]


def test_reaper_ignores_non_terminal_ticket(hermetic):
    repo = _make_repo(hermetic)
    ticket = _provision_ticket(repo, "t-wip", etats.RUNNING)
    wt = ticket["worktree"]["worktree"]
    assert reaper.reap_ticket("proj", ticket) is False
    assert Path(wt).is_dir()                            # intact
    assert _branch_exists(repo, "agent/t-wip")


def test_reap_is_idempotent(hermetic):
    repo = _make_repo(hermetic)
    ticket = _provision_ticket(repo, "t-idem", etats.CLOSED, "integre")
    wt = ticket["worktree"]["worktree"]
    assert reaper.reap_ticket("proj", ticket) is True   # intégré → fauché
    assert not Path(wt).exists()
    head_after = _git(repo, "rev-parse", "develop")
    assert reaper.reap_ticket("proj", ticket) is False  # 2e reap = no-op
    assert _git(repo, "rev-parse", "develop") == head_after


# ── Ticket éphémère : jamais de merge develop, auto-reap ──────────────────────

def test_ephemeral_shunts_merge_and_reaps(hermetic, monkeypatch):
    """Clore un éphémère (`POST /integrate` → `finalize_ephemeral`) ne touche pas develop et
    jette son bac à sable ; le ticket est clos, et reclore est idempotent."""
    monkeypatch.setattr(wake, "process_wakes", lambda: [])  # pas de réveil réel en test
    repo = _make_repo(hermetic)
    ticket = _provision_ticket(repo, "t-eph", etats.DELIVERED, ephemeral=True)
    wt = ticket["worktree"]["worktree"]
    dev_before = _git(repo, "rev-parse", "develop")

    assert integration.finalize_ephemeral("proj", ticket)["ok"] is True

    assert _git(repo, "rev-parse", "develop") == dev_before   # develop INCHANGÉ (jamais mergé)
    assert not Path(wt).exists()                              # worktree auto-fauché
    assert not _branch_exists(repo, "agent/t-eph")           # branche jetable supprimée
    frais = tickets.get_ticket("proj", "t-eph")
    assert (frais["state"], frais["state_reason"]["code"]) == (etats.CLOSED, "ephemere")

    # idempotence : reclore ne recrée ni ne recommit rien
    assert integration.finalize_ephemeral("proj", frais)["ok"] is True
    assert _git(repo, "rev-parse", "develop") == dev_before
    assert not Path(wt).exists()


# ── Création : flag éphémère persisté, dans un worktree ─────────────────────

def test_un_ticket_ephemere_cree_garde_son_drapeau_et_son_worktree(hermetic, monkeypatch):
    from bouzecode.web_v2 import api_sanity
    from bouzecode.web_v2.services.work.api_tickets import creation
    repo = _make_repo(hermetic)
    proj = {"slug": "proj", "name": "P", "path": str(repo)}
    monkeypatch.setattr(projects, "list_projects", lambda: [proj])
    monkeypatch.setattr(projects, "find", lambda slug: proj if slug == "proj" else None)
    monkeypatch.setattr(api_sanity, "require_api_sanity", lambda: None)

    class _FakeAgent:
        agent_id = "fake123"

    monkeypatch.setattr(agent_creation, "create_agent", lambda *a, **k: _FakeAgent())
    monkeypatch.setattr(worktrees, "setup_venv_async", lambda *a, **k: None)  # pas de uv en test

    result = creation.creer("proj", {"title": "teste la chaîne", "prompt": "teste la chaîne",
                                     "ephemeral": True, "defer": False})
    saved = tickets.get_ticket("proj", result["ticket_id"])
    assert saved["ephemeral"] is True
    assert isinstance(saved.get("worktree"), dict)           # un éphémère vit dans un worktree
    assert Path(saved["worktree"]["worktree"]).is_dir()

# `test_dispatch_run_validator_flag_persists` vivait ici. Il pinnait une case UI « lancer un
# validateur après le travail » dont plus RIEN ne subsiste : ni le paramètre `run_validator`
# de l'ancien `dispatch.dispatch` (il levait un TypeError), ni le champ sur le ticket, ni le lancement
# automatique qu'il pilotait — tous retirés avec la chaîne d'orchestration p10. Le validateur
# de tickets a ensuite été retiré du backend (D1).
