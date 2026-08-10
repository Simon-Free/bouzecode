# [desc] Un agent qui vient de naître apparaît dans l'arbre sans attendre la fin du TTL. [/desc]
"""L'écran attendait une information déjà écrite sur le disque.

`runner.create_agent` écrit le JSON de l'agent juste après le `Popen` — il EXISTE. Mais
`/api/agents/tree` sert une page mémorisée par `fleet_cache`, qui ne le contenait pas et n'était
recalculée qu'à l'expiration de son TTL. Mesuré le 2026-08-03 sur le parc réel : **7,9 s** entre
« l'agent est sur disque » et « l'arbre le montre ». C'était le poste DOMINANT du démarrage
ressenti — de l'attente pure, pas du travail.

La naissance d'un agent périme donc les pages déjà calculées. Périmer, pas vider : une entrée
périmée est toujours SERVIE (et recalculée en fond), ce que tout `fleet_cache` existe pour tenir.
"""
from __future__ import annotations

import sys
import time

import pytest

from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2.services.work import fleet_cache

CLE = (0, 12)


@pytest.fixture(autouse=True)
def cache_neuf():
    fleet_cache.clear()
    yield
    fleet_cache.clear()


def test_perimer_force_le_recalcul_au_prochain_acces():
    """Après une naissance, la page suivante est recalculée au lieu d'être resservie telle quelle."""
    calculs = []

    def _calcul():
        calculs.append(1)
        return f"parc-{len(calculs)}"

    assert fleet_cache.cached(CLE, _calcul) == "parc-1"
    # Sans péremption, le TTL (10 s) tient : aucun recalcul.
    assert fleet_cache.cached(CLE, _calcul) == "parc-1"
    assert len(calculs) == 1

    fleet_cache.expire_all()

    # Servi immédiatement (version connue) ET recalcul lancé en fond.
    assert fleet_cache.cached(CLE, _calcul) == "parc-1"
    limite = time.time() + 5
    while time.time() < limite and len(calculs) < 2:
        time.sleep(0.05)
    assert len(calculs) == 2, "la péremption n'a pas déclenché le recalcul de fond"

    # Le poll suivant récolte la version fraîche, sans avoir jamais attendu.
    assert fleet_cache.cached(CLE, _calcul) == "parc-2"


def test_perimer_ne_fait_attendre_personne():
    """Une entrée périmée reste SERVABLE : on ne vide pas, sinon le lecteur suivant attend."""
    def _lent():
        time.sleep(1.0)
        return "parc"

    assert fleet_cache.cached(CLE, _lent) == "parc"  # 1er appel : paie le calcul
    fleet_cache.expire_all()

    debut = time.perf_counter()
    valeur = fleet_cache.cached(CLE, _lent)
    duree = time.perf_counter() - debut

    assert valeur == "parc"
    assert duree < 0.3, f"la lecture a attendu le recalcul ({duree:.2f}s)"


def test_perimer_un_cache_vide_ne_casse_rien():
    fleet_cache.expire_all()
    assert fleet_cache.cached(CLE, lambda: "parc") == "parc"


def test_la_naissance_d_un_agent_perime_l_arbre_deja_calcule(monkeypatch):
    """Le câblage, pas seulement la primitive : `create_agent` périme les pages en cache.

    Le process spawné est remplacé par un `python -c pass` (même seam que la vraie commande de
    lancement) : on veut prouver l'invalidation, pas relancer un agent complet."""
    calculs = []
    fleet_cache.cached(CLE, lambda: calculs.append(1) or "arbre-sans-le-nouvel-agent")
    assert len(calculs) == 1

    monkeypatch.setattr(runner, "_bouzecode_launch_cmd", lambda: [sys.executable, "-c", "pass"])
    monkeypatch.setattr(runner, "check_provider_env", lambda *_, **__: None)
    agent = runner.create_agent("réponds PONG", "opus", str(runner.AGENTS_DIR))

    assert agent.agent_id
    # Périmé ⇒ le prochain lecteur relance le calcul, au lieu d'attendre la fin du TTL.
    fleet_cache.cached(CLE, lambda: calculs.append(1) or "arbre-avec-le-nouvel-agent")
    limite = time.time() + 5
    while time.time() < limite and len(calculs) < 2:
        time.sleep(0.05)
    assert len(calculs) == 2, "la naissance d'un agent n'a pas périmé l'arbre en cache"
