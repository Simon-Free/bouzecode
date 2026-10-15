# [desc] Conversation tests: closing in the same batch as a data tool answers on a result nobody read. [/desc]
"""Un résultat d'outil n'est rendu qu'au tour SUIVANT.

Clore dans le même lot qu'un outil producteur de données ferme donc la session
avant que ce résultat n'ait jamais été lu — même quand l'outil a parfaitement
fonctionné. C'est la moitié manquante de `test_close_over_failed_tool_e2e` : là
l'outil n'avait pas tourné, ici il a tourné et personne n'a lu sa sortie.

Autopsie de la conversation Focus 6e67be34 (2026-08-18) : 16 appels d'outils ET la
clôture dans une SEULE complétion. Le modèle avait écrit lui-même les résultats
qu'il attendait ; les vrais — dont `relation "f_train_jour" does not exist` —
n'ont jamais été lus, et les 8 chiffres livrés à l'utilisateur étaient inventés.
"""
from __future__ import annotations

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
METH2 = '<tool_use name="Methodology" id="m2"><param name="content">suite</param></tool_use>'
ANSWER = "La capacité réelle est inférieure de 3 % à la prévision J-30."
FINAL = ('<tool_use name="FinalAnswer" id="f1">'
         f'<param name="answer">{ANSWER}</param>'
         '<param name="taches_terminees">[]</param>'
         '<param name="taches_restantes">[]</param></tool_use>')
BASH_OK = '<tool_use name="Bash" id="b1"><param name="command">echo ok</param></tool_use>'


def _refusal_notices(result):
    return [
        str(m.get("content", "")) for m in result.messages
        if "ta clôture n'a PAS été acceptée" in str(m.get("content", ""))
    ]


def test_closing_beside_a_data_tool_is_refused_once():
    """Le lot livre une réponse et lance l'outil censé la fonder, en même temps."""
    mock = MockLLM([
        f"{METH}\n{BASH_OK}\n{FINAL}",  # répond sans avoir pu lire le résultat
        f"{METH}\n{FINAL}",             # a lu, confirme, clôt
    ])
    result = bouzecode(["compare la capacité J-30 et la capacité réelle"], mock_llm=mock)

    notices = _refusal_notices(result)
    assert len(notices) == 1, "la clôture doit être refusée exactement une fois"
    assert "Bash" in notices[0], "le message doit nommer l'outil jamais lu"
    assert "n'invente jamais" in notices[0].lower()
    assert result.state.close_reason == "final_answer"
    assert result.state.final_answer == ANSWER


def test_a_close_with_nothing_to_read_passes_immediately():
    """Methodology est de la comptabilité : le modèle écrit dedans, il n'en lit rien."""
    mock = MockLLM([f"{METH}\n{METH2}\n{FINAL}", "JAMAIS CONSOMMÉ"])
    result = bouzecode(["réponds"], mock_llm=mock)

    assert _refusal_notices(result) == []
    assert result.state.close_reason == "final_answer"


def _fil(mock, appel: int) -> str:
    """Ce que le modèle a RÉELLEMENT reçu à cet appel (le fil minimal, pas le journal)."""
    return "\n".join(str(m.get("content", "")) for m in mock.get_messages(appel))


def test_the_real_result_reaches_the_model_before_it_re_answers():
    """Tout l'objet du refus : le tour suivant PORTE le résultat réel, et l'avis avec."""
    bash = BASH_OK.replace("echo ok", "echo RESULTAT_REEL_DU_LOT")
    mock = MockLLM([f"{METH}\n{bash}\n{FINAL}", f"{METH}\n{FINAL}"])
    bouzecode(["réponds"], mock_llm=mock)

    fil = _fil(mock, 1)
    assert "ta clôture n'a PAS été acceptée" in fil
    assert "RESULTAT_REEL_DU_LOT" in fil, (
        "essai 3 : l'avis partait SEUL sur le fil (keep=0), le résultat promis n'y était pas"
    )


def test_a_validator_refusal_reaches_the_model_with_the_batch_results():
    """Essai 3, tour 37 : le refus du validateur n'est jamais arrivé au modèle."""
    recap = '<param name="recap">{"symptoms": "s", "explanation": "e"}</param>'
    bash = BASH_OK.replace("echo ok", "echo SORTIE_DU_NETTOYAGE")
    mock = MockLLM([f"{METH}\n{bash}\n{FINAL}",
                    f"{METH}\n{FINAL.replace('</tool_use>', recap + '</tool_use>')}"])
    bouzecode(["compare"], mock_llm=mock,
              config_overrides={"require_recap": True, "recap_coding": False,
                                "close_validation": True, "recap_expects_object": True,
                                "model": "claude-sonnet-4-5"})

    fil = _fil(mock, 1)
    assert "récap incomplet" in fil, "le motif du refus doit être sur le fil"
    assert "SORTIE_DU_NETTOYAGE" in fil, "le résultat de l'autre outil du lot aussi"
    assert "Déjà EXÉCUTÉS" in fil


def test_an_agent_that_never_reads_still_closes_under_the_budget():
    """Le refus est borné : il coûte des tours, il ne gèle jamais une session."""
    mock = MockLLM([f"{METH}\n{BASH_OK}\n{FINAL}"] * 6)
    result = bouzecode(["réponds"], mock_llm=mock)

    assert len(_refusal_notices(result)) == 3, "MAX_CLOSE_REFUSALS"
    assert result.state.close_reason == "close_over_unread_results"
    assert result.state.final_answer == ANSWER


def test_the_refusal_says_the_batch_already_ran_so_it_is_not_replayed():
    """Assistant du Bureau : sa précision, jointe à la clôture refusée, a été renvoyée."""
    mock = MockLLM([f"{METH}\n{BASH_OK}\n{FINAL}", f"{METH}\n{FINAL}"])
    result = bouzecode(["précise la tâche"], mock_llm=mock)

    notice = _refusal_notices(result)[0]
    assert "ONT été exécutés" in notice
    assert "ne les rejoue PAS" in notice


def test_a_validator_refusal_also_says_the_other_tools_of_the_batch_ran():
    """Clôture refusée par le validateur (récap omis) : le Bash du lot, lui, a tourné."""
    recap = '<param name="recap">{"symptoms": "s", "explanation": "e"}</param>'
    mock = MockLLM([f"{METH}\n{BASH_OK}\n{FINAL}",
                    f"{METH}\n{FINAL.replace('</tool_use>', recap + '</tool_use>')}"])
    result = bouzecode(["compare"], mock_llm=mock,
                       config_overrides={"require_recap": True, "recap_coding": False,
                                         "close_validation": True, "recap_expects_object": True,
                                         "model": "claude-sonnet-4-5"})

    notes = [str(m.get("content", "")) for m in result.messages
             if "Déjà EXÉCUTÉS" in str(m.get("content", ""))]
    assert len(notes) == 1 and "Bash" in notes[0]
    assert "Ne les rejoue PAS" in notes[0]
    assert result.state.final_answer == ANSWER
