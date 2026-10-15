# [desc] Le garde-fou de périmètre voit les tickets frères en doublon et les mandats read-only non tenus. [/desc]
"""Tests du garde-fou de périmètre, écrits sur le cas réel du manager `31b01ead`.

Ce manager a dispatché TROIS écrivains sur le même livrable (« mesure directe ») et ZÉRO
sur l'autre (« mesure indirecte »), et a briefé « READ-ONLY » des tickets à qui il donnait
la typologie `coder` — qui accorde Write/Edit/Bash. Les deux détections testées ici sont
mécaniques : elles n'exigent aucune coopération du LLM.
"""
from __future__ import annotations

import pytest

from bouzecode.web_v2.services.scope_guard import overlap, readonly, signature
from bouzecode.web_v2.tests.scope_guard_prompts import (
    DIRECTE_B, DIRECTE_ECRIVAIN, DIRECTE_IMPLEMENTATION, INDIRECTE_BLOQUANTE,
    INDIRECTE_READ_ONLY, INDIRECTE_TICKET_A, MESURE_DIRECTE, MESURE_INDIRECTE,
)


def _ticket(ticket_id: str, prompt: str, **extra) -> dict:
    return {"id": ticket_id, "title": prompt.splitlines()[0], "prompt": prompt,
            "parent": "6b4a9ce79dc1", **extra}


# --------------------------------------------------------------------------- signature

def test_deux_missions_sur_le_meme_livrable_se_ressemblent_plus_que_deux_moities_differentes():
    """La similarité doit SÉPARER : deux rédactions du même livrable au-dessus, les deux
    moitiés distinctes de la demande en dessous. C'est la propriété qui rend le seuil
    possible ; sans elle, tout seuil serait arbitraire."""
    meme_livrable = signature.similarity(
        signature.scope_signature(DIRECTE_B),
        signature.scope_signature(DIRECTE_IMPLEMENTATION),
    )
    livrables_differents = signature.similarity(
        signature.scope_signature(DIRECTE_B),
        signature.scope_signature(INDIRECTE_TICKET_A),
    )
    assert meme_livrable > livrables_differents
    assert meme_livrable >= overlap.OVERLAP_THRESHOLD
    assert livrables_differents < overlap.OVERLAP_THRESHOLD


def test_le_texte_des_regles_projet_commun_a_tous_ne_cree_pas_de_ressemblance():
    """Le bloc « RÈGLES PROJET » est identique dans les six prompts. Seul, il ne doit
    déclencher AUCUN doublon, sinon le garde-fou hurle à chaque dispatch."""
    regles_seules = "RÈGLES PROJET STRICTES : `uv run` jamais Poetry, VERDICT: OK, NE DÉPLOIE PAS."
    assert not overlap.overlapping_siblings(regles_seules, [_ticket("aaa", regles_seules + " Autre.")])


@pytest.mark.parametrize("prompt", MESURE_DIRECTE + MESURE_INDIRECTE)
def test_un_prompt_ne_produit_jamais_une_signature_vide(prompt):
    assert signature.scope_signature(prompt)


# ----------------------------------------------------------------------------- overlap

def test_le_troisieme_ecrivain_sur_la_mesure_directe_est_signale():
    """Le cas exact : deux tickets « mesure directe » existent déjà, le manager en
    dispatche un TROISIÈME. Les deux frères doivent être nommés."""
    freres = [_ticket("bed63826", DIRECTE_B), _ticket("a51cefa0", DIRECTE_IMPLEMENTATION)]
    doublons = overlap.overlapping_siblings(DIRECTE_ECRIVAIN, freres)
    assert {t["id"] for t in doublons} == {"bed63826", "a51cefa0"}


def test_la_mesure_indirecte_nest_pas_un_doublon_de_la_mesure_directe():
    """L'autre moitié de la demande doit passer : c'est un livrable DIFFÉRENT."""
    freres = [_ticket("bed63826", DIRECTE_B), _ticket("a51cefa0", DIRECTE_IMPLEMENTATION),
              _ticket("29e03369", DIRECTE_ECRIVAIN)]
    assert overlap.overlapping_siblings(INDIRECTE_TICKET_A, freres) == []


def test_les_trois_investigations_indirectes_sont_aussi_des_doublons_entre_elles():
    freres = [_ticket("744a1b03", INDIRECTE_TICKET_A), _ticket("869d263c", INDIRECTE_READ_ONLY)]
    doublons = overlap.overlapping_siblings(INDIRECTE_BLOQUANTE, freres)
    assert {t["id"] for t in doublons} == {"744a1b03", "869d263c"}


def test_un_ticket_archive_nest_plus_un_frere_concurrent():
    """Un livrable ARCHIVÉ ne couvre plus rien : le redispatcher est légitime."""
    freres = [_ticket("bed63826", DIRECTE_B, archived=True)]
    assert overlap.overlapping_siblings(DIRECTE_ECRIVAIN, freres) == []


def test_le_commentaire_de_doublon_nomme_les_freres_et_le_taux():
    freres = [_ticket("bed63826", DIRECTE_B)]
    doublons = overlap.overlapping_siblings(DIRECTE_ECRIVAIN, freres)
    texte = overlap.overlap_comment(doublons)
    assert "bed63826" in texte and "%" in texte


# ---------------------------------------------------------------------------- readonly

@pytest.mark.parametrize("prompt", MESURE_INDIRECTE)
def test_un_mandat_read_only_est_reconnu(prompt):
    assert readonly.declares_read_only(prompt)


@pytest.mark.parametrize("prompt", MESURE_DIRECTE)
def test_une_mission_decriture_nest_pas_prise_pour_un_mandat_read_only(prompt):
    assert not readonly.declares_read_only(prompt)


def test_read_only_confie_a_la_typologie_coder_est_signale_avec_les_outils_fautifs():
    """`coder` accorde Write/Edit/Bash : le mandat READ-ONLY n'est que de la prose.
    C'est le défaut qui a laissé `e6846ab5` écrire du code de production et une migration."""
    fautifs = readonly.unenforced_read_only(INDIRECTE_BLOQUANTE, "coder")
    assert "Write" in fautifs and "Edit" in fautifs


def test_read_only_confie_a_une_typologie_sans_outil_decriture_ne_declenche_rien():
    """`manager` n'a que Read/Glob/Grep + pilotage de flotte : le mandat est TENU."""
    assert readonly.unenforced_read_only(INDIRECTE_BLOQUANTE, "manager") == []


def test_une_mission_decriture_confiee_a_coder_ne_declenche_rien():
    assert readonly.unenforced_read_only(DIRECTE_B, "coder") == []


def test_le_commentaire_read_only_nomme_les_outils_accordes():
    texte = readonly.readonly_comment(readonly.unenforced_read_only(INDIRECTE_BLOQUANTE, "coder"))
    assert "Write" in texte and "READ-ONLY" in texte
