# [desc] Registre des agents du TUI : arbre principal/enfants/petits-enfants, routage d'un message selon l'etat de l'agent, questions bloquantes, interruption en cascade, alertes, conso lue sur l'AgentState. [/desc]
"""Le registre est la seule verite partagee entre les fils des sous-agents et la barre :
tout ce que l'utilisateur voit et tape passe par lui. Aucun terminal, aucun LLM."""
from __future__ import annotations

import threading
from types import SimpleNamespace

from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.multi_agent.en_process.fiche import (
    ANNULE, EN_COURS, FINI, PRINCIPAL, QUESTION, FicheAgent)
from bouzecode.backend.multi_agent.en_process.registre import RegistreAgents


def _tache():
    return SimpleNamespace(_cancel_flag=False)


def _registre_avec(*fiches):
    registre = RegistreAgents()
    registre.declarer_principal(AgentState(), "claude-opus-5")
    for fiche in fiches:
        registre.ajouter(fiche)
    return registre


def test_l_arbre_range_chaque_petit_enfant_sous_son_parent():
    """La barre liste main, puis chaque sous-agent suivi de ses propres enfants."""
    registre = _registre_avec(
        FicheAgent(id="a", description="alpha", profondeur=1, tache=_tache()),
        FicheAgent(id="b", description="beta", profondeur=1, tache=_tache()),
        FicheAgent(id="a1", parent_id="a", description="alpha.1", profondeur=2, tache=_tache()))
    assert [f.id for f in registre.arbre()] == [PRINCIPAL, "a", "a1", "b"]


def test_un_message_a_un_agent_en_cours_attend_sa_prochaine_etape():
    """Agent qui travaille : le message part dans SA boite aux lettres, pas chez un autre."""
    registre = _registre_avec(FicheAgent(id="a", description="alpha", tache=_tache()),
                              FicheAgent(id="b", description="beta", tache=_tache()))
    retour = registre.envoyer("a", "regarde aussi le README")
    assert "mis en file" in retour
    assert registre.relever("b") == []
    assert registre.relever("a") == ["regarde aussi le README"]
    assert registre.relever("a") == []


def test_un_message_a_un_agent_fini_le_relance():
    """Agent fini : le message le fait reprendre (meme conversation)."""
    relances = []
    fiche = FicheAgent(id="a", description="alpha", etat=FINI, tache=_tache(),
                       reprendre=relances.append)
    registre = _registre_avec(fiche)
    assert "reprend" in registre.envoyer("a", "et maintenant les tests")
    assert relances == ["et maintenant les tests"]


def test_la_question_d_un_sous_agent_bloque_jusqu_a_la_reponse_tapee_dans_sa_vue():
    """AskUserQuestion d'un sous-agent : etat « question », puis la reponse (ici le numero
    d'une option) le debloque avec le libelle de l'option."""
    registre = _registre_avec(FicheAgent(id="a", description="alpha", tache=_tache()))
    recu = {}
    fil = threading.Thread(target=lambda: recu.setdefault(
        "reponse", registre.poser_question("a", "Quelle base ?", ["rec", "prod"])))
    fil.start()
    while registre.fiche("a").etat != QUESTION:
        registre.attendre_changement(0.1)
    assert "réponse transmise" in registre.envoyer("a", "2")
    fil.join(5)
    assert recu["reponse"] == "prod"
    assert registre.fiche("a").etat == EN_COURS and registre.fiche("a").question is None


def test_interrompre_un_agent_interrompt_ses_descendants_et_debloque_sa_question():
    registre = _registre_avec(
        FicheAgent(id="a", description="alpha", tache=_tache()),
        FicheAgent(id="a1", parent_id="a", description="alpha.1", profondeur=2, tache=_tache()),
        FicheAgent(id="b", description="beta", tache=_tache()))
    recu = {}
    fil = threading.Thread(target=lambda: recu.setdefault(
        "reponse", registre.poser_question("a", "On continue ?")))
    fil.start()
    while registre.fiche("a").etat != QUESTION:
        registre.attendre_changement(0.1)
    assert sorted(registre.interrompre("a")) == ["a", "a1"]
    fil.join(5)
    assert "interrompu" in recu["reponse"]
    assert registre.fiche("b").tache._cancel_flag is False
    assert registre.interrompre(PRINCIPAL) == []


def test_signaler_d_un_sous_agent_apparait_une_fois_dans_les_alertes():
    registre = _registre_avec(FicheAgent(id="a", description="alpha", tache=_tache()))
    registre.signaler("a", "bloquant", "base rec injoignable")
    assert registre.fiche("a").alertes == ["[bloquant] base rec injoignable"]
    assert registre.alertes_nouvelles() == [
        "⚑ [bloquant] base rec injoignable — sous-agent alpha"]
    assert registre.alertes_nouvelles() == []


def test_la_conso_se_lit_sur_la_comptabilite_des_tours():
    """Tokens = les totaux de l'AgentState ; cout calcule si le modele a un tarif, sinon None
    (jamais un faux 0 $)."""
    state = AgentState()
    state.total_input_tokens, state.total_output_tokens = 12_000, 800
    state.total_cache_read_tokens = 40_000
    fiche = FicheAgent(id="a", modele="claude-opus-5", state=state)
    assert fiche.tokens() == {"entree": 12_000, "sortie": 800, "cache_lu": 40_000, "cache_ecrit": 0}
    assert fiche.cout() is not None and fiche.cout() > 0
    assert FicheAgent(id="b", modele="modele-sans-tarif", state=state).cout() is None


def test_un_agent_interrompu_n_est_plus_actif():
    fiche = FicheAgent(id="a", etat=ANNULE)
    assert not fiche.actif and fiche.icone == "■"
