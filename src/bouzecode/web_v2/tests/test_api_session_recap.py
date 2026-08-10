# [desc] Tests pytest du vrai endpoint GET /api/sessions/&lt;key&gt;/recap : tri/isolation tests serveur + fallback recap absent. [/desc]
"""On monte l'app Flask réelle et on appelle le VRAI endpoint via le test client.

La session est une session « daily » écrite sur disque dans un répertoire temporaire
(DAILY_DIR monkeypatché), donc `store.resolve` la retrouve sans dépendre d'un runner
d'agent. On vérifie que le SERVEUR fait tout le tri (ordre = recap.changes, section
« Autres modifications » pour les fichiers hors changes, isolation des test_*.py en fin,
is_test correct) et le fallback quand le recap est absent."""
from __future__ import annotations

import json

import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services.sessions import store


# Diff git RÉEL multi-fichiers : deux fichiers de code (un dans recap.changes, un hors
# changes), un test corrigé (existant) et un test neuf (new file mode). Dérivé d'un vrai
# `git diff base...branch`.
_DIFF = """diff --git a/src/pkg/service.py b/src/pkg/service.py
index 1111111..2222222 100644
--- a/src/pkg/service.py
+++ b/src/pkg/service.py
@@ -1,3 +1,3 @@
 def run():
-    return 1
+    return 2
diff --git a/src/pkg/helper.py b/src/pkg/helper.py
index 3333333..4444444 100644
--- a/src/pkg/helper.py
+++ b/src/pkg/helper.py
@@ -1,2 +1,2 @@
-x = 0
+x = 1
diff --git a/tests/test_service.py b/tests/test_service.py
index 5555555..6666666 100644
--- a/tests/test_service.py
+++ b/tests/test_service.py
@@ -1,2 +1,2 @@
-assert run() == 1
+assert run() == 2
diff --git a/tests/test_helper.py b/tests/test_helper.py
new file mode 100644
index 0000000..7777777
--- /dev/null
+++ b/tests/test_helper.py
@@ -0,0 +1,2 @@
+def test_helper():
+    assert x == 1
"""

# Snapshots par fichier (contrat ACTUEL de la route /recap : `data['file_snapshots']`,
# assemblés par assemble_recap_diffs). Dérivés du même changement que _DIFF ci-dessus :
# deux fichiers de code (service.py dans recap.changes, helper.py hors changes), un test
# corrigé (existant) et un test neuf (is_new). before/after → patch difflib côté serveur.
_SNAPSHOTS = {
    "src/pkg/service.py": {
        "before": "def run():\n    return 1\n",
        "after": "def run():\n    return 2\n",
    },
    "src/pkg/helper.py": {
        "before": "x = 0\n",
        "after": "x = 1\n",
    },
    "tests/test_service.py": {
        "before": "assert run() == 1\n",
        "after": "assert run() == 2\n",
    },
    "tests/test_helper.py": {
        "before": "",
        "after": "def test_helper():\n    assert x == 1\n",
        "is_new": True,
    },
}


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    return app.test_client()


def _write_daily_session(daily_dir, data: dict) -> str:
    """Écrit une session daily réelle et renvoie la clé résolvable par store."""
    date = "2026-07-06"
    name = "session_test.json"
    day = daily_dir / date
    day.mkdir(parents=True, exist_ok=True)
    (day / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return f"daily/{date}/{name}"


def test_recap_endpoint_orders_and_isolates_tests(monkeypatch, client, tmp_path):
    monkeypatch.setattr(store, "DAILY_DIR", tmp_path)
    recap = {
        "symptoms": "Ça plante à la fin.",
        "explanation": "On renvoie 2 au lieu de 1.",
        "tests": "2 tests pytest verts.",
        # helper.py N'EST PAS dans changes → doit atterrir en « Autres modifications ».
        "changes": [{"file": "src/pkg/service.py", "summary": "corrige run()"}],
    }
    key = _write_daily_session(tmp_path, {"recap": recap, "file_snapshots": _SNAPSHOTS})

    resp = client.get(f"/api/sessions/{key}/recap")
    assert resp.status_code == 200
    body = resp.get_json()

    assert body["recap"] == recap
    assert body["recap_missing"] is False

    diffs = body["diffs"]
    files = [d["file"] for d in diffs]
    # Ordre serveur : changes (service.py) → other (helper.py) → tests (neuf puis corrigé).
    assert files == [
        "src/pkg/service.py",
        "src/pkg/helper.py",
        "tests/test_helper.py",
        "tests/test_service.py",
    ]
    by_file = {d["file"]: d for d in diffs}
    assert by_file["src/pkg/service.py"]["section"] == "changes"
    assert by_file["src/pkg/helper.py"]["section"] == "other"
    assert by_file["tests/test_helper.py"]["section"] == "tests"
    assert by_file["tests/test_service.py"]["section"] == "tests"
    # is_test correct côté serveur.
    assert by_file["src/pkg/service.py"]["is_test"] is False
    assert by_file["tests/test_helper.py"]["is_test"] is True
    # Chaque item porte son patch (le front n'a rien à recalculer).
    assert "def run():" in by_file["src/pkg/service.py"]["patch"]
    # Contenus complets avant/après (alimentent Monaco createDiffEditor côté front).
    assert by_file["src/pkg/service.py"]["original"] == "def run():\n    return 1\n"
    assert by_file["src/pkg/service.py"]["modified"] == "def run():\n    return 2\n"
    # Fichier neuf : original vide, modified rempli.
    assert by_file["tests/test_helper.py"]["original"] == ""
    assert by_file["tests/test_helper.py"]["modified"] == "def test_helper():\n    assert x == 1\n"


def test_recap_endpoint_fallback_without_recap(monkeypatch, client, tmp_path):
    monkeypatch.setattr(store, "DAILY_DIR", tmp_path)
    # Session historique : pas de recap, mais des snapshots persistés.
    key = _write_daily_session(tmp_path, {"file_snapshots": _SNAPSHOTS})

    resp = client.get(f"/api/sessions/{key}/recap")
    assert resp.status_code == 200
    body = resp.get_json()

    assert body["recap_missing"] is True
    diffs = body["diffs"]
    files = [d["file"] for d in diffs]
    # Fallback : tous les fichiers triés alphabétiquement, aucun tri par narration.
    assert files == sorted(files)
    assert all(d["section"] == "all" for d in diffs)
    # is_test reste correct même en fallback.
    by_file = {d["file"]: d for d in diffs}
    assert by_file["tests/test_helper.py"]["is_test"] is True


def test_recap_endpoint_no_diff_returns_empty_list(monkeypatch, client, tmp_path):
    monkeypatch.setattr(store, "DAILY_DIR", tmp_path)
    recap = {"symptoms": "x", "explanation": "y", "tests": "z", "changes": []}
    key = _write_daily_session(tmp_path, {"recap": recap})

    resp = client.get(f"/api/sessions/{key}/recap")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["recap"] == recap
    assert body["diffs"] == []


def test_recap_endpoint_uses_git_diff_when_snapshots_empty(monkeypatch, client, tmp_path):
    """Bug Manager/Python : file_snapshots persiste VIDE en flux headless web_v2, mais le
    git diff TEXTE (data['diff']) survit. L'endpoint doit s'en servir en fallback → diffs
    présents et sectionnés au lieu d'une liste vide."""
    monkeypatch.setattr(store, "DAILY_DIR", tmp_path)
    recap = {
        "symptoms": "x", "explanation": "y", "tests": "z",
        "changes": [{"file": "src/pkg/service.py", "summary": "corrige run()"}],
    }
    key = _write_daily_session(tmp_path, {"recap": recap, "file_snapshots": {}, "diff": _DIFF})

    resp = client.get(f"/api/sessions/{key}/recap")
    assert resp.status_code == 200
    body = resp.get_json()

    assert body["recap"] == recap
    diffs = body["diffs"]
    files = [d["file"] for d in diffs]
    # Diffs reconstruits depuis le git diff text, mêmes sections/ordre que le chemin snapshots.
    assert files == [
        "src/pkg/service.py",
        "src/pkg/helper.py",
        "tests/test_helper.py",
        "tests/test_service.py",
    ]
    by_file = {d["file"]: d for d in diffs}
    assert by_file["src/pkg/service.py"]["section"] == "changes"
    assert by_file["src/pkg/helper.py"]["section"] == "other"
    assert by_file["tests/test_helper.py"]["section"] == "tests"
    # Chaque item porte son patch (le front rend en <pre> quand original/modified absents).
    assert "def run():" in by_file["src/pkg/service.py"]["patch"]
    assert by_file["tests/test_helper.py"]["is_new"] is True
