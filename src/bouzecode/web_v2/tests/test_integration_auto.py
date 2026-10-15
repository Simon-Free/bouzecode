# [desc] Tests de l'intégration demandée d'un ticket worktree : merge propre → closed, échec git → delivered{merge_echoue}, conflit renvoyé sans relance ni ré-intégration d'office. [/desc]
"""Tests user-centric de l'intégration demandée (integration.integrate_ticket) sur un vrai dépôt
git en tmp et le vrai store de tickets (aucun unittest.mock). L'état du ticket suit la machine
à états : delivered → integrating → closed | conflict | delivered{merge_echoue}."""
import subprocess
from pathlib import Path

from bouzecode.web_v2.services.work import conflits, integration, signalements, tickets, worktrees
from bouzecode.web_v2.services.work.fsm import etats
from bouzecode.web_v2.services.work.provisioning import meta_du_worktree
from bouzecode.web_v2.tests.aides_tickets import run, semer


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


def _livre(ident: str, meta: dict) -> dict:
    """Un ticket dont le codeur a livré dans son worktree."""
    return semer("proj", ident, etats.DELIVERED, title="ma feature",
                 worktree=meta_du_worktree(meta), runs=[run("work-agent-1", completed=True)])


def _frais(ticket: dict) -> dict:
    return tickets.get_ticket("proj", ticket["id"])


def test_clean_merge_integrates_and_cleans_worktree(tmp_path, monkeypatch):
    monkeypatch.setattr(worktrees, "WORKTREES_DIR", tmp_path / "wts")
    repo, base = _make_repo(tmp_path)
    meta = worktrees.provision(str(repo), "tk-clean", base_branch=base, with_venv=False)
    (Path(meta["worktree"]) / "b.txt").write_text("new file\n")  # pas de conflit
    ticket = _livre("tk-clean", meta)

    result = integration.integrate_ticket("proj", ticket)

    assert result["ok"] is True and result["state"] == etats.CLOSED
    frais = _frais(ticket)
    assert (frais["state"], frais["state_reason"]["code"]) == (etats.CLOSED, "integre")
    assert frais["integration"]["merged_at"] and frais["worktree"]["retire_at"]
    assert not Path(meta["worktree"]).exists()        # dossier worktree supprimé
    assert tickets.derive_status(frais) == "terminé"  # plus jamais « à relire » après merge


def test_integrate_error_is_parked_as_merge_echoue(tmp_path, monkeypatch):
    """Un échec de merge NON-conflit (erreur git) laisse le ticket LIVRÉ avec sa raison
    (`merge_echoue`), re-tentable — jamais une boucle, jamais perdu."""
    monkeypatch.setattr(worktrees, "WORKTREES_DIR", tmp_path / "wts")
    repo, base = _make_repo(tmp_path)
    meta = worktrees.provision(str(repo), "tk-err", base_branch=base, with_venv=False)
    (Path(meta["worktree"]) / "b.txt").write_text("x\n")
    ticket = _livre("tk-err", meta)
    monkeypatch.setattr(worktrees, "integrate",
                        lambda m: {"ok": False, "state": "error", "error": "boom git"})

    result = integration.integrate_ticket("proj", ticket)

    assert result["ok"] is False and result["code"] == "merge_echoue"
    frais = _frais(ticket)
    assert (frais["state"], frais["state_reason"]["code"]) == (etats.DELIVERED, "merge_echoue")
    assert "boom git" in frais["state_reason"]["message"]   # cause préservée
    assert frais["state_reason"]["details"]["remede"]        # et le remède (spec §5.4)
    assert tickets.derive_status(frais) == "merge bloqué"


def test_un_agent_qui_tourne_bloque_le_merge(tmp_path, monkeypatch):
    monkeypatch.setattr(worktrees, "WORKTREES_DIR", tmp_path / "wts")
    repo, base = _make_repo(tmp_path)
    meta = worktrees.provision(str(repo), "tk-run", base_branch=base, with_venv=False)
    ticket = semer("proj", "tk-run", etats.RUNNING, worktree=meta_du_worktree(meta),
                   runs=[run("work-agent-1", state="running")])
    assert integration.integrate_ticket("proj", ticket)["code"] == "agent_actif"
    assert _frais(ticket)["state"] == etats.RUNNING


def test_conflict_is_returned_and_nothing_is_relaunched_nor_merged(tmp_path, monkeypatch):
    """Lot L4 (B4) : un conflit est RENVOYÉ ; personne n'est relancé d'office, et une fois le
    conflit résolu le watchdog le CONSTATE (`conflict{conflit_resolu}`) sans jamais ré-intégrer."""
    monkeypatch.setattr(worktrees, "WORKTREES_DIR", tmp_path / "wts")
    repo, base = _make_repo(tmp_path)
    meta = worktrees.provision(str(repo), "tk-conflict", base_branch=base, with_venv=False)
    (Path(meta["worktree"]) / "a.txt").write_text("agent change\n")
    worktrees.harvest(meta, "edite a")
    (repo / "a.txt").write_text("base change\n")  # la base diverge sur le MÊME fichier
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "edite a (base)")
    ticket = _livre("tk-conflict", meta)

    first = integration.integrate_ticket("proj", ticket)
    assert first == {"ok": False, "code": "conflit", "state": etats.CONFLICT, "files": ["a.txt"]}
    frais = _frais(ticket)
    assert frais["state"] == etats.CONFLICT and len(frais["runs"]) == 1  # aucun run lancé
    assert frais["integration"]["conflict_files"] == ["a.txt"]

    # Tant que le merge n'est pas conclu dans le worktree, rien ne bouge.
    assert conflits.observer_resolution("proj", frais) is False

    # L'APPELANT a relancé le codeur, qui résout et commite dans le worktree.
    (Path(meta["worktree"]) / "a.txt").write_text("resolved\n")
    _git(meta["worktree"], "add", "-A")
    _git(meta["worktree"], "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--no-edit")
    assert conflits.observer_resolution("proj", _frais(ticket)) is True
    frais = _frais(ticket)
    assert (frais["state"], frais["state_reason"]["code"]) == (etats.CONFLICT, conflits.RESOLU)
    assert (repo / "a.txt").read_text() == "base change\n"  # le watchdog n'a RIEN mergé
    assert any("Conflit résolu" in s["titre"] for s in signalements.ouverts())  # sans parent

    # L'intégration, redemandée explicitement, passe : conflict → delivered → integrating → closed.
    assert integration.integrate_ticket("proj", frais)["ok"] is True
    assert _frais(ticket)["state"] == etats.CLOSED
    assert (repo / "a.txt").read_text() == "resolved\n"


def test_restore_conflict_exposed_on_ticket(tmp_path, monkeypatch):
    """Un pop de restore conflictuel (arbre principal sale sur le même fichier que l'agent
    réécrit) est exposé sur le ticket (`integration.restore_conflict`), le merge étant livré."""
    monkeypatch.setattr(worktrees, "WORKTREES_DIR", tmp_path / "wts")
    repo, base = _make_repo(tmp_path)
    meta = worktrees.provision(str(repo), "tk-restore", base_branch=base, with_venv=False)
    (Path(meta["worktree"]) / "a.txt").write_text("agent rewrite\n")
    _git(meta["worktree"], "add", "-A")
    _git(meta["worktree"], "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "agent")
    (repo / "a.txt").write_text("human wip\n")  # arbre principal SALE sur le même fichier
    ticket = _livre("tk-restore", meta)

    result = integration.integrate_ticket("proj", ticket)

    assert result["ok"] is True and "restore_conflict" in result
    restore = _frais(ticket)["integration"]["restore_conflict"]
    assert restore["branch"] == meta["branch"] and restore["stash_ref"].startswith("stash@{")
