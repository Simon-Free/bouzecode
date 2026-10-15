"""Préchauffage des caches au démarrage (`web_v2/prechauffage.py`)."""
from bouzecode.web_v2 import prechauffage


def test_chaque_etape_jouee_et_une_erreur_n_arrete_pas_les_suivantes():
    jouees = []

    def casse():
        raise RuntimeError("disque absent")

    bilan = prechauffage.prechauffer((("a", lambda: jouees.append("a")), ("b", casse),
                                      ("c", lambda: jouees.append("c"))))
    assert jouees == ["a", "c"]
    assert isinstance(bilan["a"], float) and isinstance(bilan["c"], float)
    assert bilan["b"] == "RuntimeError: disque absent"


def test_desactivable(monkeypatch):
    monkeypatch.setenv("BOUZECODE_PRECHAUFFAGE", "0")
    assert prechauffage.lancer((("a", lambda: None),)) is None


def test_lance_en_fond(monkeypatch):
    monkeypatch.delenv("BOUZECODE_PRECHAUFFAGE", raising=False)
    jouees = []
    fil = prechauffage.lancer((("a", lambda: jouees.append("a")),))
    fil.join(10)
    assert fil.daemon and jouees == ["a"]


def test_vraies_etapes_sur_un_home_vide():
    """Les étapes réelles tournent sans erreur sur un poste sans agent (home de test étanche) :
    elles remplissent les caches que les routes relisent."""
    bilan = prechauffage.prechauffer()
    assert set(bilan) == {nom for nom, _ in prechauffage.ETAPES}
    assert all(isinstance(v, float) for v in bilan.values()), bilan
