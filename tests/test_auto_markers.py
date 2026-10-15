# [desc] Verifie les deux axes de marqueurs derives : zone (dossier) et dependance (fixtures, corps) [/desc]
"""Ce que ces tests protegent : `addopts = "-m 'not web and not ui'"` n'a d'effet que si
quelqu'un pose `ui` et `web`. Personne ne le faisait — la garde etait decorative.

Meme risque pour l'axe dependance, en pire : une regle derivee est juste tant que ce qu'elle
lit existe encore. Les trois derniers tests sont des gardes anti-pourrissement — ils cassent
le jour ou la fixture ou la fonction sur laquelle la regle s'appuie est renommee ou deplacee,
au lieu de laisser un test live tourner sans marqueur.
"""
from pathlib import Path

from tests.auto_markers import (
    APPEL_GATEWAY_REEL, JETONS_CHRONOMETRE, JETONS_CONCURRENCE,
    marker_for, markers_for, markers_for_module, markers_for_source,
)


def test_dossier_backend():
    assert marker_for("tests/backend/tools/test_bash.py") == "backend"


def test_dossier_ui():
    assert marker_for("tests/ui/test_terminal.py") == "ui"


def test_dossier_frontend_porte_le_marqueur_web():
    """Le dossier s'appelle `frontend`, le marqueur declare s'appelle `web`."""
    assert marker_for("tests/frontend/test_flask.py") == "web"


def test_dossier_inconnu_non_marque():
    assert marker_for("tests/test_bash_timeout_hint.py") is None


def test_chemin_windows_reconnu():
    assert marker_for(r"C:\repo\bouzecode\tests\ui\test_terminal.py") == "ui"


# ── Axe dependance : network / llm / timing / slow ────────────────────────────















def test_un_test_ordinaire_ne_recoit_rien():
    """⛔ La grande majorite des tests ne doit porter AUCUN marqueur de dependance : sans ca,
    `-m "not slow"` ne trierait plus rien."""
    assert markers_for("tests/backend/tools/test_bash.py", ["tmp_path", "monkeypatch"]) == set()
    # Le pytest imbrique etanche du repertoire runner n'est plus `timing` (cf. markers_for).
    assert markers_for("tests/backend/tools/runner/test_x.py", ["_pytest_imbrique_etanche"]) == set()
    assert markers_for_source("def test_x():\n    assert 1 == 1\n") == set()




def test_le_corps_qui_ouvre_le_gateway_est_llm_et_network():
    # Le jeton est ASSEMBLE depuis la constante, jamais ecrit en toutes lettres : sinon la
    # regle marquerait son propre test comme un appel live (constate : 3 faux positifs).
    source = f"def test_live():\n    {APPEL_GATEWAY_REEL})\n    bouzecode(['salut'])\n"
    assert markers_for_source(source) == {"llm", "network", "slow"}


def test_slow_accompagne_toujours_les_autres_familles():
    """⛔ Sans ca, `-m "not slow"` laisserait passer des tests de plusieurs dizaines de secondes."""
    assert "slow" in markers_for_source(f"{APPEL_GATEWAY_REEL})")


def test_un_module_qui_pilote_des_threads_est_timing():
    """Le module, pas le corps : les helpers qui lancent les threads vivent en tete de fichier."""
    module = f"import threading\n\ndef _worker():\n    t = {JETONS_CONCURRENCE[0]}(target=f)\n"
    assert markers_for_module(module) == {"timing"}


def test_un_module_ordinaire_n_est_pas_timing():
    assert markers_for_module("def test_x():\n    assert True\n") == set()


def test_un_module_timing_n_est_pas_declare_lent():
    """⛔ Ces tests durent des fractions de seconde : leur coller `slow` sortirait 103 tests
    rapides d'un `-m "not slow"` — le mensonge symetrique de celui qu'on corrige."""
    assert "slow" not in markers_for_module(f"x = {JETONS_CONCURRENCE[1]}()")


def test_un_test_qui_se_chronometre_est_timing_et_lent():
    """Attendre une duree reelle pour l'affirmer, c'est la payer : 62 s mesurees."""
    corps = f"def test_x():\n    t0 = {JETONS_CHRONOMETRE[0]})\n    assert elapsed < 3\n"
    assert markers_for_source(corps) == {"timing", "slow"}




def test_chaque_jeton_designe_encore_du_code_reel():
    """⛔ Anti-pourrissement : un jeton que plus aucun test n'utilise est une regle morte qui
    donne l'illusion d'une famille couverte. Il doit etre retire ou corrige, pas conserve."""
    sources = _sources_des_tests()
    for jeton in JETONS_CONCURRENCE + JETONS_CHRONOMETRE:
        assert jeton in sources, f"aucun test n'utilise plus {jeton} : regle morte"


def test_la_porte_vers_le_gateway_existe_vraiment():
    """Meme garde-fou pour `require_api_key` : c'est le seul passage autorise par
    `_llm_network_guard`, et la regle se lit dessus."""
    sources = _sources_des_tests()
    assert f"def {APPEL_GATEWAY_REEL.rstrip('(')}(" in sources


def test_aucun_appel_au_gateway_n_echappe_a_la_regle():
    """⛔ Garde INVERSE : tout appel a la porte du gateway doit vivre dans un corps de test,
    sinon la regle — qui lit le corps du test — le manquerait. Un appel deplace dans une
    fixture ou un helper laisserait un test live tourner sans marqueur `network`.

    (Le jeton n'est jamais ecrit en toutes lettres dans ce fichier : il se marquerait lui-meme.)
    """
    racine = Path(__file__).resolve().parent
    for fichier in racine.rglob("test_*.py"):
        texte = fichier.read_text(encoding="utf-8")
        for ligne in texte.splitlines():
            if (APPEL_GATEWAY_REEL not in ligne or "def " in ligne or "import" in ligne
                    or ligne.strip().startswith("#")):
                continue
            fonction = _fonction_englobante(texte, ligne)
            assert fonction.startswith("test_"), (
                f"{fichier.name} : `{ligne.strip()}` est dans `{fonction}`, pas dans un test — "
                "la regle de marquage ne le verrait pas")


def _sources_des_tests() -> str:
    racine = Path(__file__).resolve().parent
    return "\n".join(p.read_text(encoding="utf-8") for p in racine.rglob("*.py"))


def _fonction_englobante(texte: str, ligne_cible: str) -> str:
    """Nom du dernier `def` rencontre au-dessus de `ligne_cible`."""
    nom = "<module>"
    for ligne in texte.splitlines():
        if ligne.lstrip().startswith("def "):
            nom = ligne.lstrip()[4:].split("(")[0]
        if ligne == ligne_cible:
            return nom
    return nom
