# [desc] Tests d'auto-intégration de ticket worktree (merge propre + résolution de conflit via fake runner/store). [/desc]
"""Tests user-centric de l'auto-intégration (integration.integrate_ticket /
resume_after_conflict). On simule un vrai repo git en tmp et un fake runner/store
(fakes purs, aucun unittest.mock) : le fake continue_agent capture le prompt puis
résout réellement le conflit dans le worktree, prouvant la boucle complète."""
import subprocess
from pathlib import Path

from bouzecode.web_v2.services.work import integration, tickets, worktrees


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


def _make_repo(tmp: Path):
    repo = tmp / "myrepo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "user.email", "t@t")
    (repo / "a.txt").write_text("base\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    base = subprocess.run(["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    return repo, base


class FakeAgent:
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.auto_retry_count = 0


class FakeStore:
    """Aucun agent ne tourne (le fake continue_agent résout de façon synchrone)."""

    def agent_status(self, agent):
        return {"state": "finished"}


class FakeRunner:
    """Fake pur : load_agent rend l'agent codeur du ticket ; continue_agent capture
    le prompt PUIS résout réellement le conflit dans le worktree (comme le ferait
    le vrai agent), pour que la re-intégration réussisse."""

    def __init__(self, worktree_path: str):
        self.worktree = worktree_path
        self.continue_calls = []
        self.create_calls = []
        self.reap_calls = []
        self.AGENTS_DIR = Path(worktree_path)
        self.agent = FakeAgent("work-agent-1")

    def load_agent(self, agent_id):
        return self.agent

    def reap_session_processes(self, session_path):
        self.reap_calls.append(session_path)
        return 0

    def is_running(self, agent):
        return False  # le conflit est résolu SYNCHRONIQUEMENT dans continue_agent

    def continue_agent(self, agent, prompt, model=""):
        self.continue_calls.append(prompt)
        # simule la résolution de l'agent : réécrit + commit dans le worktree
        (Path(self.worktree) / "a.txt").write_text("resolved\n")
        _git(self.worktree, "add", "-A")
        _git(self.worktree, "-c", "user.name=t", "-c", "user.email=t@t",
             "commit", "--no-edit")
        return agent

    def create_agent(self, prompt, extra, worktree, parent=""):
        self.create_calls.append(prompt)
        return FakeAgent("merge-agent-fallback")


def _build_ticket(meta):
    """Ticket avec un run 'work' (agent codeur) + une validation verte."""
    return {
        "title": "ma feature",
        "worktree": meta,
        "runs": [
            {"kind": "work", "agent_id": "work-agent-1"},
            {"kind": "validate", "verdict": "OK", "agent_id": "val-1"},
        ],
    }


def _wire(monkeypatch, tmp_path, runner):
    worktrees.WORKTREES_DIR = tmp_path / "wts"
    monkeypatch.setattr(integration, "runner", runner)
    monkeypatch.setattr(integration, "store", FakeStore())
    # neutralise la persistance disque des tickets (on manipule le dict en mémoire)
    monkeypatch.setattr(tickets, "update_ticket", lambda slug, ticket: None)
    monkeypatch.setattr(tickets, "add_run",
                        lambda slug, ticket, aid, kind, prompt: ticket["runs"].append(
                            {"kind": kind, "agent_id": aid, "prompt": prompt}))


def test_clean_merge_integrates_and_cleans_worktree(tmp_path, monkeypatch):
    repo, base = _make_repo(tmp_path)
    runner = FakeRunner("")
    _wire(monkeypatch, tmp_path, runner)

    meta = worktrees.provision(str(repo), "tk-clean", base_branch=base, with_venv=False)
    (Path(meta["worktree"]) / "b.txt").write_text("new file\n")  # pas de conflit
    ticket = _build_ticket(meta)

    result = integration.integrate_ticket("proj", ticket)

    assert result["ok"] is True and result["state"] == "integrated"
    assert meta["state"] == "cleaned"                 # worktree nettoyé
    assert not Path(meta["worktree"]).exists()        # dossier worktree supprimé
    assert runner.continue_calls == []                # aucun conflit → pas de relance


def test_clean_merge_marks_ticket_done(tmp_path, monkeypatch):
    """BUG : après un merge PROPRE, le ticket restait affiché 'valide' (done=False) à vie
    alors que le code était déjà mergé sur develop. Le merge doit poser done=True pour que
    derive_status affiche 'termine' — mirror de finalize_ephemeral."""
    repo, base = _make_repo(tmp_path)
    runner = FakeRunner("")
    _wire(monkeypatch, tmp_path, runner)

    meta = worktrees.provision(str(repo), "tk-done", base_branch=base, with_venv=False)
    (Path(meta["worktree"]) / "b.txt").write_text("new file\n")  # pas de conflit
    ticket = _build_ticket(meta)

    result = integration.integrate_ticket("proj", ticket)

    assert result["ok"] is True
    assert ticket["done"] is True                      # merge propre → done posé
    assert tickets.derive_status(ticket) == "terminé"  # plus jamais 'valide' après merge


def test_integrate_error_is_parked_as_needs_attention(tmp_path, monkeypatch):
    """META-BUG : un échec de merge NON-conflit (erreur git) doit être PARKÉ (needs_attention),
    jamais laissé en 'error' — sinon derive_state retombe sur 'validating' → merge_and_wake
    bouclé jusqu'au crash = travail VALIDÉ jamais livré."""
    repo, base = _make_repo(tmp_path)
    runner = FakeRunner("")
    _wire(monkeypatch, tmp_path, runner)
    meta = worktrees.provision(str(repo), "tk-err", base_branch=base, with_venv=False)
    (Path(meta["worktree"]) / "b.txt").write_text("x\n")
    ticket = _build_ticket(meta)
    monkeypatch.setattr(worktrees, "integrate",
                        lambda m: {"ok": False, "state": "error", "error": "boom git"})

    result = integration.integrate_ticket("proj", ticket)

    assert result["ok"] is False and result["state"] == "needs_attention"
    assert meta["state"] == "needs_attention"           # parké → derive_state gare → pas de boucle
    assert meta.get("integrate_error") == "boom git"    # cause préservée


def test_completed_work_run_does_not_block_merge(tmp_path, monkeypatch):
    """META-BUG : un run 'work' déjà 'completed' (zombie de codeur fini dont le process traîne)
    ne bloque PLUS le merge — sinon integrate_ticket early-return en boucle → crash."""
    repo, base = _make_repo(tmp_path)
    runner = FakeRunner("")
    _wire(monkeypatch, tmp_path, runner)
    meta = worktrees.provision(str(repo), "tk-zombie", base_branch=base, with_venv=False)
    (Path(meta["worktree"]) / "b.txt").write_text("new\n")
    ticket = _build_ticket(meta)
    ticket["runs"][0]["completed"] = True               # run fini, mais process "running"

    class RunningStore:
        def agent_status(self, agent):
            return {"state": "running"}
    monkeypatch.setattr(integration, "store", RunningStore())

    assert integration._work_running(ticket) is False   # completed prime sur le process vivant
    result = integration.integrate_ticket("proj", ticket)
    assert result["ok"] is True and result["state"] == "integrated"


# `test_continue_coder_noop_when_validated` vivait ici. Il protégeait un verrou de course
# INTERNE à `integration.continue_coder` : ne pas respawner le codeur quand le ticket portait
# déjà un validate:OK. Cette fonction, et la boucle de rework work→validate→work qu'elle
# animait, ont été retirées avec l'orchestration p10 — plus aucun chemin ne relance un codeur
# de lui-même (ni route, ni appelant), donc plus aucune course à verrouiller. Relancer un
# codeur est désormais un geste explicite, via POST /api/agents/<id>/continue.


def test_conflict_relaunches_coder_agent_then_reintegrates(tmp_path, monkeypatch):
    repo, base = _make_repo(tmp_path)
    meta = worktrees.provision(str(repo), "tk-conflict", base_branch=base, with_venv=False)
    runner = FakeRunner(meta["worktree"])
    _wire(monkeypatch, tmp_path, runner)

    # l'agent modifie a.txt dans le worktree
    (Path(meta["worktree"]) / "a.txt").write_text("agent change\n")
    worktrees.harvest(meta, "edite a")
    # la base diverge sur le MÊME fichier → conflit garanti
    (repo / "a.txt").write_text("base change\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "edite a (base)")

    ticket = _build_ticket(meta)

    # 1re tentative : conflit détecté → l'agent CODEUR du ticket est relancé
    first = integration.integrate_ticket("proj", ticket)
    assert first["ok"] is False and first["state"] == "conflict"
    assert "a.txt" in first["files"]
    assert runner.continue_calls, "continue_agent doit être appelé"
    assert "a.txt" in runner.continue_calls[0], "le prompt doit lister les fichiers en conflit"
    assert runner.create_calls == [], "on relance la session codeur, pas un agent générique"
    assert meta["state"] == "conflict" and meta["conflict_agent"] == "work-agent-1"

    # le FakeRunner a résolu + commité dans le worktree → la reprise ré-intègre
    integration.resume_after_conflict("proj", ticket)

    assert meta["state"] == "cleaned"                 # intégré + nettoyé
    assert not Path(meta["worktree"]).exists()
    assert (repo / "a.txt").read_text() == "resolved\n"  # résolution mergée dans la base


def test_restore_conflict_exposed_on_ticket_meta(tmp_path, monkeypatch):
    """Un pop de restore conflictuel (arbre principal sale sur le même fichier que l'agent
    réécrit) doit exposer restore_conflict sur meta du ticket, tout en livrant le merge."""
    repo, base = _make_repo(tmp_path)
    runner = FakeRunner("")
    _wire(monkeypatch, tmp_path, runner)

    meta = worktrees.provision(str(repo), "tk-restore", base_branch=base, with_venv=False)
    (Path(meta["worktree"]) / "a.txt").write_text("agent rewrite\n")
    _git(meta["worktree"], "add", "-A")
    _git(meta["worktree"], "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "agent")
    # arbre principal SALE sur le même fichier → le pop de restore conflictera
    (repo / "a.txt").write_text("human wip\n")
    ticket = _build_ticket(meta)

    result = integration.integrate_ticket("proj", ticket)

    assert result["ok"] is True and result["state"] == "integrated"
    assert "restore_conflict" in result
    assert meta["restore_conflict"]["branch"] == meta["branch"]
    assert meta["restore_conflict"]["stash_ref"].startswith("stash@{")
