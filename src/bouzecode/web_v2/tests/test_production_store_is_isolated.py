"""La suite de tests ne doit jamais écrire dans les données réelles de l'utilisateur.

Régression réelle : `conftest._isolate_production_state` ne redirigeait que
`tickets.TICKETS_DIR`, un simple ré-export. La base SQLite est ouverte par
`_persistence._db_path()`, qui lit `_persistence.TICKETS_DIR` — restée pointée sur
`~/.bouzecode`. Résultat : 1152 lignes de fixtures (slugs « proj » et « p ») semées
dans le magasin de tickets de production, et une suite non déterministe.
"""
from __future__ import annotations

from pathlib import Path

from bouzecode.web_v2.services.work import _persistence, projects, tickets, worktrees

PRODUCTION_ROOT = Path.home() / ".bouzecode"


def _is_isolated(path: Path) -> bool:
    """Vrai si le chemin est hors du répertoire de données réel de l'utilisateur."""
    return PRODUCTION_ROOT not in Path(path).resolve().parents


def test_the_ticket_database_never_points_at_the_real_user_data():
    """La base de tickets ouverte pendant un test est un fichier temporaire, jamais celle de l'utilisateur."""
    assert _is_isolated(_persistence._db_path())


def test_every_isolated_path_really_leaves_the_user_data_alone():
    """Les quatre emplacements que la fixture redirige pointent tous hors de ~/.bouzecode."""
    for label, path in {
        "_persistence.TICKETS_DIR": _persistence.TICKETS_DIR,
        "tickets.TICKETS_DIR": tickets.TICKETS_DIR,
        "worktrees.WORKTREES_DIR": worktrees.WORKTREES_DIR,
        "projects.PROJECTS_PATH": projects.PROJECTS_PATH,
    }.items():
        assert _is_isolated(path), f"{label} pointe encore vers les données réelles : {path}"


def test_creating_a_ticket_writes_to_the_temporary_store():
    """Créer un ticket pendant un test remplit la base temporaire, et elle seule."""
    ticket = tickets.create_ticket("un-projet", "Un titre", "Un prompt")
    assert ticket["id"]
    database = _persistence._db_path()
    assert _is_isolated(database)
    assert database.is_file(), "le ticket a été écrit ailleurs que dans la base isolée"
