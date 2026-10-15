"""Le récap d'une session affiche des chemins RELATIFS au dépôt, jamais le chemin absolu du
worktree jetable (…/worktrees/<repo>/<ticket>/…) — ni dans la liste des fichiers, ni dans
l'en-tête du patch. Prouvé par le vrai endpoint `GET /api/sessions/<key>/recap`."""
from __future__ import annotations

import json

import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services.sessions import store

_WORKTREE = r"C:\Users\u\.bouzecode\worktrees\bouzecode\tk1"


@pytest.fixture
def recap_de(monkeypatch, tmp_path):
    """Écrit une session « daily » et renvoie le JSON servi par l'endpoint recap."""
    monkeypatch.setattr(store, "DAILY_DIR", tmp_path)
    client = create_app().test_client()

    def servir(data: dict) -> dict:
        day = tmp_path / "2026-07-06"
        day.mkdir(parents=True, exist_ok=True)
        (day / "s.json").write_text(json.dumps(data), encoding="utf-8")
        resp = client.get("/api/sessions/daily/2026-07-06/s.json/recap")
        assert resp.status_code == 200
        return resp.get_json()

    return servir


def test_un_fichier_du_worktree_s_affiche_relatif_au_depot(recap_de):
    body = recap_de({
        "recap": {"changes": [{"file": "src/pkg/service.py", "summary": "fix"}]},
        "file_snapshots": {
            _WORKTREE + r"\src\pkg\service.py": {"before": "a\n", "after": "b\n"},
            _WORKTREE + r"\tests\test_service.py": {"before": "", "after": "x\n", "is_new": True},
        },
    })
    assert [(d["file"], d["section"]) for d in body["diffs"]] == [
        ("src/pkg/service.py", "changes"),
        ("tests/test_service.py", "tests"),
    ]
    assert "a/src/pkg/service.py" in body["diffs"][0]["patch"]
    assert "worktrees" not in body["diffs"][0]["patch"]


def test_un_chemin_deja_relatif_n_est_que_normalise(recap_de):
    body = recap_de({
        "recap": {"changes": []},
        "file_snapshots": {r"src\pkg\a.py": {"before": "", "after": "x\n"}},
    })
    assert [d["file"] for d in body["diffs"]] == ["src/pkg/a.py"]


def test_un_chemin_absolu_hors_worktree_garde_son_nom_en_slashes(recap_de):
    body = recap_de({
        "recap": {"changes": []},
        "file_snapshots": {r"D:\other\x.py": {"before": "", "after": "x\n"}},
    })
    assert [d["file"] for d in body["diffs"]] == ["D:/other/x.py"]
