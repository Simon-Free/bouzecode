# [desc] Conversation tests: une clôture refusée se complète sans retaper `answer`, et un lot muet ne la retient plus. [/desc]
"""Deux gaspillages mesurés le 2026-10-07 sur claude-opus-5-5 : la réponse finale retapée.

- d407d73d : `del temp_check_models.py` dans le MÊME lot que FinalAnswer. Le Bash a
  réussi sans rien écrire ; la clôture a quand même été suspendue, et le modèle a renvoyé
  une réponse quasi identique de 2 k caractères.
- c4fe6829 : le validateur refuse parce qu'un seul champ manque (`taches_restantes` avec
  `decision=true`) ; le texte complet est renvoyé pour corriger ce champ.
"""
from __future__ import annotations

import sys

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
ANSWER = "Les deux modèles marchent sur la préprod ; script temporaire supprimé."
TACHES_VIDES = ('<param name="taches_terminees">[]</param>'
                '<param name="taches_restantes">[]</param>')
FINAL = (f'<tool_use name="FinalAnswer" id="f1"><param name="answer">{ANSWER}</param>'
         f'{TACHES_VIDES}</tool_use>')
#  La reprise : ni `answer` ni recap, seulement les deux déclarations requises.
FINAL_SANS_ANSWER = f'<tool_use name="FinalAnswer" id="f2">{TACHES_VIDES}</tool_use>'
SUSPENDUE = "ta clôture n'a PAS été acceptée"


def _bash(commande: str) -> str:
    return f'<tool_use name="Bash" id="b1"><param name="command">{commande}</param></tool_use>'


def _contenus(result) -> list[str]:
    return [str(m.get("content", "")) for m in result.messages]


def test_supprimer_un_fichier_temporaire_dans_le_lot_de_cloture_clot_aussitot(tmp_path):
    """d407d73d : un Bash réussi et muet ne retient plus la clôture — un seul tour."""
    temporaire = tmp_path / "temp_check_models.py"
    temporaire.write_text("print('ok')\n", encoding="utf-8")
    commande = (f"Remove-Item '{temporaire}'" if sys.platform == "win32"
                else f"rm '{temporaire}'")
    mock = MockLLM([f"{METH}\n{_bash(commande)}\n{FINAL}", "JAMAIS CONSOMMÉ"])

    result = bouzecode(["les modèles marchent-ils ?"], mock_llm=mock)

    assert not temporaire.exists(), "le Bash du lot a bien tourné"
    assert not any(SUSPENDUE in c for c in _contenus(result)), "aucune clôture suspendue"
    assert result.state.close_reason == "final_answer"
    assert result.state.final_answer == ANSWER
    assert mock.call_count == 1


def test_une_cloture_suspendue_se_reemet_sans_retaper_la_reponse():
    """Un Bash qui ÉCRIT reste à lire ; l'avis dit d'omettre `answer`, et le texte est repris."""
    mock = MockLLM([f"{METH}\n{_bash('echo commit ef3ee4f4')}\n{FINAL}",
                    f"{METH}\n{FINAL_SANS_ANSWER}"])

    result = bouzecode(["commite et réponds"], mock_llm=mock)

    avis = [c for c in _contenus(result) if SUSPENDUE in c]
    assert len(avis) == 1, "la sortie du Bash n'avait pas été lue : une suspension"
    assert "SANS `answer`" in avis[0], "l'avis dit au modèle qu'il n'a rien à retaper"
    assert result.state.close_reason == "final_answer"
    assert result.state.final_answer == ANSWER, "le texte de la tentative suspendue est livré"
    reprise = [tc for m in result.messages if m.get("role") == "assistant"
               for tc in (m.get("tool_calls") or []) if tc["id"] == "f2"]
    assert reprise[0]["input"]["answer"] == ANSWER, "le transcript porte la réponse complète"


def test_un_refus_du_validateur_pour_un_seul_champ_se_corrige_sans_retaper(monkeypatch):
    """c4fe6829 : il manquait `decision=true` ; la reprise ne renvoie que les tâches."""
    vus = []

    def validateur(answer, config, recap, taches_terminees, taches_restantes, *_):
        vus.append(answer)
        if any(isinstance(t, dict) and t.get("decision") for t in taches_restantes or []):
            return True, ""
        return False, "l'accord pour déployer n'apparaît pas dans `taches_restantes`"

    monkeypatch.setattr("bouzecode.backend.agent.close_validator.validate_close", validateur)
    decision = ('<param name="taches_terminees">[]</param><param name="taches_restantes">'
                '<![CDATA[[{"titre": "Pousser develop et déployer", "decision": true}]]]>'
                '</param>')
    mock = MockLLM([f"{METH}\n{FINAL}",
                    f'{METH}\n<tool_use name="FinalAnswer" id="f2">{decision}</tool_use>'])

    result = bouzecode(["as-tu déployé ?"], mock_llm=mock)

    refus = [c for c in _contenus(result) if c.startswith("CLÔTURE REFUSÉE")]
    assert len(refus) == 1 and "SANS `answer`" in refus[0]
    assert vus == [ANSWER, ANSWER], "le validateur rejuge le MÊME texte, champ corrigé"
    assert result.state.final_answer == ANSWER
    assert result.state.taches_restantes[0]["decision"] is True


def test_une_demande_suivante_ne_ressuscite_pas_la_reponse_d_avant():
    """La tentative est oubliée à la clôture acceptée : un `answer` vide est refusé ensuite."""
    mock = MockLLM([f"{METH}\n{FINAL}", f"{METH}\n{FINAL_SANS_ANSWER}", "Rien à ajouter."])

    result = bouzecode(["première question", "seconde question"], mock_llm=mock)

    resultats = [str(m.get("content", "")) for m in result.messages
                 if m.get("role") == "tool" and m.get("name") == "FinalAnswer"]
    assert resultats[-1].startswith("Error: 'answer' is empty")


def _suspendue_puis_jamais_acceptee(entre_les_deux: list) -> object:
    """Une clôture suspendue (Bash qui écrit), le plafond de tours coupe AVANT toute
    acceptation ; puis [étapes REPL] ; puis une nouvelle demande close par FinalAnswer
    sans `answer`."""
    mock = MockLLM([f"{METH}\n{_bash('echo commit ef3ee4f4')}\n{FINAL}",
                    f"{METH}\n{FINAL_SANS_ANSWER}"])
    return bouzecode(["commite et réponds", *entre_les_deux, "autre chose"],
                     mock_llm=mock, config_overrides={"max_turns": 1})


def _resultat_de_la_reprise(result) -> str:
    return next(str(m.get("content", "")) for m in result.messages
                if m.get("role") == "tool" and m.get("tool_call_id") == "f2")


def test_une_tentative_jamais_acceptee_ne_survit_pas_a_la_demande_suivante():
    """La reprise ne vaut qu'au sein d'une demande : coupée avant acceptation, la tentative
    meurt avec sa boucle, et la demande suivante ne la reprend pas (même sans /clear)."""
    result = _suspendue_puis_jamais_acceptee([])

    assert result.state.close_reason != "final_answer"
    assert _resultat_de_la_reprise(result).startswith("Error: 'answer' is empty")


def test_apres_un_clear_une_cloture_sans_answer_ne_reprend_pas_l_ancienne(tmp_path, monkeypatch):
    """`/clear` ouvre une autre conversation : la clôture refusée d'avant est oubliée."""
    from bouzecode.backend.commands.core.basic import cmd_clear
    #  /clear enregistre d'abord la session qui s'achève (sessions/daily, figé à l'import).
    monkeypatch.setattr("bouzecode.backend.core.config.DAILY_DIR", tmp_path)
    #  Puis lui donne un `_session_id` : la conversation suivante journalise ses payloads.
    monkeypatch.setattr("bouzecode.backend.agent.payload_dump._payload_dir",
                        lambda session_id: tmp_path / "debug_payloads" / session_id)

    result = _suspendue_puis_jamais_acceptee([lambda state, config: cmd_clear("", state, config)])

    assert _resultat_de_la_reprise(result).startswith("Error: 'answer' is empty")
    assert result.state.final_answer != ANSWER
