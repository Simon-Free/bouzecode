# [desc] Tests du garde anti-rejeu : un appel de lecture identique n'est pas rejoué, une écriture invalide la mémoire. [/desc]
"""Rejouer le même appel ne donne pas un autre résultat.

Scénario d'origine : trois `WebFetch` sur la même URL, deux dans le même tour,
trois pages de login identiques, puis l'abandon. L'agent n'avait aucun signal
lui disant qu'il tournait en rond.
"""
import pytest

from bouzecode.backend.core import repeat_guard
from bouzecode.backend.core.tool_registry import ToolDef, execute_tool, register_tool


@pytest.fixture()
def outils():
    """Un outil de lecture et un outil d'écriture, tous deux comptant leurs appels."""
    appels = {"lecture": 0, "ecriture": 0}

    def lire(params, config):
        appels["lecture"] += 1
        return f"page de login (appel {appels['lecture']})"

    def ecrire(params, config):
        appels["ecriture"] += 1
        return "ecrit"

    schema = {"type": "object", "properties": {"url": {"type": "string"}}, "required": []}
    register_tool(ToolDef(name="_TestLecture",
                          schema={"name": "_TestLecture", "description": "", "input_schema": schema},
                          func=lire, read_only=True))
    register_tool(ToolDef(name="_TestEcriture",
                          schema={"name": "_TestEcriture", "description": "", "input_schema": schema},
                          func=ecrire, read_only=False))
    return appels


def test_un_appel_de_lecture_identique_n_est_pas_rejoue(outils):
    config = {}

    premier = execute_tool("_TestLecture", {"url": "https://x/conv.json"}, config)
    second = execute_tool("_TestLecture", {"url": "https://x/conv.json"}, config)

    assert outils["lecture"] == 1, "l'appel a été rejoué alors que rien n'a changé"
    assert "DÉJÀ JOUÉ" in second
    assert "change d'approche" in second
    assert premier in second


def test_des_parametres_differents_sont_bien_rejoues(outils):
    config = {}

    execute_tool("_TestLecture", {"url": "https://x/a.json"}, config)
    execute_tool("_TestLecture", {"url": "https://x/b.json"}, config)

    assert outils["lecture"] == 2


def test_une_ecriture_entre_les_deux_relance_la_lecture(outils):
    """Relire un fichier qu'on vient d'éditer doit fonctionner."""
    config = {}

    execute_tool("_TestLecture", {"url": "https://x/a.json"}, config)
    execute_tool("_TestEcriture", {"url": "https://x/a.json"}, config)
    resultat = execute_tool("_TestLecture", {"url": "https://x/a.json"}, config)

    assert outils["lecture"] == 2
    assert "DÉJÀ JOUÉ" not in resultat


def test_un_outil_d_ecriture_est_toujours_rejoue(outils):
    config = {}

    execute_tool("_TestEcriture", {"url": "https://x/a.json"}, config)
    execute_tool("_TestEcriture", {"url": "https://x/a.json"}, config)

    assert outils["ecriture"] == 2


def test_deux_sessions_ne_partagent_pas_leur_memoire(outils):
    """Focus fait tourner plusieurs conversations en threads : un résultat ne doit
    jamais franchir la frontière d'un run."""
    config_a, config_b = {}, {}

    execute_tool("_TestLecture", {"url": "https://x/a.json"}, config_a)
    resultat_b = execute_tool("_TestLecture", {"url": "https://x/a.json"}, config_b)

    assert outils["lecture"] == 2
    assert "DÉJÀ JOUÉ" not in resultat_b


def test_l_ordre_des_parametres_ne_change_pas_l_empreinte():
    config = {}
    repeat_guard.remember(config, "T", {"a": 1, "b": 2}, "memo")

    assert repeat_guard.recall(config, "T", {"b": 2, "a": 1}) is not None
