# [desc] Isolation du parc d'agents RÉEL : AGENTS_DIR + les constantes figées qui en dérivent. [/desc]
"""Empêche la suite de TUER de vrais agents.

`wake.tick()` → `wake._sweep_warm_pool` → `fleet.sweep_warm_pool` énumère
`runner.list_agents()` et applique la politique d'éviction du warm-pool :
`runner.kill_agent(agent)` → `psutil.Process(agent.pid).terminate()`. Or `AGENTS_DIR`
pointait sur `~/.bouzecode/web_agents` — le parc RÉEL — dans TOUS les tests qui n'en
posaient pas un à eux. Observé pendant un run : des centaines de `terminate()` sur le
pid d'un agent en vol, refusés uniquement par les ACL Windows.

Partagé par les deux arbres de conftest (`src/bouzecode/web_v2/tests/` et `tests/`) :
la subtilité ci-dessous ne doit pas diverger entre deux copies.

SITE DE RÉSOLUTION — la leçon de la journée appliquée à cette garde elle-même :
`runner.py` lit `AGENTS_DIR` comme global de SON module, et purge/wake/liveness/
integration/search y accèdent par `runner.AGENTS_DIR` à l'appel. Patcher l'attribut du
module `runner` couvre donc tout le monde… SAUF `purge.TRASH_DIR`, calculé À L'IMPORT
(`TRASH_DIR = runner.AGENTS_DIR / "_trash"`). Repointer `runner.AGENTS_DIR` sans lui
laisserait la purge déplacer des artefacts dans le `_trash` RÉEL : une garde à moitié
posée, exactement le motif qu'on chasse. Les deux sont donc redirigés.
"""
from __future__ import annotations

from pathlib import Path


def isoler_le_parc_d_agents(tmp_path: Path, monkeypatch) -> Path:
    """Redirige le parc d'agents (et sa corbeille) vers un frère de `tmp_path`. Renvoie le répertoire.

    Les tests qui posent leur propre `AGENTS_DIR` l'emportent : ils tournent APRÈS
    l'autouse et réécrivent la même cible."""
    from bouzecode.web_v2.runtime import runner
    from bouzecode.web_v2.services.sessions import purge

    # HORS de `tmp_path`, en FRÈRE : unique par test (le nom de `tmp_path` l'est), jeté avec le
    # dossier temporaire, et surtout INVISIBLE depuis `tmp_path`. Les deux contraintes qui ont
    # fixé cet emplacement, chacune mesurée sur un échec réel :
    #   * une douzaine de tests font `(tmp_path / "web_agents").mkdir()` SANS `exist_ok` pour
    #     poser leur propre parc → même nom = FileExistsError en cascade (66 erreurs) ;
    #   * `test_write_partial_noop_without_session_path` exige que `tmp_path` reste VIDE → tout
    #     répertoire créé d'office DEDANS le fait tomber.
    # Il est bien créé : des tests écrivent un agent sans poser de parc à eux (ils écrivaient
    # donc, jusqu'ici, dans le parc RÉEL) et `runner` ne crée pas le dossier à l'écriture.
    agents_dir = tmp_path.parent / f"{tmp_path.name}__parc_agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(runner, "AGENTS_DIR", agents_dir)
    # `_list_agents_cache` est un cache TTL de PROCESS, sans clé sur le répertoire : un
    # `list_agents()` joué pendant que `AGENTS_DIR` valait encore le parc RÉEL rend le parc
    # RÉEL pendant toute la TTL, y compris aux tests isolés qui suivent. Rediriger le
    # répertoire sans vider ce cache serait une garde à moitié posée (observé : la garde de
    # l'arbre `tests/` voyait de vrais agents dès qu'elle tournait après ceux de `src/`).
    runner._list_agents_cache.clear()
    monkeypatch.setattr(runner, "_agent_file_cache", {})
    monkeypatch.setattr(purge, "TRASH_DIR", agents_dir / "_trash")
    monkeypatch.setattr(purge, "DELETED_PATH", tmp_path / "deleted_sessions.json")
    return agents_dir


def autoriser_la_destruction(monkeypatch) -> None:
    """Lève EXPLICITEMENT le garde-fou `runner.destruction_permitted` pour UN test.

    Le garde rend toute terminaison inerte sous pytest (cf. sa docstring). Un test qui
    veut prouver le comportement RÉEL d'un chemin de kill doit donc le lever — et le
    faire visiblement, par cet appel nommé, pour qu'un lecteur voie immédiatement qu'il
    est dans le seul cas où du code destructeur s'exécute. Il reste tenu par les autres
    garanties : parc isolé, et process cibles fabriqués par le test lui-même."""
    from bouzecode.web_v2.runtime import runner

    monkeypatch.setattr(runner, "destruction_permitted", lambda: True)


PARC_REEL = Path.home() / ".bouzecode" / "web_agents"


def verifier_le_parc_est_isole(tmp_path: Path) -> None:
    """Assertions partagées par les gardes des DEUX arbres de tests : le répertoire réellement
    consulté est le jetable, sa corbeille suit, et aucun agent réel n'est visible."""
    from bouzecode.web_v2.runtime import runner
    from bouzecode.web_v2.services.sessions import purge

    assert runner.AGENTS_DIR != PARC_REEL, "les tests lisent le parc d'agents RÉEL"
    assert runner.AGENTS_DIR.parent == tmp_path.parent, runner.AGENTS_DIR
    assert runner.AGENTS_DIR.name.startswith(tmp_path.name), runner.AGENTS_DIR
    # `purge.TRASH_DIR` est figé À L'IMPORT depuis `runner.AGENTS_DIR` : rediriger AGENTS_DIR
    # seul le laisserait sur la corbeille RÉELLE.
    assert purge.TRASH_DIR.parent == runner.AGENTS_DIR, purge.TRASH_DIR
    assert runner.list_agents() == [], "un agent RÉEL est visible depuis un test"
