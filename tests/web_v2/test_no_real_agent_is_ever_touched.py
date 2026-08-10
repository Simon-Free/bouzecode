# [desc] Garde-fou côté `tests/` : cet arbre non plus ne doit toucher le parc d'agents RÉEL. [/desc]
"""Même garantie que `src/bouzecode/web_v2/tests/test_no_real_agent_is_ever_touched.py`, pour
l'AUTRE arbre : `tests/` a sa propre fixture autouse, donc sa propre isolation à prouver.
Les deux arbres atteignent `wake.tick()` → `fleet.sweep_warm_pool` → `runner.kill_agent`.

Les assertions vivent dans `production_isolation` pour que les deux gardes ne divergent pas.
"""
from __future__ import annotations

from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2.services.work import wake
from bouzecode.web_v2.tests.production_isolation import verifier_le_parc_est_isole


def test_le_parc_est_isole_dans_cet_arbre_aussi(tmp_path):
    verifier_le_parc_est_isole(tmp_path)


def test_le_tick_du_watchdog_ne_tue_personne(monkeypatch):
    """Le chemin par lequel le danger arrivait. Le sentinelle enregistre au lieu de tuer :
    la liste doit rester vide."""
    tues: list = []
    monkeypatch.setattr(runner, "kill_agent", lambda agent: tues.append(agent.agent_id))

    wake.tick()

    assert tues == []
