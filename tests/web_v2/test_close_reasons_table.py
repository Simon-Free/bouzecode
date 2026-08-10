# [desc] Une seule table close_reason : toute raison produite par la boucle y est classée. [/desc]
"""Trois ensembles répondaient chacun à leur question sans se connaître.

`runner` décidait du code retour, `wake` de l'avancement du ticket, `liveness` de la
vivacité — et ils divergeaient. `ends_turn_tool` était « propre » pour l'un et « planté »
pour l'autre. Pire : `final_answer_over_failed_tool`, introduit le 2026-07-29, ne figurait
dans AUCUN des trois — un agent ayant clos délibérément était rapporté PLANTÉ, son ticket
gelé, et la suite restait verte.

La règle tenue ici : toute raison de clôture ASSIGNÉE par la boucle doit être classée dans
`close_reasons.CLOSURES`. C'est la seule règle qui aurait attrapé ce trou.
"""
import ast
from pathlib import Path

import pytest

from bouzecode.backend.agent import loop as loop_mod
from bouzecode.web_v2 import close_reasons
from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2.services.work import liveness, wake

AGENT_DIR = Path(loop_mod.__file__).parent


def _literaux_de_cloture(path: Path) -> set[str]:
    """Les close_reasons ASSIGNÉS littéralement dans un module de la boucle.

    Couvre `state.close_reason = "x"` comme `state.close_reason = state.close_reason or "x"`
    — la seconde forme est celle qui avait fait taire le garde précédent, écrit en grep brut.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    trouves: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        cibles = [t for t in node.targets
                  if isinstance(t, ast.Attribute) and t.attr == "close_reason"]
        if not cibles:
            continue
        trouves.update(sous.value for sous in ast.walk(node.value)
                       if isinstance(sous, ast.Constant) and isinstance(sous.value, str))
    return trouves


def _raisons_produites() -> set[str]:
    raisons: set[str] = set()
    for module in sorted(AGENT_DIR.glob("*.py")):
        raisons |= _literaux_de_cloture(module)
    return raisons


def test_toute_raison_assignee_par_la_boucle_est_classee():
    """GARDE ANTI-TROU : une raison produite mais absente de la table serait traitée comme
    une mort en vol — ticket gelé, agent rapporté planté, sans qu'aucun test ne bronche."""
    produites = _raisons_produites()
    assert produites, "aucun `state.close_reason = ...` trouvé — le parse a-t-il changé ?"
    manquantes = sorted(produites - set(close_reasons.CLOSURES))
    assert not manquantes, (
        f"raisons produites par la boucle et absentes de close_reasons.CLOSURES : "
        f"{manquantes}. Non classées, elles sont traitées comme un crash."
    )


def test_la_table_ne_classe_pas_de_raisons_fantomes():
    """Symétrique : une entrée que plus personne ne produit doit partir — ou être DÉCLARÉE
    comme survivance historique. Sinon la table documente peu à peu une boucle qui n'existe
    plus, et c'est exactement ainsi qu'on absout des morts qu'on n'a jamais vus."""
    produites = _raisons_produites()
    # Les morts en vol ne sont pas assignées par la boucle : elles viennent du runner/IPC.
    hors_boucle = close_reasons.CRASH_CLOSE_REASONS | close_reasons.LEGACY_CLOSE_REASONS
    fantomes = sorted(set(close_reasons.CLOSURES) - produites - hors_boucle)
    assert not fantomes, (
        f"entrées de table que la boucle ne produit plus : {fantomes}. Retire-les, ou "
        f"déclare-les dans close_reasons.LEGACY_CLOSE_REASONS si des sessions disque les portent."
    )


def test_les_survivances_historiques_ne_sont_plus_produites():
    """L'inverse : une raison déclarée « historique » que la boucle produit encore est une
    déclaration périmée — la liste doit rester une liste de morts, pas un dépotoir."""
    encore_vivantes = sorted(close_reasons.LEGACY_CLOSE_REASONS & _raisons_produites())
    assert not encore_vivantes, (
        f"déclarées historiques mais toujours produites par la boucle : {encore_vivantes}"
    )


def test_close_over_failed_tool_livre_et_avance():
    """Le cœur du correctif. Avant le 2026-07-29 cette clôture était écrasée en
    `final_answer` par `_fire_completion` : elle prouvait une livraison et faisait avancer le
    ticket. La dégrader en crash serait une régression — c'est au validateur de juger une
    livraison dont un outil a manqué, pas au classifieur de geler le ticket."""
    assert close_reasons.proves_delivery("final_answer_over_failed_tool")
    assert close_reasons.advances_ticket("final_answer_over_failed_tool")
    assert close_reasons.is_controlled("final_answer_over_failed_tool")


def test_une_raison_inconnue_ne_prouve_rien():
    """Repli pessimiste : une clôture qu'on ne sait pas nommer ne valide ni rc 0 ni
    avancement de ticket."""
    assert not close_reasons.proves_delivery("raison_jamais_vue")
    assert not close_reasons.advances_ticket("raison_jamais_vue")
    assert not close_reasons.is_controlled("")


@pytest.mark.parametrize("raison", ["api_error", "cancelled", "assistant_none", "partial_stream"])
def test_les_morts_en_vol_restent_des_crashs(raison):
    assert close_reasons.is_crash(raison)
    assert not close_reasons.is_controlled(raison)


def test_les_trois_surfaces_lisent_la_meme_table():
    """Aucune des trois ne garde son propre ensemble : c'est la divergence qui a créé le bug."""
    assert wake.GRACEFUL_CLOSE_REASONS is close_reasons.ADVANCING_CLOSE_REASONS
    assert liveness.CLEAN_CLOSE_REASONS is close_reasons.CONTROLLED_CLOSE_REASONS
    assert liveness.CRASH_CLOSE_REASONS is close_reasons.CRASH_CLOSE_REASONS
    assert runner._DELIVERY_CLOSE_REASONS is close_reasons.DELIVERY_CLOSE_REASONS


def test_aucune_classification_existante_n_a_bouge():
    """Le correctif REMPLIT deux trous, il ne redéfinit rien. Les raisons antérieures gardent
    exactement le classement qu'elles avaient dans les trois modules d'origine."""
    assert close_reasons.DELIVERY_CLOSE_REASONS >= {"final_answer", "final_answer_deferred"}
    assert not close_reasons.proves_delivery("text_no_tools"), \
        "text_no_tools ne prouve PAS une livraison (rc≠0) — un validateur clos sur prose " \
        "ne doit pas basculer de KO à OK"
    assert close_reasons.advances_ticket("text_no_tools"), \
        "text_no_tools fait avancer le ticket (le verdict d'un validateur est dans sa prose)"
    for forcee in ("final_answer_nudge_exhausted", "final_answer_never_called",
                   "meta_only_cap", "meta_only_text_close"):
        assert close_reasons.is_controlled(forcee), forcee
        assert not close_reasons.advances_ticket(forcee), forcee
