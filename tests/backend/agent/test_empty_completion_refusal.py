"""Un tour vide n'a pas une cause unique : le run doit distinguer un REFUS du modèle
(le backend l a deja relance ; la boucle coupe sans nudge) d un glitch de provider
(une relance debloque reellement certains modeles).

Mesure a l'origine de ces tests (2026-09-28, deux logs independants) :
  - collegue : coupure au TOUT PREMIER appel LLM (0 cached, 20K cache-write) -> zero
    relance, car `_last_batch_has_methodology` est faux tant qu'aucun batch assistant
    n'existe ;
  - utilisateur : 1 tour vide + 2 relances puis coupure (990K cached).
Dans les deux cas le retry backend ne s'est jamais arme (quelques tokens de
whitespace rendaient `text` non vide) : cf. tests/backend/providers/test_empty_completion_retry.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from e2e_harness import bouzecode  # noqa: E402
from fake_llm import MockLLM  # noqa: E402

PRODUCTIVE_TURN = (
    '<tool_use name="Methodology" id="m1"><param name="content">j\'avance</param></tool_use>'
    '<tool_use name="Bash" id="b1"><param name="command">echo hi</param></tool_use>'
)


def test_un_refus_du_modele_ferme_sans_relance_inutile():
    """finish_reason=content_filter => close_reason dedie, et AUCUNE relance payante."""
    mock = MockLLM([PRODUCTIVE_TURN, ("", "content_filter"), *([""] * 10)])

    result = bouzecode(["fais le travail"], mock_llm=mock, mock_tools=True,
                       config_overrides={"close_requires_final_answer": True})

    assert result.state.close_reason == "content_refusal", (
        f"close_reason={result.state.close_reason!r}, attendu 'content_refusal'"
    )
    assert result.state.close_detail and "refus" in result.state.close_detail.lower()
    # 1 tour productif + le tour refuse : relancer un refus est deterministe, donc inutile.
    assert mock.call_count == 2, (
        f"{mock.call_count} appels LLM — un refus a ete relance alors qu'il est deterministe"
    )


def test_un_tour_vide_au_premier_tour_garde_une_relance():
    """Sans aucun batch assistant precedent, le run avait 0 relance : il en garde 1."""
    mock = MockLLM([""] * 10)

    result = bouzecode(["fais le travail"], mock_llm=mock, mock_tools=True,
                       config_overrides={"close_requires_final_answer": True})

    assert mock.call_count >= 2, (
        "coupure des le premier tour vide : aucune relance n'a ete tentee"
    )
    assert result.state.close_reason == "empty_completion", (
        f"close_reason={result.state.close_reason!r}, attendu 'empty_completion'"
    )
    # Borne anti-boucle : le budget reste petit.
    assert mock.call_count <= 4, f"{mock.call_count} appels LLM — budget non borne"


def test_le_message_de_refus_ne_pretend_pas_qu_un_refus_est_definitif(capsys):
    """Session PBI du 2026-10-06 (poste 9403306K, claude-opus-5-5) : 11 refus en une session,
    la MÊME lecture de typography.md refusée deux fois puis acceptée à la troisième. Le message
    « retrying as-is would refuse again: rephrase » était faux ; l'utilisateur l'a recollé deux
    fois dans le chat et l'agent en a tiré une fausse cause (« trop d'actions par lot »).
    Le message doit dire que relancer peut suffire, sans prescrire de reformuler."""
    mock = MockLLM([PRODUCTIVE_TURN, ("", "content_filter"), *([""] * 10)])

    result = bouzecode(["fais le travail"], mock_llm=mock, mock_tools=True,
                       config_overrides={"close_requires_final_answer": True})

    stderr = capsys.readouterr().err
    for message in (result.state.close_detail, stderr):
        assert "refuse again" not in message and "même refus" not in message, message
        assert "reformule" not in message.lower() and "rephrase" not in message.lower(), message
    assert "relance" in result.state.close_detail.lower()
    assert "retry" in stderr.lower()
