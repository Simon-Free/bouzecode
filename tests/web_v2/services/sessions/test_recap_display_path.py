"""Les diffs de récap doivent afficher un chemin RELATIF au dépôt, pas le chemin absolu
Windows du worktree jetable (…/worktrees/<repo>/<ticket>/…). Fonction pure → pas de mock."""
from bouzecode.web_v2.services import recap_service


def test_display_path_strips_worktree_prefix():
    p = (r"C:\Users\u\.bouzecode\worktrees\bouzecode\5c5551f3"
         r"\src\bouzecode\web_v2\services\oxford_join.py")
    assert recap_service._display_path(p) == "src/bouzecode/web_v2/services/oxford_join.py"


def test_display_path_relative_unchanged_but_normalized():
    assert recap_service._display_path("src/pkg/a.py") == "src/pkg/a.py"
    assert recap_service._display_path(r"src\pkg\a.py") == "src/pkg/a.py"


def test_display_path_absolute_non_worktree_left_as_relative_slashes():
    # Hors worktree : pas de préfixe reconnu → on garde le chemin (slashes normalisés).
    assert recap_service._display_path(r"D:\other\x.py") == "D:/other/x.py"


def test_assemble_relativizes_and_orders_by_relative_changes():
    wt = r"C:\Users\u\.bouzecode\worktrees\bouzecode\tk1"
    snapshots = {
        wt + r"\src\pkg\service.py": {"before": "a\n", "after": "b\n"},
        wt + r"\tests\test_service.py": {"before": "", "after": "def t(): pass\n", "is_new": True},
    }
    recap = {"changes": [{"file": "src/pkg/service.py", "summary": "fix"}]}
    diffs = recap_service.assemble_recap_diffs(recap, snapshots)
    files = [(d["file"], d["section"]) for d in diffs]
    # chemins relatifs affichés + code dans 'changes' (match exact via chemin relatif), test isolé.
    assert files == [
        ("src/pkg/service.py", "changes"),
        ("tests/test_service.py", "tests"),
    ]
    # l'en-tête du patch porte aussi le chemin relatif, pas l'absolu worktree.
    assert "a/src/pkg/service.py" in diffs[0]["patch"]
    assert "worktrees" not in diffs[0]["patch"]
