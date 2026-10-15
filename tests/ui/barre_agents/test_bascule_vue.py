"""Basculer de vue rejoue la conversation de l'agent choisi — main compris.

Regression : main → sous-agent → main laissait la conversation du sous-agent a l'ecran
et n'imprimait que « retour à main ».
"""
from types import SimpleNamespace

from bouzecode.backend.multi_agent.en_process.fiche import PRINCIPAL, FicheAgent
from bouzecode.backend.multi_agent.en_process.registre import RegistreAgents
from bouzecode.ui.barre_agents.ecran import EcranAgents


def _ecran():
    registre = RegistreAgents()
    principal = SimpleNamespace(messages=[
        {"role": "user", "content": "QUESTION_DE_MAIN"},
        {"role": "assistant", "content": "REPONSE_DE_MAIN"}])
    registre.declarer_principal(principal, "claude-sonnet-4-5")
    enfant = SimpleNamespace(messages=[
        {"role": "user", "content": "CONSIGNE_DU_SOUS_AGENT"},
        {"role": "assistant", "content": "TRAVAIL_DU_SOUS_AGENT"}])
    registre.ajouter(FicheAgent(id="a1", description="tests", state=enfant))
    return EcranAgents(registre, {})


def test_retour_a_main_rejoue_la_conversation_de_main(capsys):
    ecran = _ecran()
    ecran.traiter(("vue", "a1"))
    vers_enfant = capsys.readouterr().out
    assert "TRAVAIL_DU_SOUS_AGENT" in vers_enfant
    assert "REPONSE_DE_MAIN" not in vers_enfant

    ecran.traiter(("vue", PRINCIPAL))
    retour = capsys.readouterr().out
    assert "╭─ main" in retour
    assert "QUESTION_DE_MAIN" in retour and "REPONSE_DE_MAIN" in retour
    assert "TRAVAIL_DU_SOUS_AGENT" not in retour
    assert ecran._vue_affichee == PRINCIPAL


def test_rechoisir_la_vue_deja_affichee_ne_rejoue_rien(capsys):
    ecran = _ecran()
    ecran.traiter(("vue", PRINCIPAL))
    assert capsys.readouterr().out == ""
