"""Cycle de vie worktree sur un dépôt jetable (vrai git, sans mock)."""
import subprocess
from pathlib import Path

from bouzecode.web_v2.services.work import integration, tickets, worktrees
from bouzecode.web_v2.services.work.fsm import etats
from bouzecode.web_v2.tests.aides_tickets import livre, run, semer


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


def test_harvest_embeds_recap_body(tmp_path):
    worktrees.WORKTREES_DIR = tmp_path / "wts"
    repo, base = _make_repo(tmp_path)
    meta = worktrees.provision(str(repo), "tkbody", base_branch=base, with_venv=False)
    assert meta["ok"]
    (Path(meta["worktree"]) / "c.txt").write_text("c\n")

    body = "## Symptoms\nle bug X.\n\n## Changes\n- a.py — corrige X"
    harvested = worktrees.harvest(meta, "titre court", body=body)
    assert harvested["committed"]

    full = subprocess.run(
        ["git", "-C", str(meta["worktree"]), "log", "-1", "--format=%B"],
        capture_output=True, text=True).stdout
    assert "agent: titre court" in full   # titre préservé
    assert "## Symptoms" in full           # corps recap embarqué
    assert "corrige X" in full


def test_harvest_excludes_orchestration_lock(tmp_path):
    """harvest ne doit JAMAIS committer `.agents.lock` (lock d'orchestration du
    harness) même s'il traîne untracked dans le worktree — mais doit committer le
    vrai travail. Reproduit le KO validateur : add -A aspirait le lock."""
    worktrees.WORKTREES_DIR = tmp_path / "wts"
    repo, base = _make_repo(tmp_path)
    meta = worktrees.provision(str(repo), "tklock", base_branch=base, with_venv=False)
    assert meta["ok"]

    wt = Path(meta["worktree"])
    (wt / "feat.py").write_text("def feat():\n    return 1\n")   # vrai produit
    (wt / ".agents.lock").write_text('{"stale": true}\n')        # artefact orchestration

    harvested = worktrees.harvest(meta, "ajoute feat")
    assert harvested["committed"]
    assert "feat.py" in harvested["files"]           # le produit est bien livré
    assert ".agents.lock" not in harvested["files"]  # le lock est exclu du commit

    # preuve dure : le lock n'est pas tracké dans le commit HEAD de la branche agent
    tracked = subprocess.run(
        ["git", "-C", str(wt), "ls-files"], capture_output=True, text=True).stdout
    assert ".agents.lock" not in tracked


def test_provision_harvest_integrate_cleanup(tmp_path):
    worktrees.WORKTREES_DIR = tmp_path / "wts"          # hermétique
    repo, base = _make_repo(tmp_path)

    meta = worktrees.provision(str(repo), "tk123", base_branch=base, with_venv=False)
    assert meta["ok"] and Path(meta["worktree"]).is_dir()
    assert meta["branch"] == "agent/tk123"

    (Path(meta["worktree"]) / "b.txt").write_text("new\n")
    harvested = worktrees.harvest(meta, "ajoute b")
    assert harvested["committed"] and "b.txt" in harvested["files"]

    result = worktrees.integrate(meta)
    assert result["ok"] and result["state"] == "integrated"
    assert (repo / "b.txt").exists()                    # intégré dans la base

    worktrees.cleanup(meta)
    assert not Path(meta["worktree"]).exists()


def test_integrate_refuses_branch_with_conflict_markers(tmp_path):
    """Garde-fou : une branche portant des marqueurs de conflit committés (résolution ratée
    d'un agent) n'est JAMAIS intégrée — sinon le code cassé casse la branche de référence
    (cf. incident app.py mergé avec <<<<<<< -> SyntaxError -> serveur mort)."""
    worktrees.WORKTREES_DIR = tmp_path / "wts_cm"
    repo, base = _make_repo(tmp_path)

    meta = worktrees.provision(str(repo), "tkcm", base_branch=base, with_venv=False)
    (Path(meta["worktree"]) / "app.py").write_text(
        "def main():\n<<<<<<< HEAD\n    return 1\n=======\n    return 2\n>>>>>>> develop\n")
    # Commit à la main : `harvest` refuserait de figer ces marqueurs (fichier non suivi sale).
    _git(meta["worktree"], "add", "app.py")
    _git(meta["worktree"], "commit", "-m", "resolution ratee")

    result = worktrees.integrate(meta)
    assert result["ok"] is False and result["state"] == "needs_attention"
    assert "app.py" in result["error"]
    assert not (repo / "app.py").exists()          # base épargnée


def test_integrate_conflict_is_detected_and_main_repo_untouched(tmp_path):
    worktrees.WORKTREES_DIR = tmp_path / "wts2"
    repo, base = _make_repo(tmp_path)
    meta = worktrees.provision(str(repo), "tk9", base_branch=base, with_venv=False)

    (Path(meta["worktree"]) / "a.txt").write_text("agent change\n")
    worktrees.harvest(meta, "edite a (agent)")

    (repo / "a.txt").write_text("base change\n")          # divergence sur la base
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "edite a (base)")

    result = worktrees.integrate(meta)
    assert result["state"] == "conflict" and "a.txt" in result["files"]
    # le repo principal reste propre (la résolution se fera dans le worktree)
    assert (repo / "a.txt").read_text() == "base change\n"


def _head(repo, ref):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", ref],
                          capture_output=True, text=True).stdout.strip()


def _harvested_meta(repo, base, tmp_path, sub, ticket="tk", filename="b.txt"):
    worktrees.WORKTREES_DIR = tmp_path / sub
    meta = worktrees.provision(str(repo), ticket, base_branch=base, with_venv=False)
    (Path(meta["worktree"]) / filename).write_text("agent work\n")
    worktrees.harvest(meta, "livre agent")
    return meta


def test_merge_base_not_checked_out_advances_ref(tmp_path):
    """CAS 1 : base non checkout dans le repo principal → avance de ref (git branch -f),
    HEAD de la base AVANCE, worktree nettoyé."""
    repo, base = _make_repo(tmp_path)
    _git(repo, "checkout", "-b", "sidebranch")            # le repo principal quitte la base
    meta = _harvested_meta(repo, base, tmp_path, "c1")

    before = _head(repo, base)
    result = worktrees.integrate(meta)
    assert result["ok"] and result["state"] == "integrated"
    assert _head(repo, base) != before                    # la ref de base a avancé

    worktrees.cleanup(meta)
    assert not Path(meta["worktree"]).exists()


def test_merge_base_checked_out_clean_merges_no_ff(tmp_path):
    """CAS 2 : base checkout et arbre PROPRE → merge --no-ff, HEAD avance, worktree nettoyé."""
    repo, base = _make_repo(tmp_path)                      # repo reste sur la base
    meta = _harvested_meta(repo, base, tmp_path, "c2")

    before = _head(repo, "HEAD")
    result = worktrees.integrate(meta)
    assert result["ok"] and result["state"] == "integrated"
    assert _head(repo, "HEAD") != before                  # HEAD (= base) a avancé
    assert (repo / "b.txt").exists()

    worktrees.cleanup(meta)
    assert not Path(meta["worktree"]).exists()


def test_merge_with_unrelated_untracked_file_still_merges(tmp_path):
    """CAS 3 (LE FIX) : base checkout + fichier UNTRACKED sans rapport → merge quand même,
    et le fichier untracked de l'humain est PRÉSERVÉ."""
    repo, base = _make_repo(tmp_path)
    (repo / "human_artifact.log").write_text("scratch de l'humain\n")   # untracked, sans rapport
    meta = _harvested_meta(repo, base, tmp_path, "c3")

    result = worktrees.integrate(meta)
    assert result["ok"] and result["state"] == "integrated"
    assert (repo / "b.txt").exists()                                     # merge effectué
    assert (repo / "human_artifact.log").read_text() == "scratch de l'humain\n"  # préservé


def test_merge_with_tracked_uncommitted_change_stashes_merges_restores(tmp_path):
    """CAS 4 (ex-needs_attention) : base checkout + modif TRACKED non commitée SANS rapport avec
    le merge. On ne bloque PLUS (« les merges ne se déclenchent pas ») : stash → merge → restore.
    Le merge s'applique ET le WIP humain est préservé."""
    repo, base = _make_repo(tmp_path)
    (repo / "a.txt").write_text("WIP humain non commité\n")             # modif tracked (sans rapport)
    meta = _harvested_meta(repo, base, tmp_path, "c4")                  # l'enfant ajoute b.txt

    result = worktrees.integrate(meta)
    assert result["ok"] and result["state"] == "integrated"
    assert (repo / "b.txt").exists()                                   # merge appliqué
    assert (repo / "a.txt").read_text() == "WIP humain non commité\n"  # WIP restauré (intact)
    assert worktrees._tracked_dirty(str(repo))                         # toujours sale = bien restauré


def test_real_content_conflict_yields_conflict_state(tmp_path):
    """CAS 5 : vrai conflit de contenu → état conflict, aucun merge, repo principal intact."""
    repo, base = _make_repo(tmp_path)
    worktrees.WORKTREES_DIR = tmp_path / "c5"
    meta = worktrees.provision(str(repo), "tk5", base_branch=base, with_venv=False)
    (Path(meta["worktree"]) / "a.txt").write_text("version agent\n")
    worktrees.harvest(meta, "edite a (agent)")
    (repo / "a.txt").write_text("version base\n")                       # divergence sur la base
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "edite a (base)")

    result = worktrees.integrate(meta)
    assert result["state"] == "conflict" and "a.txt" in result["files"]
    assert (repo / "a.txt").read_text() == "version base\n"             # repo principal intact


def test_integrate_is_idempotent(tmp_path):
    """CAS 6 : re-intégrer un ticket déjà mergé = no-op (pas de nouveau merge)."""
    worktrees.WORKTREES_DIR = tmp_path / "c6"
    repo, base = _make_repo(tmp_path)
    ticket = livre("proj", "agent-d", title="ajoute d")  # seul un ticket LIVRÉ s'intègre
    meta = worktrees.provision(str(repo), ticket["id"], base_branch=base, with_venv=False)
    (Path(meta["worktree"]) / "d.txt").write_text("contenu\n")
    tickets.poser("proj", ticket, worktree=meta)

    first = integration.integrate_ticket("proj", ticket)
    assert first["ok"] and first["state"] == etats.CLOSED
    head_after_first = _head(repo, base)

    second = integration.integrate_ticket("proj", ticket)              # rejoué
    assert not second["ok"]                                            # no-op
    assert _head(repo, base) == head_after_first                       # base inchangée


def test_untracked_collision_merges_and_keeps_human_file_in_stash(tmp_path):
    """Sous-cas : untracked de l'humain qui collisionne avec un fichier ajouté par l'enfant.
    On ne bloque plus TOUT le merge pour ça : il s'intègre, et le fichier de l'humain n'est pas
    perdu — il reste RÉCUPÉRABLE dans la pile `git stash` (pop en conflit, jamais écrasé)."""
    repo, base = _make_repo(tmp_path)
    meta = _harvested_meta(repo, base, tmp_path, "c7", filename="collision.txt")
    (repo / "collision.txt").write_text("contenu humain\n")            # untracked qui collisionne

    result = worktrees.integrate(meta)
    assert result["ok"] and result["state"] == "integrated"
    assert (repo / "collision.txt").exists()                          # merge appliqué
    stash = subprocess.run(["git", "-C", str(repo), "stash", "list"],
                           capture_output=True, text=True)
    assert stash.stdout.strip()                                       # contenu humain préservé (stash)


def test_integrate_ticket_merges_and_cleans(tmp_path):
    """Bout-en-bout (sans agent) : harvest commit → merge dans la base → cleanup."""
    worktrees.WORKTREES_DIR = tmp_path / "wts3"
    repo, base = _make_repo(tmp_path)

    ticket = livre("proj", "agent-c", title="ajoute c")  # seul un ticket LIVRÉ s'intègre
    meta = worktrees.provision(str(repo), ticket["id"], base_branch=base, with_venv=False)
    (Path(meta["worktree"]) / "c.txt").write_text("contenu\n")
    tickets.poser("proj", ticket, worktree=meta)

    result = integration.integrate_ticket("proj", ticket)
    assert result["ok"] and result["state"] == etats.CLOSED
    assert (repo / "c.txt").exists()                       # mergé dans la base
    assert not Path(meta["worktree"]).exists()             # worktree nettoyé
    fresh = tickets.get_ticket("proj", ticket["id"])
    assert fresh["worktree"]["retire_at"] and fresh["integration"]["merged_at"]
    assert fresh["state_reason"]["code"] == "integre"


def test_current_branch_is_the_live_checkout_not_develop(tmp_path):
    """LE FIX : le worktree d'un agent doit partir de la branche VIVE (celle checkout dans
    l'arbre principal = ce que le serveur exécute), pas de `develop` hardcodé. Sinon l'agent
    développe sur une branche invisible au serveur (cf. divergence session↔develop)."""
    worktrees.WORKTREES_DIR = tmp_path / "wts_live"
    repo, _ = _make_repo(tmp_path)
    _git(repo, "branch", "develop")                        # develop existe mais n'est PAS vive
    _git(repo, "checkout", "-q", "-b", "session/live")     # branche vive = session/live
    assert worktrees.current_branch(str(repo)) == "session/live"
    # provision via current_branch → meta['base'] = branche vive (base ET cible de merge).
    meta = worktrees.provision(str(repo), "tk-live",
                               base_branch=worktrees.current_branch(str(repo)), with_venv=False)
    assert meta["ok"] and meta["base"] == "session/live"


def test_discard_stale_allows_reprovision_after_reap(tmp_path):
    """Retry ISOLÉ en place : après reap, la branche `agent/<id>` survit → une re-provision
    naïve échoue ('branch already exists'). `discard_stale` la purge et la re-provision réussit
    en réutilisant l'id (pas de ticket doublon)."""
    worktrees.WORKTREES_DIR = tmp_path / "wts_retry"
    repo, base = _make_repo(tmp_path)

    meta1 = worktrees.provision(str(repo), "retry1", base_branch=base, with_venv=False)
    assert meta1["ok"] and Path(meta1["worktree"]).is_dir()

    _git(repo, "worktree", "remove", "--force", meta1["worktree"])   # simule le reap
    assert not Path(meta1["worktree"]).is_dir()                      # ... mais agent/retry1 subsiste

    naive = worktrees.provision(str(repo), "retry1", base_branch=base, with_venv=False)
    assert not naive["ok"]                                           # confirme le bug

    worktrees.discard_stale(str(repo), "retry1")
    meta2 = worktrees.provision(str(repo), "retry1", base_branch=base, with_venv=False)
    assert meta2["ok"] and Path(meta2["worktree"]).is_dir()          # re-provision réussie


def test_harvest_handles_utf8_diff(tmp_path):
    """Régression Windows : un diff avec du non-ASCII (accents FR, emoji) ne crashe PAS le
    harvest. git émet de l'UTF-8 ; `text=True` seul décode en cp1252 → UnicodeDecodeError →
    stdout None → harvest/validate/merge en 500 (bloquait tous les tickets UI FR)."""
    worktrees.WORKTREES_DIR = tmp_path / "wts_utf8"
    repo, base = _make_repo(tmp_path)
    meta = worktrees.provision(str(repo), "utf8", base_branch=base, with_venv=False)
    (Path(meta["worktree"]) / "accents.py").write_text(
        "# eaou rôle 🚀 « obsolète »\nMSG = 'Votre version est obsolète'\n", encoding="utf-8")
    h = worktrees.harvest(meta, "ajoute accents")
    assert h["committed"] and "accents.py" in h["files"]
    assert "obsol" in h["diff"]


def test_add_run_clears_stale_terminal_flags(tmp_path):
    """Un nouveau run RÉ-ACTIVE le ticket : la relance d'un ticket planté repart `running`
    sans la raison du cycle précédent (C9 : purge par construction, plus de drapeaux)."""
    t = semer("proj", "t1", etats.STOPPED, "crashed", runs=[run("agent1")])

    tickets.add_run("proj", t, "agent2", "work", "")

    fresh = tickets.get_ticket("proj", t["id"])
    assert (fresh["state"], fresh.get("state_reason")) == (etats.RUNNING, None)  # persisté
    assert t["state"] == etats.RUNNING                                         # objet appelant
    assert "crashed" not in fresh and "reaped" not in fresh


def test_current_branch_detached_head_falls_back(tmp_path):
    """HEAD détaché → repli sur default_branch (jamais une chaîne vide qui casserait git)."""
    repo, _ = _make_repo(tmp_path)
    sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    _git(repo, "checkout", "-q", sha)                      # HEAD détaché
    assert worktrees.current_branch(str(repo)) == worktrees.default_branch(str(repo))


def _repo_on_branch(tmp: Path, branch: str) -> Path:
    """Depot git jetable dont la branche courante est `branch`, avec un commit."""
    repo = tmp / f"repo_{branch}"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", branch], cwd=repo, check=True)
    return repo


def _set_origin_head(repo: Path, branch: str) -> None:
    """Simule origin/HEAD sans remote reel : symbolic-ref se lit sans que la cible existe."""
    subprocess.run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD", f"refs/remotes/origin/{branch}"],
        cwd=repo,
        check=True,
    )


def test_default_branch_prefers_local_develop_over_origin_head(tmp_path):
    repo = _repo_on_branch(tmp_path, "develop")
    _set_origin_head(repo, "master")
    assert worktrees.default_branch(str(repo)) == "develop"


def test_default_branch_falls_back_to_origin_head_without_develop(tmp_path):
    repo = _repo_on_branch(tmp_path, "trunk")
    _set_origin_head(repo, "master")
    # La branche annoncée par origin/HEAD doit EXISTER localement : `git worktree add <base>`
    # ne fait aucun DWIM remote, une base seulement distante donnerait
    # `fatal: invalid reference: master`. Le cas « origin/HEAD non local » est couvert par
    # test_worktrees_default_branch.py (on retombe alors sur la branche sortie).
    subprocess.run(["git", "branch", "master"], cwd=repo, check=True)
    assert worktrees.default_branch(str(repo)) == "master"


def test_default_branch_prefers_master_over_main(tmp_path):
    """`master` passe avant `main` : les dépôts de ce parc travaillent sur `master`."""
    repo = _repo_on_branch(tmp_path, "master")
    subprocess.run(["git", "branch", "main"], cwd=repo, check=True)
    assert worktrees.default_branch(str(repo)) == "master"


def test_current_branch_detached_head_uses_new_order(tmp_path):
    repo = _repo_on_branch(tmp_path, "develop")
    _set_origin_head(repo, "master")
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    subprocess.run(["git", "checkout", sha], cwd=repo, check=True, capture_output=True)
    assert worktrees.current_branch(str(repo)) == "develop"