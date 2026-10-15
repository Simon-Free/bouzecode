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

from bouzecode.web_v2.services.sessions import listing_cache, meta_index, store  # noqa: E402
from bouzecode.web_v2.services.work import (  # noqa: E402
    _persistence, projects, tickets, worktrees,
)
from bouzecode.web_v2.tests.production_isolation import (  # noqa: E402
    isoler_l_identite_d_agent, isoler_le_parc_d_agents, isoler_les_fichiers_du_home,
)


@pytest.fixture(autouse=True)
def _environnement_restaure(monkeypatch):
    """`os.environ` est global au worker : un outil qui l'écrit lui-même (Environment adopte un
    worktree, `armer_identite` pose `tui:<id>`) le laissait au test suivant, d'où des tests qui
    dépendaient de l'ordre. Même garde que `tests/conftest.py::_isolate_global_state`."""
    from bouzecode.backend.core import tool_registry
    isoler_l_identite_d_agent(monkeypatch)
    avant = dict(os.environ)
    #  Même chose pour les outils coupés : `/agent`, `/assistant` les rallumaient pour la suite.
    desactives = set(tool_registry._disabled)
    yield
    if dict(os.environ) != avant:
        os.environ.clear()
        os.environ.update(avant)
    tool_registry._disabled.clear()
    tool_registry._disabled.update(desactives)


@pytest.fixture(autouse=True)
def _forget_session_caches():
    """Vide les caches process du listing de sessions (memo de méta + cache TTL) et le statut
    mémorisé des agents autour de CHAQUE test : sinon un test verrait la méta, le listing ou le
    statut mémorisés par le précédent.

    `store._status_cache` est indexé par `agent_id` : en production un id ne sert qu'une fois,
    mais les tests réemploient des ids courts (« recent »…). Sous xdist, quand
    test_auto_resume_supersession passait avant test_conversations_auto_archive_stale sur le
    même worker, « recent » y était déjà mémorisé `finished` et sa question orpheline
    disparaissait de la liste."""
    meta_index.reset_memo()
    listing_cache.reset()
    store._status_cache.clear()
    yield
    meta_index.reset_memo()
    listing_cache.reset()
    store._status_cache.clear()
    #  Chaque écriture de ticket périme l'arbre mémorisé : son recalcul de fond ne doit pas
    #  déborder sur le test suivant du même worker.
    from bouzecode.web_v2.services.work import fleet_cache
    fleet_cache.attendre_puis_vider()


@pytest.fixture(autouse=True)
def _isolate_production_state(tmp_path, monkeypatch):
    # Sorties d'outils tronquées et installation auto de ripgrep : rien dans le vrai HOME
    # (les sous-process d'agents lancés par ces tests héritent de l'environnement).
    monkeypatch.setenv("BOUZECODE_TOOL_OUTPUT_DIR", str(tmp_path / "tool_outputs"))
    #  Le cache disque de l'activite MS est ACTIF par defaut : sans cette redirection, un
    #  test qui lit mails/chats ecrirait des tranches dans le vrai ~/.bouzecode/cache.
    monkeypatch.setenv(
        "BOUZECODE_MS_ACTIVITE_CACHE_DIR", str(tmp_path / "cache" / "ms_activite")
    )
    monkeypatch.setenv("BOUZECODE_RIPGREP_AUTO", "0")
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
    isoler_les_fichiers_du_home(tmp_path, monkeypatch)
    monkeypatch.setattr(worktrees, "WORKTREES_DIR", tmp_path / "worktrees")
    # bureau.md est le fichier PERSONNEL de l'utilisateur : un test qui écrirait dans le vrai
    # ~/.bouzecode/bureau y ajouterait des ancres et un bloc machine dans SES notes. Chaque test
    # a donc son propre dossier bureau, comme il a déjà sa propre base de tickets.
    from bouzecode.web_v2.services.work import bureau_file as _bureau_file
    monkeypatch.setattr(_bureau_file, "BUREAU_DIR", tmp_path / "bureau")
    # PROJECTS_PATH aussi : sinon wake.tick/process_wakes itèrent les VRAIS projets (dont
    # « bouzecode ») et tentent d'écrire leur store réel. Liste vide → rien de réel à toucher.
    monkeypatch.setattr(projects, "PROJECTS_PATH", tmp_path / "projects.json")


@pytest.fixture(autouse=True)
def _vue_du_bureau_sans_memoire(monkeypatch):
    """La vue du Bureau se mémorise 3 s en production (`taches_vue.CACHE_TTL`). Un test écrit
    l'état d'un agent sur disque puis relit aussitôt : il doit voir la photo de MAINTENANT."""
    from bouzecode.web_v2.services.work import taches_vue
    monkeypatch.setattr(taches_vue, "CACHE_TTL", 0)
    taches_vue.invalider()
    yield
    taches_vue.invalider()


@pytest.fixture(autouse=True)
def _api_joignable_par_defaut(monkeypatch):
    """Sous test, l'env API (ANTHROPIC_BASE_URL/clé) est absent : le verdict de boot est KO et
    toute route de spawn répondrait 503. Les tests qui éprouvent ce refus posent eux-mêmes
    `BOOT_API_OK = False` (ils tournent APRÈS cette fixture et l'emportent)."""
    from bouzecode.web_v2 import api_sanity
    monkeypatch.setattr(api_sanity, "BOOT_API_OK", True)


@pytest.fixture(autouse=True)
def _client_de_test_avec_jeton(monkeypatch):
    """Les mutations /api/ exigent le jeton local (web_v2/securite.py) : le client de test le
    joint comme le front, sans désactiver la garde (cf. web_v2/tests/client_jeton.py)."""
    from bouzecode.web_v2.tests.client_jeton import armer
    armer(monkeypatch)
