# [desc] Fixture autouse : isole l'état PRODUCTION (tickets + worktrees) sous tmp pour CHAQUE test. [/desc]
"""Garde-fou global d'isolation. Un test non isolé écrivait `~/.bouzecode/web_v2/tickets/<slug>.json`
RÉEL ; pendant qu'un serveur tourne, ces écritures concurrentes se concaténaient (« Extra data »)
→ corruption du store de PRODUCTION (perte de tickets → worktrees orphelins). Cette fixture autouse
redirige `tickets.TICKETS_DIR` et `worktrees.WORKTREES_DIR` vers un tmp par test, si bien qu'AUCUN
test ne peut plus toucher l'état réel. Les tests qui posent leur propre chemin (ex. `hermetic`)
l'emportent : ils tournent APRÈS l'autouse et réécrivent la même cible."""
import os

import pytest

# AVANT tout import qui pourrait construire l'app : `create_app()` (app.py:141) arme
# `wake.start_poller()`, un thread DÉMON qui rejoue `tick()` en boucle — donc APRÈS les
# teardowns qui rendent `AGENTS_DIR` au parc RÉEL, d'où des `kill_agent` asynchrones sur de
# vrais agents. `start_poller` lit `BOUZECODE_WAKE_POLLER` == "0" ; l'ancien
# `BOUZECODE_DISABLE_WAKE_POLLER` de `tests/conftest.py` ne correspond à AUCUN lecteur.
os.environ.setdefault("BOUZECODE_WAKE_POLLER", "0")

from bouzecode.web_v2.services.sessions import listing_cache, meta_index  # noqa: E402
from bouzecode.web_v2.services.work import (  # noqa: E402
    _persistence, projects, tickets, worktrees,
)
from bouzecode.web_v2.tests.production_isolation import (  # noqa: E402
    isoler_le_parc_d_agents,
)


@pytest.fixture(autouse=True)
def _forget_session_caches():
    """Vide les caches process du listing de sessions (memo de méta + cache TTL) autour de
    CHAQUE test : sinon un test verrait la méta ou le listing mémorisés par le précédent."""
    meta_index.reset_memo()
    listing_cache.reset()
    yield
    meta_index.reset_memo()
    listing_cache.reset()


@pytest.fixture(autouse=True)
def _isolate_production_state(tmp_path, monkeypatch):
    # `tickets.TICKETS_DIR` n'est qu'un RÉ-EXPORT : la base SQLite est ouverte par
    # `_persistence._db_path()`, qui lit `_persistence.TICKETS_DIR`. Ne patcher que le
    # ré-export laissait donc TOUTES les écritures SQLite tomber dans le store RÉEL —
    # 1152 lignes de fixtures y avaient été semées avant que ce soit vu. On patche la
    # source (pour la base) ET le ré-export (pour les chemins .json historiques encore
    # lus par auto_resume / interrupted_report / migrations).
    tickets_dir = tmp_path / "tickets"
    monkeypatch.setattr(_persistence, "TICKETS_DIR", tickets_dir)
    monkeypatch.setattr(tickets, "TICKETS_DIR", tickets_dir)
    # `_migrated` mémorise les slugs déjà importés du JSON legacy. C'est un set de PROCESS :
    # sans ce reset, le 1er test à toucher un slug le marque migré pour TOUS les suivants, qui
    # voient alors un store VIDE là où ils croient avoir semé (vacuité prouvée sur
    # test_subagent_events). Chaque test a sa propre base : le souvenir de la précédente est faux.
    monkeypatch.setattr(_persistence, "_migrated", set())
    # Le parc d'agents RÉEL : sans cette ligne, tout test atteignant `wake.tick()` balaie le
    # warm-pool des VRAIS agents et leur envoie `kill_agent`. Cf. production_isolation.py.
    isoler_le_parc_d_agents(tmp_path, monkeypatch)
    monkeypatch.setattr(worktrees, "WORKTREES_DIR", tmp_path / "worktrees")
    # PROJECTS_PATH aussi : sinon wake.tick/process_wakes itèrent les VRAIS projets (dont
    # « bouzecode ») et tentent d'écrire leur store réel. Liste vide → rien de réel à toucher.
    monkeypatch.setattr(projects, "PROJECTS_PATH", tmp_path / "projects.json")
