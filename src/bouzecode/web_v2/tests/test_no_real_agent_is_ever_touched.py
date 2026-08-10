# [desc] Garde-fou : la suite ne doit JAMAIS énumérer ni tuer un agent du parc RÉEL. [/desc]
"""Un test ne doit jamais pouvoir tuer le travail d'un agent en vol.

`wake.tick()` → `wake._sweep_warm_pool` → `fleet.sweep_warm_pool` énumère les agents et
applique la politique d'éviction du warm-pool : `runner.kill_agent(agent)` →
`psutil.Process(agent.pid).terminate()`. Tant que `runner.AGENTS_DIR` pointait sur
`~/.bouzecode/web_agents`, ce balayage visait le parc RÉEL. Un run l'a fait des centaines
de fois sur le pid d'un agent d'une autre session ; seules les ACL Windows l'ont refusé.

Ces tests vérifient la garde POSÉE, pas l'intention : ils lisent le répertoire réellement
consulté et comptent ce qui y est vu.
"""
from __future__ import annotations

import json

from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2.services.work import fleet, wake
from bouzecode.web_v2.tests.production_isolation import (
    PARC_REEL, verifier_le_parc_est_isole,
)

def test_le_parc_consulte_n_est_jamais_le_parc_reel(tmp_path):
    """Répertoire jetable, corbeille de purge qui le suit (elle est FIGÉE à l'import, donc
    rediriger `AGENTS_DIR` seul la laisserait sur la corbeille RÉELLE), et aucun agent visible.
    Assertions partagées avec la garde de l'arbre `tests/` pour qu'elles ne divergent pas."""
    verifier_le_parc_est_isole(tmp_path)


def test_le_balayage_du_warm_pool_ne_tue_personne(monkeypatch):
    """`sweep_warm_pool` sur un parc isolé VIDE n'évince rien, et n'APPELLE même pas
    `kill_agent` — c'est la garantie qui compte.

    Le témoin ENREGISTRE au lieu de lever : `sweep_warm_pool` attrape désormais toute
    exception pour ne pas interrompre la boucle d'éviction (une seule éviction refusée
    la stoppait entièrement), et avalerait donc une sentinelle qui lève."""
    appels: list = []
    monkeypatch.setattr(runner, "kill_agent", lambda agent: appels.append(agent.agent_id))

    assert fleet.sweep_warm_pool() == []
    assert appels == [], "kill_agent a été appelé depuis un test"


def test_le_tick_du_watchdog_ne_tue_personne(monkeypatch):
    """Le chemin RÉEL par lequel le danger arrivait : `wake.tick()` balaie le warm-pool à
    chaque tour. Il ne doit atteindre aucun process, même quand des agents existent."""
    tues: list = []
    monkeypatch.setattr(runner, "kill_agent", lambda agent: tues.append(agent.agent_id))

    wake.tick()

    assert tues == []


def test_un_agent_du_parc_jetable_est_bien_vu(tmp_path):
    """Contre-preuve indispensable : l'isolation ne rend pas `list_agents` aveugle. Sans ce
    test, les trois assertions « rien vu » ci-dessus seraient vraies pour une mauvaise raison
    (un `list_agents` cassé les satisferait toutes)."""
    (runner.AGENTS_DIR / "cafe1234.json").write_text(json.dumps({
        "agent_id": "cafe1234", "prompt": "p", "model": "", "cwd": "", "pid": 0,
        "started_at": "2026-07-28T10:00:00", "returncode": 0,
        "session_path": "", "stdout_path": "",
    }), encoding="utf-8")
    runner._list_agents_cache.clear()

    assert [agent.agent_id for agent in runner.list_agents()] == ["cafe1234"]


def test_la_redirection_survit_a_un_acces_par_attribut():
    """Les appelants hors `runner` (purge, wake, liveness, integration, search) lisent
    `runner.AGENTS_DIR` à l'APPEL, pas à l'import : la redirection les couvre tous."""
    from bouzecode.web_v2.services.work import liveness

    # `liveness._session_path` reconstruit un chemin depuis `runner.AGENTS_DIR` pour un agent
    # déchargé : c'est un lecteur par attribut représentatif de tous les autres.
    chemin = liveness._session_path("inconnu", agent=None)

    assert PARC_REEL not in chemin.parents, chemin
