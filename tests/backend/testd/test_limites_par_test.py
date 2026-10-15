# [desc] testd : limites par test lues dans tests.yaml — 30 s, 60 s navigateur, 300 s au moins pour un test lent ; `per_test` remplace les deux, `per_test_browser` la navigateur, 0 coupe [/desc]
from __future__ import annotations

from bouzecode.backend.testd.garde.limites import limites_de


def _limite(config: dict, nodeid: str = "tests/test_a.py::test_x", navigateur: bool = False,
            marque_lent: bool = False) -> int:
    return limites_de(config).pour(nodeid, navigateur, marque_lent, cwd="C:/projet")


def test_sans_reglage_30_s_hors_navigateur_et_60_s_navigateur():
    """Sans `timeouts` dans tests.yaml : 30 s pour un test ordinaire, 60 s pour un test navigateur."""
    assert _limite({}) == 30
    assert _limite({}, navigateur=True) == 60


def test_per_test_remplace_les_deux_et_per_test_browser_la_navigateur():
    """`per_test` vaut pour tous les tests ; `per_test_browser` le remplace pour les tests navigateur."""
    assert _limite({"timeouts": {"per_test": 10}}) == 10
    assert _limite({"timeouts": {"per_test": 10}}, navigateur=True) == 10
    assert _limite({"timeouts": {"per_test": 10, "per_test_browser": 90}}, navigateur=True) == 90


def test_un_test_lent_garde_au_moins_300_s():
    """Un test listé sous `impacted.slow` (fichier ou dossier) ou marqué `slow` a au moins 300 s."""
    config = {"impacted": {"slow": ["tests/test_a.py", "tests/lourds"]}, "_racine": "C:/projet"}
    assert _limite(config) == 300
    assert _limite(config, nodeid="tests/lourds/test_b.py::test_y") == 300
    assert _limite(config, nodeid="tests/test_c.py::test_z") == 30
    assert _limite({}, marque_lent=True) == 300
    assert _limite({"timeouts": {"per_test": 600}}, marque_lent=True) == 600


def test_zero_coupe_la_limite_meme_pour_un_test_lent():
    """`per_test: 0` : aucun test n'est tué, lent ou non."""
    assert _limite({"timeouts": {"per_test": 0}}) == 0
    assert _limite({"timeouts": {"per_test": 0}}, navigateur=True) == 0
    assert _limite({"timeouts": {"per_test": 0}}, marque_lent=True) == 0
    assert limites_de({"timeouts": {"per_test": 0}}).vidage(navigateur=False) == 0
