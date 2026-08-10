"""Le vrai poste disque, ce sont les `.venv` des bacs à sable : 82 Go sur les 104 Go de
`~/.bouzecode`, ~1 Go par worktree, jamais partagés.

Ce que ces tests protègent : qu'on ne récupère QUE du reproductible (un venv se refait par
`uv sync`) et JAMAIS un bac à sable dont un agent se sert ou dont le ticket est encore ouvert.

Aucun mock : de vrais dossiers `.venv` sur disque, de vrais tickets dans le store.
"""
import json
import os

import pytest

from bouzecode.web_v2.services.work import tickets, worktree_disk, worktrees

SLUG = "projet-test"


@pytest.fixture()
def sandbox_root(tmp_path, monkeypatch):
    """Racine de worktrees isolée, avec le registre de projets pointant sur le store de test."""
    from bouzecode.web_v2.services.work import projects

    root = tmp_path / "worktrees"
    (root / "depot").mkdir(parents=True)
    monkeypatch.setattr(worktrees, "WORKTREES_DIR", root)
    registre = tmp_path / "projects.json"
    registre.write_text(json.dumps(
        [{"slug": SLUG, "name": "Test", "path": str(tmp_path / "depot")}]), encoding="utf-8")
    monkeypatch.setattr(projects, "PROJECTS_PATH", registre)
    return root / "depot"


def _sandbox(root, ticket_id, *, venv_poids=2048, code=True):
    """Un bac à sable avec son `.venv` (et du code non commité, qu'on ne doit jamais toucher)."""
    d = root / ticket_id
    (d / ".venv" / "Lib").mkdir(parents=True)
    (d / ".venv" / "Lib" / "paquet.py").write_text("x" * venv_poids, encoding="utf-8")
    if code:
        (d / "travail_non_commite.py").write_text("print('mon travail')", encoding="utf-8")
    return d


def test_l_inventaire_dit_le_poids_des_venvs_par_classe(sandbox_root):
    """Premier besoin : savoir où sont les gigaoctets, et lesquels sont récupérables."""
    ticket = tickets.create_ticket(SLUG, "en cours", "travaille")
    _sandbox(sandbox_root, ticket["id"])
    _sandbox(sandbox_root, "aaaaaaaa")  # aucun ticket de ce nom → inconnu

    etat = worktree_disk.inventory()

    assert etat["venvs"] == 2
    assert etat["par_classe"]["ouvert"]["venvs"] == 1
    assert etat["par_classe"]["inconnu"]["venvs"] == 1
    assert [r["ticket_id"] for r in etat["recuperable"]] == ["aaaaaaaa"]


def test_un_ticket_encore_ouvert_garde_son_environnement(sandbox_root):
    """Lui reprendre son venv, c'est lui refaire payer un `uv sync` de plusieurs minutes à la
    reprise : fausse économie."""
    ticket = tickets.create_ticket(SLUG, "en cours", "travaille")
    _sandbox(sandbox_root, ticket["id"])

    assert worktree_disk.reclaim_venvs()["venvs"] == 0


def test_un_ticket_termine_rend_son_environnement(sandbox_root):
    """Mergé, archivé ou clos : plus personne ne reprendra ce bac à sable."""
    ticket = tickets.create_ticket(SLUG, "fini", "c'était à faire")
    tickets.archive_ticket(SLUG, ticket["id"])
    _sandbox(sandbox_root, ticket["id"])

    simulation = worktree_disk.reclaim_venvs()

    assert [d["ticket_id"] for d in simulation["detail"]] == [ticket["id"]]
    assert simulation["bytes"] > 2000


def test_un_agent_vivant_rend_son_bac_a_sable_intouchable(sandbox_root, tmp_path, monkeypatch):
    """La garde essentielle : un agent qui TOURNE se sert de son venv à l'instant même, quel
    que soit l'état de son ticket."""
    from bouzecode.web_v2.runtime import runner

    ticket = tickets.create_ticket(SLUG, "fini sur le papier", "…")
    tickets.archive_ticket(SLUG, ticket["id"])
    _sandbox(sandbox_root, ticket["id"])
    agents = tmp_path / "web_agents"
    agents.mkdir()
    monkeypatch.setattr(runner, "AGENTS_DIR", agents)
    (agents / "abcdef123456.json").write_text(json.dumps({
        "agent_id": "abcdef123456", "prompt": "je travaille", "model": "m",
        "cwd": str(sandbox_root / ticket["id"]), "pid": os.getpid(), "returncode": None,
        "started_at": "2026-07-30T10:00:00Z", "ticket_id": ticket["id"],
        "session_path": str(agents / "abcdef123456.session.json"), "ipc_dir": "",
    }), encoding="utf-8")
    (agents / "abcdef123456.session.json").write_text('{"messages": []}', encoding="utf-8")
    runner._list_agents_cache.clear()

    assert worktree_disk.reclaim_venvs()["venvs"] == 0
    runner._list_agents_cache.clear()


def test_une_jonction_vers_un_vrai_depot_n_est_jamais_touchee(sandbox_root, monkeypatch):
    """LE BUG DU 2026-07-30, verrouillé ici : `worktree_sources.link_editable_sources` crée
    dans cet arbre des JONCTIONS vers les vrais dépôts (`worktrees/demo_app/
    bouzecode` → `dev/demo_monorepo/bouzecode`). Prises pour des bacs à sable, elles ont
    fait suivre le lien à `shutil.rmtree`, qui a effacé le `.venv` du dépôt principal — celui
    qui lance le serveur et les tests.

    Un lien n'entre donc ni dans l'inventaire ni dans la récupération, et le venv qu'il
    désigne reste intact."""
    if not hasattr(os, "add_dll_directory"):  # pragma: no cover — jonctions = Windows
        pytest.skip("les jonctions sont un mécanisme Windows")
    import subprocess
    from bouzecode.web_v2.tests.production_isolation import autoriser_la_destruction
    autoriser_la_destruction(monkeypatch)

    vrai_depot = sandbox_root.parent.parent / "vrai_depot"
    (vrai_depot / ".venv" / "Lib").mkdir(parents=True)
    (vrai_depot / ".venv" / "pyvenv.cfg").write_text("home = quelque part", encoding="utf-8")
    lien = sandbox_root / "vrai_depot"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(lien), str(vrai_depot)],
                   check=True, capture_output=True)

    assert worktree_disk.inventory()["venvs"] == 0  # le lien n'est pas un bac à sable
    assert worktree_disk.reclaim_venvs(confirm=True)["supprimes"] == []
    assert (vrai_depot / ".venv" / "pyvenv.cfg").is_file()  # le VRAI venv est intact


def test_la_recuperation_confirmee_n_efface_que_le_venv(sandbox_root, monkeypatch):
    """Le venv part, le TRAVAIL RESTE : c'est toute la différence entre récupérer un artefact
    reproductible et détruire du code."""
    from bouzecode.web_v2.tests.production_isolation import autoriser_la_destruction
    autoriser_la_destruction(monkeypatch)
    bac = _sandbox(sandbox_root, "bbbbbbbb")

    resultat = worktree_disk.reclaim_venvs(confirm=True)

    assert resultat["supprimes"] == ["bbbbbbbb"]
    assert not (bac / ".venv").exists()
    assert (bac / "travail_non_commite.py").read_text(encoding="utf-8") == "print('mon travail')"
