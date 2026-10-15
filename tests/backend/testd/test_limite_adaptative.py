# [desc] testd : limite par test adaptative — max(10 s, 5 × la durée habituelle du test), plafonnée par sa catégorie ; un test inconnu garde 30 s / 60 s ; tests.yaml la fixe ; un test d'1 s bloqué est tué vers 15 s, pas à 35 s [/desc]
from __future__ import annotations

import os
import time

from bouzecode.backend.testd.budget.durations import fichier_durees, fusionner
from bouzecode.backend.testd.budget.recentes import ajouter, fichier_recentes, medianes
from bouzecode.backend.testd.garde.limites import limites_de
from bouzecode.backend.testd.rendu import attendre, texte_etat
from tests.backend.testd.aides import commande, projet

_ID = "tests/test_a.py::test_x"


def _motif(config: dict, habituelles: dict, navigateur: bool = False) -> tuple[int, str]:
    return limites_de(config, habituelles).motivee(_ID, navigateur, False, cwd="C:/projet")


def test_un_test_mesure_recoit_cinq_fois_sa_duree_habituelle_au_moins_10_s():
    """1,8 s habituel → 10 s (plancher) ; 4 s → 20 s ; 9 s → plafonné à 30 s hors navigateur
    mais 45 s s'il est navigateur ; le motif est écrit pour le rapport."""
    assert _motif({}, {_ID: 1.8}) == (10, "limite 10 s = 5 × 1,8 s habituel, plancher 10 s")
    assert _motif({}, {_ID: 4.0}) == (20, "limite 20 s = 5 × 4 s habituel")
    assert _motif({}, {_ID: 9.0})[0] == 30
    assert _motif({}, {_ID: 9.0}, navigateur=True)[0] == 45


def test_un_test_inconnu_garde_la_limite_de_sa_categorie():
    """Jamais mesuré : 30 s hors navigateur, 60 s navigateur, le temps d'être appris."""
    assert _motif({}, {}) == (30, "limite 30 s, défaut des tests hors navigateur (jamais mesuré)")
    assert _motif({}, {}, navigateur=True)[0] == 60


def test_une_limite_ecrite_dans_tests_yaml_coupe_l_adaptation():
    """`timeouts.per_test` (ou `per_test_browser`) est pris tel quel, même pour un test mesuré."""
    assert _motif({"timeouts": {"per_test": 45}}, {_ID: 0.1})[0] == 45
    assert _motif({"timeouts": {"per_test_browser": 90}}, {_ID: 0.1}, navigateur=True)[0] == 90


def test_la_duree_habituelle_est_la_mediane_des_dernieres_mesures(tmp_path):
    """Une mesure aberrante (machine chargée) ne déplace pas la durée habituelle ; seules les
    5 dernières mesures comptent."""
    historique = tmp_path / "depot.json"
    for duree in (1.0, 1.2, 30.0, 0.9, 1.1, 1.0):
        ajouter(historique, {_ID: duree})
    assert medianes(historique) == {_ID: 1.1}
    assert fichier_recentes(historique).exists()


_BLOQUE = {
    "test_bloque.py": """
        import threading
        def test_habituellement_une_seconde():
            verrou = threading.Lock()
            verrou.acquire()
            verrou.acquire()
    """,
}


def test_un_test_d_une_seconde_bloque_est_tue_vers_15_s(demon, tmp_path):
    """Un test qui prend d'habitude 1 s et reste bloqué est tué à sa limite adaptative (10 s +
    5 s de marge), pas à la limite fixe de 30 s ; le rapport dit pourquoi 10 s."""
    racine = projet(tmp_path / "p", _BLOQUE)
    nodeid = "test_bloque.py::test_habituellement_une_seconde"
    historique = fichier_durees(str(racine))
    fusionner(historique, {nodeid: 1.0})
    ajouter(historique, {nodeid: 1.0})
    debut = time.monotonic()
    job = demon.soumettre(commande("test_bloque.py"), dict(os.environ), str(racine), 300, "")
    final = attendre(job["job_id"], 120, au_premier_echec=False)
    duree = time.monotonic() - debut
    rapport = texte_etat(final)
    assert duree < 28, (duree, rapport)
    assert f"{nodeid} bloqué depuis" in rapport, rapport
    assert "limite 10 s = 5 × 1 s habituel" in rapport, rapport
    assert "Pile du test (faulthandler)" in rapport, rapport
