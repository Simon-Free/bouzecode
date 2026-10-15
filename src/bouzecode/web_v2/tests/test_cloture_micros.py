"""Le pont de clôture : ce qu'un agent DÉCLARE en partant devient une micro-tâche.

Mesuré avant d'écrire ce pont : le champ `taches_restantes` de `FinalAnswer` est rempli à
presque chaque clôture (57 des 60 sessions récentes le portent, le `close_validator` refuse
une clôture qui laisse un point en suspens non déclaré), mais AUCUN code ne le convertissait
en quoi que ce soit de persistant : il était seulement AFFICHÉ sur la page TO-DO, et il
fallait un geste humain (`POST /api/todo/capture`) pour en faire une micro-tâche. En base :
zéro micro-tâche issue réellement d'une clôture d'agent, et des micros `humain` du 08/09 dont
le corps est du texte RECOPIÉ À LA MAIN depuis une clôture d'agent.

Règle arbitrée par l'utilisateur le 2026-09-08 : « si le ticket provient d'une tâche macro, on
y rattache par défaut les nouveaux tickets ». La macro n'est donc ni proposée par l'agent ni
validée par un humain : elle est HÉRITÉE du ticket parent.

Tout passe par le vrai service et la vraie base SQLite (isolée par la fixture autouse
`_isolate_production_state` du conftest). Aucun mock.
"""
import os

import pytest

from bouzecode.web_v2.services.work import micros
from bouzecode.web_v2.services.work.cloture_micros import ouvrir_micros_de_cloture


def _ticket_issu_dune_macro(titre_macro="Refaire le Bureau", titre_micro="Mère"):
    """Reproduit la filiation que `fleet.py` écrit au dispatch : une micro rattachée à une
    macro a lancé un ticket. C'est CETTE macro que la clôture doit hériter."""
    macro = micros.ensure_macro(titre_macro)
    mere = micros.create_micro(titre=titre_micro, macro_id=macro["id"])
    micros.lier_ticket(mere["id"], slug="bouzecode", ticket_id="T1")
    return macro, mere


def _filles(exclure_ids):
    return [m for m in micros.list_micros() if m["id"] not in exclure_ids]


# --------------------------------------------- 0. en-têtes de brief recopiés par l'agent


def test_un_entete_de_contexte_recopie_ne_devient_pas_une_tache():
    """Mesuré le 2026-09-21 : 3 micros en base dont titre == corps == la première ligne du
    brief de l'agent (« Macro-tâche de rattachement : Finir l'assistant »). L'agent a recopié
    son propre contexte en croyant déclarer un point ouvert. Ce n'est pas une tâche."""
    _ticket_issu_dune_macro()
    avant = {m["id"] for m in micros.list_micros()}

    creees = ouvrir_micros_de_cloture(
        [
            {"titre": "Macro-tâche de rattachement : Finir l'assistant",
             "corps": "Macro-tâche de rattachement : Finir l'assistant"},
            "Informations communes au chantier :",
            "Précisions :",
            #  Sans accents : un titre recopié en perd souvent, la comparaison est à plat.
            "Macro-tache de rattachement : Gillot",
        ],
        ticket_id="T1",
        slug="bouzecode",
    )

    assert creees == []
    assert {m["id"] for m in micros.list_micros()} == avant


def test_le_prefixe_tache_du_brief_est_retire_mais_la_ligne_reste():
    """`Tâche : {titre}` ANNONCE une vraie action : on jette l'étiquette, pas la ligne."""
    _ticket_issu_dune_macro()
    avant = {m["id"] for m in micros.list_micros()}

    creees = ouvrir_micros_de_cloture(
        [{"titre": "Tâche : répondre à Nathan sur la planification du cours",
          "corps": "Mail du 21/09"}],
        ticket_id="T1",
        slug="bouzecode",
    )

    assert len(creees) == 1
    fille = _filles(avant)[0]
    assert fille["titre"] == "répondre à Nathan sur la planification du cours"
    assert fille["corps"] == "Mail du 21/09"


def test_un_titre_ordinaire_traverse_le_garde_fou_intact():
    """Le garde-fou ne mord QUE les en-têtes du brief : une tâche qui contient un deux-points
    ou le mot « précisions » au milieu ne doit pas être mutilée."""
    _ticket_issu_dune_macro()
    avant = {m["id"] for m in micros.list_micros()}

    creees = ouvrir_micros_de_cloture(
        ["Corriger bureau_lignes : le statut ment", "Demander des précisions à Yann"],
        ticket_id="T1",
        slug="bouzecode",
    )

    assert len(creees) == 2
    titres = sorted(f["titre"] for f in _filles(avant))
    assert titres == ["Corriger bureau_lignes : le statut ment",
                      "Demander des précisions à Yann"]


# ------------------------------------------------------------------ 1. héritage


def test_les_taches_restantes_heritent_de_la_macro_du_ticket_parent():
    macro, mere = _ticket_issu_dune_macro()

    creees = ouvrir_micros_de_cloture(
        [{"titre": "Purger le cache au redémarrage", "corps": "Voir services/cache.py"}],
        ticket_id="T1",
        slug="bouzecode",
    )

    assert len(creees) == 1
    fille = micros.get_micro(creees[0]["id"])
    assert fille["titre"] == "Purger le cache au redémarrage"
    assert fille["corps"] == "Voir services/cache.py"
    #  L'héritage : aucun titre de macro n'a été déclaré par l'agent, et pourtant la fille
    #  est rattachée au MÊME chantier que le ticket qu'elle prolonge.
    assert fille["macro_id"] == macro["id"]
    #  Elle naît en brouillon : un dispatch exige `prete`, donc rien ne part sans relecture.
    assert fille["etat"] == "brouillon"
    assert fille["origine"] == "cloture_agent"
    assert fille["id"] != mere["id"]


def test_lheritage_gagne_contre_la_macro_proposee_par_lagent():
    """La règle utilisateur est un DÉFAUT qui s'impose : un agent qui invente un nom de
    chantier ne doit pas éparpiller les suites d'un ticket déjà rattaché."""
    macro, _ = _ticket_issu_dune_macro(titre_macro="Chantier réel")

    creees = ouvrir_micros_de_cloture(
        [{"titre": "Suite", "macro_titre": "Un nom que j'invente"}],
        ticket_id="T1",
    )

    assert micros.get_micro(creees[0]["id"])["macro_id"] == macro["id"]
    #  Et surtout : le chantier inventé n'a PAS été créé au passage.
    titres = [m["titre"] for m in micros.list_macros()]
    assert "Un nom que j'invente" not in titres


# ------------------------------------------------------- 2. replis de rattachement


def test_sans_ticket_parent_la_macro_nommee_par_lagent_est_creee():
    creees = ouvrir_micros_de_cloture(
        [{"titre": "Documenter le pont", "macro_titre": "Bureau"}],
        ticket_id="",
    )

    fille = micros.get_micro(creees[0]["id"])
    assert fille["macro_id"]
    assert micros.get_macro(fille["macro_id"])["titre"] == "Bureau"


def test_un_ticket_sans_macro_ne_fabrique_aucun_chantier():
    """Le contraire de la règle du Bureau : une puce non rattachée tombe dans « Non
    rattachées », elle n'invente pas un chantier par ticket."""
    avant = len(micros.list_macros())

    creees = ouvrir_micros_de_cloture([{"titre": "Point isolé"}], ticket_id="T404")

    assert micros.get_micro(creees[0]["id"])["macro_id"] == ""
    assert len(micros.list_macros()) == avant


# ---------------------------------------------------------------- 3. decision=true


def test_un_point_a_arbitrer_devient_une_micro_decision_en_brouillon():
    creees = ouvrir_micros_de_cloture(
        [{"titre": "Faut-il garder le poller ?", "decision": True}], ticket_id=""
    )

    fille = micros.get_micro(creees[0]["id"])
    assert fille["decision"] is True
    assert fille["etat"] == "brouillon"


# ------------------------------------------------------------ 4. anti-doublon


def test_deux_clotures_avec_le_meme_point_ne_creent_quune_micro():
    macro, _ = _ticket_issu_dune_macro()
    item = {"titre": "Purger le cache"}

    premiere = ouvrir_micros_de_cloture([item], ticket_id="T1")
    seconde = ouvrir_micros_de_cloture([dict(item, titre="  purger LE cache  ")], ticket_id="T1")

    assert len(premiere) == 1
    assert seconde == []
    filles = [m for m in micros.list_micros() if m["origine"] == "cloture_agent"]
    assert len(filles) == 1


# --------------------------------------------------------- 5. rien ne se dispatche


def test_le_pont_ne_lance_rien():
    _ticket_issu_dune_macro()

    ouvrir_micros_de_cloture([{"titre": "Suite A"}, {"titre": "Suite B"}], ticket_id="T1")

    filles = [m for m in micros.list_micros() if m["origine"] == "cloture_agent"]
    assert len(filles) == 2
    assert all(m["etat"] == "brouillon" for m in filles)
    #  `micro_tickets` veut dire « tickets LANCÉS par cette micro ». Lier le ticket PARENT
    #  inverserait la filiation et casserait l'héritage au cycle suivant.
    assert all(not m.get("tickets") for m in filles)


# ------------------------------------------------------------------ 6. robustesse


@pytest.mark.parametrize(
    "declaration",
    [None, [], [""], ["   "], [{"titre": ""}], [{}], [None], "pas une liste"],
)
def test_une_declaration_vide_ou_biscornue_ne_cree_rien(declaration):
    assert ouvrir_micros_de_cloture(declaration, ticket_id="T1") == []
    assert [m for m in micros.list_micros() if m["origine"] == "cloture_agent"] == []


def test_une_chaine_nue_est_acceptee_comme_titre():
    """Tolérance identique à `todo_board._puce` : une clôture peut avoir écrit des chaînes."""
    creees = ouvrir_micros_de_cloture(["Repasser sur les logs"], ticket_id="")

    assert micros.get_micro(creees[0]["id"])["titre"] == "Repasser sur les logs"


# --------------------------------------------------- 7. bout en bout via FinalAnswer


def _cloture(monkeypatch, ticket_id, taches_restantes, run_kind="work"):
    """Clôture acceptée : `_final_answer` déclare, la boucle qui ferme la session ouvre."""
    from bouzecode.backend.tools.registration import (
        _final_answer, ouvrir_micros_de_cloture_acceptee,
    )

    monkeypatch.setenv("BOUZECODE_TICKET_ID", ticket_id)
    monkeypatch.setenv("BOUZECODE_TICKET_SLUG", "bouzecode")
    monkeypatch.setenv("BOUZECODE_RUN_KIND", run_kind)
    config = {"_state": type("S", (), {})()}
    sortie = _final_answer(
        "Livré.", config, taches_terminees=["fait"], taches_restantes=taches_restantes
    )
    ouvrir_micros_de_cloture_acceptee(config)
    return sortie


def test_final_answer_ouvre_les_micros_du_ticket_courant(monkeypatch):
    macro, _ = _ticket_issu_dune_macro()

    _cloture(monkeypatch, "T1", [{"titre": "Reste à brancher le poller"}])

    filles = [m for m in micros.list_micros() if m["origine"] == "cloture_agent"]
    assert [m["titre"] for m in filles] == ["Reste à brancher le poller"]
    assert filles[0]["macro_id"] == macro["id"]


def test_un_run_de_validation_ne_remplit_pas_le_bureau(monkeypatch):
    """Un validateur partage le prompt du codeur et déclare parfois des restes : ses items
    feraient double emploi avec ceux du codeur."""
    _ticket_issu_dune_macro()

    _cloture(monkeypatch, "T1", [{"titre": "Doublon de validateur"}], run_kind="validation")

    assert [m for m in micros.list_micros() if m["origine"] == "cloture_agent"] == []


def test_une_cloture_qui_plante_le_pont_reste_acceptee(monkeypatch):
    """La déclaration dans le JSON de session est la source de vérité : un pont cassé ne doit
    JAMAIS empêcher un agent de rendre sa réponse."""
    from bouzecode.web_v2.services.work import cloture_micros

    def _boom(*_a, **_k):
        raise RuntimeError("base indisponible")

    monkeypatch.setattr(cloture_micros, "ouvrir_micros_de_cloture", _boom)
    sortie = _cloture(monkeypatch, "T1", [{"titre": "Peu importe"}])

    assert "final answer delivered" in sortie
