# [desc] Test TDD du tool Chantiers : l'assistant du Bureau crée, liste et rattache un dépôt à un chantier [/desc]
"""Le geste utilisateur teste ici : depuis /bureau, je dis « cree un chantier … » a
l'assistant. Il n'a ni Bash ni Write : sans un outil dedie, il ne peut RIEN faire de cette
demande (create_macro n'etait atteignable que par POST /api/macros, c'est-a-dire par l'UI).

On appelle donc l'outil exactement comme le runtime l'appelle (handler, puis func du
registry), et on relit la base : pas de mock, pas de HTTP, pas de LLM.
"""
from __future__ import annotations

from bouzecode.backend.core.tool_registry import get_tool
from bouzecode.backend.tools import bureau_tools
from bouzecode.web_v2.services.work import micros as service


def test_l_assistant_cree_un_chantier_et_le_retrouve_en_base():
    reponse = bureau_tools.chantiers(
        action="creer",
        titre="Rendre le Bureau pilotable a la voix",
        corps="Tout ce qui se fait a la souris doit se dire a l'assistant.",
        projets=["bouzecode"],
    )

    assert reponse["ok"] is True, reponse
    chantier = reponse["chantier"]
    assert chantier["titre"] == "Rendre le Bureau pilotable a la voix"
    assert chantier["projets"] == ["bouzecode"]

    #  Persiste vraiment : on relit par le service, pas par la valeur de retour.
    relu = service.get_macro(chantier["id"])
    assert relu is not None, "le chantier n'a pas ete ecrit en base"
    assert relu["etat"] == "active"


def test_l_assistant_liste_les_chantiers_qu_il_vient_de_creer():
    cree = bureau_tools.chantiers(action="creer", titre="Chantier a lister")

    listing = bureau_tools.chantiers(action="lister")

    assert listing["ok"] is True
    ids = [c["id"] for c in listing["chantiers"]]
    assert cree["chantier"]["id"] in ids, f"chantier absent du listing : {ids}"


def test_un_chantier_sans_titre_est_refuse_sans_exception_nue():
    """create_macro leve BriefInsuffisant ; un outil doit rendre un dict JSON-able,
    sinon l'assistant recoit une trace au lieu d'une phrase a dire a l'utilisateur."""
    reponse = bureau_tools.chantiers(action="creer", titre="   ")

    assert reponse["ok"] is False
    assert reponse["erreur"] == "titre_vide"
    assert reponse["message"], "il faut dire a l'assistant CE QUI manque"


def test_l_assistant_rattache_un_depot_a_un_chantier_en_cours():
    chantier = bureau_tools.chantiers(action="creer", titre="Chantier multi-depots")["chantier"]

    reponse = bureau_tools.chantiers(action="ajouter_projet",
                                     macro_id=chantier["id"], projet_slug="demo")

    assert reponse["ok"] is True, reponse
    assert reponse["chantier"]["projets"] == ["demo"]


def test_rattacher_un_depot_a_un_chantier_inconnu_ne_casse_pas():
    reponse = bureau_tools.chantiers(action="ajouter_projet",
                                     macro_id="inexistant", projet_slug="demo")

    assert reponse["ok"] is False
    assert reponse["erreur"] == "not_found"


def test_une_action_inconnue_rappelle_les_actions_possibles():
    reponse = bureau_tools.chantiers(action="supprimer")

    assert reponse["ok"] is False
    assert reponse["erreur"] == "action_inconnue"
    assert set(reponse["attendu"]) == {"lister", "creer", "ajouter_projet"}


def test_le_runtime_peut_appeler_chantiers_par_le_registry():
    """Le chemin REEL : le runtime ne connait que ToolDef.func(params, config)."""
    bureau_tools.register()
    definition = get_tool("Chantiers")

    assert definition is not None, "Chantiers n'est pas enregistre dans le registry"
    assert definition.read_only is False, "creer un chantier ECRIT : ce n'est pas read_only"

    resultat = definition.func({"action": "creer", "titre": "Chantier via registry"}, {})

    assert resultat["ok"] is True, resultat
    assert service.get_macro(resultat["chantier"]["id"]) is not None
