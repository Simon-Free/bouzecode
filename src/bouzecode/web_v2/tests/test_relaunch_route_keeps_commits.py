# [desc] Le geste exact du 28/07 : POST .../launch avec un corps VIDE ne doit rien effacer. [/desc]
"""`POST /api/tickets/<slug>/<id>/launch` appelé avec `{}`.

Le corps vide n'est pas un « lancement neutre » : `isolation` retombe sur celle INSCRITE
sur le ticket (`worktree`), donc la route re-provisionne — et re-provisionner détruisait la
branche. C'est par cette porte que quatre tickets ont perdu leur livraison le 28/07.

Ce test joue la route RÉELLE sur un VRAI dépôt : seuls le spawn de l'agent (aucun process
ne doit naître d'un test) et la résolution du projet sont remplacés."""
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from bouzecode.web_v2 import api_sanity
from bouzecode.web_v2.routes.work import tickets as troute
from bouzecode.web_v2.services.work import tickets, worktrees

SLUG = "proj-relance-http"


def git(cwd, *args: str) -> str:
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    assert res.returncode == 0, f"git {' '.join(args)} → {res.stderr}"
    return res.stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "projet"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@t.t")
    git(root, "config", "user.name", "t")
    (root / "README.md").write_text("init\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    git(root, "branch", "-M", "develop")
    return root


@pytest.fixture()
def relancer(monkeypatch, repo):
    """Relance un ticket LIVRÉ via l'API réelle et renvoie (sha livré, cwd du nouvel agent)."""
    from bouzecode.web_v2.app import create_app

    monkeypatch.setattr(api_sanity, "require_api_sanity", lambda: None)
    monkeypatch.setattr(troute, "_project_or_404",
                        lambda slug: ({"path": str(repo), "name": "P", "slug": slug}, None))
    spawned: dict = {}
    monkeypatch.setattr(troute.runner, "create_agent",
                        lambda prompt, model, cwd, **kw: spawned.update(cwd=cwd)
                        or SimpleNamespace(agent_id="relance-1"))
    app = create_app()
    app.config["TESTING"] = True

    def _post() -> dict:
        ticket = tickets.create_ticket(SLUG, "ticket livré", "refais-le")
        meta = worktrees.provision(str(repo), ticket["id"], base_branch="develop",
                                   with_venv=False)
        assert meta["ok"], meta
        (Path(meta["worktree"]) / "livraison.py").write_text("x = 1\n", encoding="utf-8")
        git(meta["worktree"], "add", "-A")
        git(meta["worktree"], "commit", "-q", "-m", "agent: travail livré")
        livre = git(meta["worktree"], "rev-parse", "HEAD")
        ticket["isolation"] = "worktree"
        ticket["worktree"] = meta
        tickets.update_ticket(SLUG, ticket)

        with app.test_client() as client:
            reponse = client.post(f"/api/tickets/{SLUG}/{ticket['id']}/launch", json={})
        assert reponse.status_code == 200, reponse.get_data(as_text=True)
        return {"livre": livre, "cwd": spawned["cwd"],
                "ticket": tickets.get_ticket(SLUG, ticket["id"])}

    return _post


def test_le_corps_vide_ne_detruit_pas_la_livraison(relancer, repo):
    """Le commit livré est encore là, et la branche du ticket le porte toujours."""
    resultat = relancer()

    assert git(repo, "rev-parse", resultat["ticket"]["worktree"]["branch"]) == resultat["livre"]


def test_le_nouvel_agent_travaille_sur_la_livraison_precedente(relancer):
    """Le cwd rendu à l'agent relancé contient le travail de son prédécesseur."""
    resultat = relancer()

    assert (Path(resultat["cwd"]) / "livraison.py").is_file()


def test_la_relance_est_expliquee_sur_le_ticket(relancer):
    """Reprendre une branche existante est une décision : elle est dite, pas subie."""
    commentaires = [c["text"] for c in relancer()["ticket"]["comments"]]

    assert any("branche existante" in texte for texte in commentaires)
